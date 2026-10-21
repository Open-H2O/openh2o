# SPDX-License-Identifier: AGPL-3.0-or-later
"""
150.3-01 Task 1: a point of diversion's lining sets its default seepage share.

Each point of diversion has a lined, unlined or pipe choice to help with
seepage calcs. A point whose losses are
still the platform's default takes 25 percent seepage if unlined, 5 percent if
lined and 0 if pipe. A share marked as measured or estimated is never
overwritten, and a point whose lining is not stated keeps whatever
seepage it holds, so nothing moves until someone states the lining.
"""
from decimal import Decimal

import pytest

from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.forms import PointOfDiversionForm
from surface.models import (
    LINED_DEFAULT_SEEPAGE,
    OPEN_CANAL_DEFAULT_EVAPORATION,
    PIPE_DEFAULT_EVAPORATION,
    PIPE_DEFAULT_SEEPAGE,
    UNLINED_DEFAULT_SEEPAGE,
    PointOfDiversion,
    default_evaporation_fraction,
    default_seepage_fraction,
)
from tests.factories import PointOfDiversionFactory

pytestmark = pytest.mark.django_db


def test_the_three_defaults():
    assert UNLINED_DEFAULT_SEEPAGE == Decimal("0.2500")
    assert LINED_DEFAULT_SEEPAGE == Decimal("0.0500")
    assert PIPE_DEFAULT_SEEPAGE == Decimal("0")
    assert default_seepage_fraction("unlined") == Decimal("0.2500")
    assert default_seepage_fraction("lined") == Decimal("0.0500")
    assert default_seepage_fraction("pipe") == Decimal("0")
    assert default_seepage_fraction(None) is None
    assert default_seepage_fraction("") is None
    assert OPEN_CANAL_DEFAULT_EVAPORATION == Decimal("0.0100")
    assert PIPE_DEFAULT_EVAPORATION == Decimal("0")
    assert default_evaporation_fraction("unlined") == Decimal("0.0100")
    assert default_evaporation_fraction("lined") == Decimal("0.0100")
    assert default_evaporation_fraction("pipe") == Decimal("0")
    assert default_evaporation_fraction(None) is None


@pytest.mark.parametrize(
    "lining, expected",
    [("unlined", Decimal("0.2500")), ("lined", Decimal("0.0500")), ("pipe", Decimal("0"))],
)
def test_default_basis_takes_the_lining_default(lining, expected):
    pod = PointOfDiversionFactory(lining=lining, loss_basis="default")
    pod.refresh_from_db()
    assert pod.seepage_fraction == expected


def test_district_estimate_keeps_its_own_seepage():
    pod = PointOfDiversionFactory(
        lining="unlined", loss_basis="district_estimate", seepage_fraction=Decimal("0.1200")
    )
    pod.refresh_from_db()
    assert pod.seepage_fraction == Decimal("0.1200")


def test_measured_point_changing_lining_changes_only_the_lining():
    pod = PointOfDiversionFactory(
        lining="unlined", loss_basis="measured", seepage_fraction=Decimal("0.0730")
    )
    pod.lining = "pipe"
    pod.save()
    pod.refresh_from_db()
    assert pod.lining == "pipe"
    assert pod.seepage_fraction == Decimal("0.0730")
    assert pod.evaporation_fraction == Decimal("0.0100")


def test_lining_not_stated_keeps_the_stored_seepage():
    pod = PointOfDiversionFactory(lining=None, loss_basis="default", seepage_fraction=Decimal("0.0300"))
    pod.refresh_from_db()
    assert pod.lining is None
    assert pod.seepage_fraction == Decimal("0.0300")


def test_existing_points_have_no_lining():
    """A point created without a lining has none: nothing moves on migrate."""
    pod = PointOfDiversionFactory()
    pod.refresh_from_db()
    assert pod.lining is None
    assert pod.seepage_fraction == Decimal("0")


def test_returning_to_default_basis_takes_the_lining_default():
    pod = PointOfDiversionFactory(
        lining="lined", loss_basis="district_estimate", seepage_fraction=Decimal("0.0900")
    )
    pod.loss_basis = "default"
    pod.save()
    pod.refresh_from_db()
    assert pod.seepage_fraction == Decimal("0.0500")


def test_save_with_update_fields_writes_the_derived_seepage():
    pod = PointOfDiversionFactory(loss_basis="default")
    pod.lining = "unlined"
    pod.save(update_fields=["lining"])
    pod.refresh_from_db()
    assert pod.seepage_fraction == Decimal("0.2500")


def test_full_clean_checks_the_derived_seepage():
    """The three shares must stay below 1 with the default the lining sets."""
    from django.core.exceptions import ValidationError

    pod = PointOfDiversionFactory(loss_basis="default")
    pod.lining = "unlined"
    pod.spill_fraction = Decimal("0.7400")
    with pytest.raises(ValidationError):
        pod.full_clean()


def test_history_records_the_lining_and_seepage_change():
    pod = PointOfDiversionFactory(loss_basis="default")
    pod.lining = "unlined"
    pod.save()
    latest = pod.events.order_by("-pgh_id").first()
    assert latest.lining == "unlined"
    assert latest.seepage_fraction == Decimal("0.2500")


def test_lining_choices():
    field = PointOfDiversion._meta.get_field("lining")
    assert [value for value, _ in field.choices] == ["unlined", "lined", "pipe"]
    assert field.null and field.blank


# ---------------------------------------------------------------------------
# Task 3: a pipe's default evaporation is 0
# ---------------------------------------------------------------------------


def test_pipe_default_has_no_evaporation_and_an_open_canal_gets_it_back():
    pod = PointOfDiversionFactory(lining="pipe", loss_basis="default")
    pod.refresh_from_db()
    assert pod.evaporation_fraction == Decimal("0")
    pod.lining = "unlined"
    pod.save()
    pod.refresh_from_db()
    assert pod.evaporation_fraction == Decimal("0.0100")
    assert pod.seepage_fraction == Decimal("0.2500")


def test_district_estimate_pipe_keeps_its_own_evaporation():
    pod = PointOfDiversionFactory(
        lining="pipe", loss_basis="district_estimate", evaporation_fraction=Decimal("0.0040")
    )
    pod.refresh_from_db()
    assert pod.evaporation_fraction == Decimal("0.0040")


# ---------------------------------------------------------------------------
# The form and the page
# ---------------------------------------------------------------------------


def _form_data(pod, **overrides):
    data = {
        "name": pod.name,
        "status": "active",
        "loss_basis": "default",
        "lining": "",
        "evaporation_fraction": "0.0100",
        "seepage_fraction": "0",
        "spill_fraction": "0",
    }
    data.update(overrides)
    return data


def test_form_blank_lining_saves_as_not_stated():
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(_form_data(pod), instance=pod)
    assert form.is_valid(), form.errors
    assert form.save().lining is None
    assert form.fields["lining"].choices[0] == ("", "Not stated")


def test_form_lined_default_replaces_the_typed_seepage():
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(
        _form_data(pod, lining="lined", seepage_fraction="0.3000"), instance=pod
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    saved.refresh_from_db()
    assert saved.seepage_fraction == Decimal("0.0500")


def test_form_checks_the_sum_on_the_lining_default():
    """Typed shares sum to 0.75; with the unlined default they sum to 1.00."""
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(
        _form_data(pod, lining="unlined", spill_fraction="0.7400"), instance=pod
    )
    assert not form.is_valid()
    messages = form.non_field_errors()
    assert sum("cannot exceed the whole" in m for m in messages) == 1


class _UserFactory:
    @staticmethod
    def create():
        from core.models import User

        return User.objects.create(
            username="liningviewer",
            email="liningviewer@example.com",
            password=make_password("testpass123"),
            is_active=True,
        )


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory.create())
    return c


def test_page_shows_the_lining_and_where_the_default_comes_from(auth_client):
    pod = PointOfDiversionFactory(lining="unlined", loss_basis="default")
    html = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "Lining" in html and "Unlined" in html
    assert "25.00%" in html
    assert "FAO Irrigation and Drainage Paper 61 gives unlined canals 20 to 30 percent" in html
    assert "Published water management plans report canal evaporation" in html
    assert "Platform default" in html
    assert "Spill depends on how the canal is operated" in html


def test_page_shows_no_default_note_for_a_district_estimate(auth_client):
    pod = PointOfDiversionFactory(
        lining="unlined", loss_basis="district_estimate", seepage_fraction=Decimal("0.1200")
    )
    html = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "12.00%" in html
    assert "Default for" not in html
    assert "No default." not in html


def test_page_says_not_stated_when_no_lining(auth_client):
    pod = PointOfDiversionFactory()
    html = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "Not stated" in html
    assert "Default with no lining stated." in html


def test_page_pipe_notes(auth_client):
    pod = PointOfDiversionFactory(lining="pipe", loss_basis="default")
    html = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert "puts pipeline seepage at zero" in html
    assert "A closed pipe has no open water surface" in html
    assert "Default for an open canal" not in html


# ---------------------------------------------------------------------------
# Task 4: the demonstration's points get their lining
# ---------------------------------------------------------------------------


def test_demo_lining_command_sets_each_named_point_once():
    from core.management.commands.seed_merced_pod_lining import (
        LINING_BY_POD,
        apply_demo_pod_lining,
    )

    atwater = PointOfDiversionFactory(name="MER-POD-004-DEMO Atwater Canal Headgate")
    hydro = PointOfDiversionFactory(name="MER-POD-010-DEMO Merced Falls Hydroelectric Diversion")
    riparian = PointOfDiversionFactory(name="MER-POD-009-DEMO Bottomlands Riparian Take")
    other = PointOfDiversionFactory(name="Somebody else's headgate")

    assert apply_demo_pod_lining() == 3
    for pod in (atwater, hydro, riparian, other):
        pod.refresh_from_db()
    assert atwater.lining == "unlined" and atwater.seepage_fraction == Decimal("0.2500")
    assert hydro.lining == "pipe" and hydro.evaporation_fraction == Decimal("0")
    assert riparian.lining is None and riparian.seepage_fraction == Decimal("0")
    assert other.lining is None and other.notes == ""
    assert atwater.notes == LINING_BY_POD[atwater.name][1]

    assert apply_demo_pod_lining() == 0
    atwater.refresh_from_db()
    assert atwater.notes.count("Demonstration data") == 1


def test_demo_lining_command_replaces_the_note_that_named_a_district():
    """A re-run takes out the first-built note and keeps the point's own notes.

    The first build appended a note naming a real district (since removed).
    The El Nido intake's own description sat before it.
    """
    from core.management.commands.seed_merced_pod_lining import (
        LINING_BY_POD,
        apply_demo_pod_lining,
    )

    name = "MER-BPOD-001 El Nido Canal Recharge Intake"
    own = "Shared recharge intake on the El Nido Canal."
    retired = (
        "Demonstration data: lining set to unlined, a real district's majority "
        "(406 miles of unlined canal against 105 of lined canal). No published "
        "source read states this canal's own lining."
    )
    intake = PointOfDiversionFactory(name=name, lining="unlined", notes=f"{own}\n\n{retired}")

    assert apply_demo_pod_lining() == 1
    intake.refresh_from_db()
    assert intake.notes == f"{own}\n\n{LINING_BY_POD[name][1]}"
    assert apply_demo_pod_lining() == 0


def test_form_basis_help_points_at_the_shares_below_it():
    """The basis sits above the three shares on the form (150.3-01)."""
    form = PointOfDiversionForm(instance=PointOfDiversionFactory())
    assert "three shares below" in form.fields["loss_basis"].help_text
