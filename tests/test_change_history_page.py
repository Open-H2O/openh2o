# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading the change history back: /changes/ (147-01 Task 4).

The History panel this module also covered on record pages was removed in
147-02 (Brent's 2026-09-24 checkpoint ruling: keep the recording, strip the
display); the reading functions it called (``changes_for``, field filtering)
stay and are still exercised directly here, since /changes/ reads through the
same code.

Every assertion is an exact value: the text a reader sees, the stored figure
formatted, the person's name. None re-derives a formula, and none asserts a
direction ("went up") that a wrong number could also satisfy.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.http import urlencode

from accounting.models import CalculationStep
from core.changes import changes_for, format_decimal, recent_changes
from core.history import command_context
from tests.factories import ParcelFactory, WellFactory, WellIrrigatedParcelFactory

pytestmark = pytest.mark.django_db

User = get_user_model()


def _client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def operator():
    return User.objects.create_user(
        username="op", email="op@example.org", password="x", is_active=True,
        first_name="Dana", last_name="Reyes",
    )


@pytest.fixture
def administrator():
    return User.objects.create_user(
        username="adm", email="adm@example.org", password="x", is_active=True,
        agency_admin=True, first_name="Lee", last_name="Ortiz",
    )


def _patch(client, url, **data):
    return client.patch(
        url, data=urlencode(data), content_type="application/x-www-form-urlencoded"
    )


# -- Formatting ------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored, shown",
    [
        ("12.5000", "12.50"),
        ("12.7500", "12.75"),
        ("12.5010", "12.501"),
        ("100.0000", "100.00"),
        ("0.0000", "0.00"),
        ("-2.2864", "-2.2864"),
        ("0.750", "0.75"),
    ],
)
def test_a_stored_decimal_is_shown_exactly(stored, shown):
    assert format_decimal(Decimal(stored)) == shown


# -- The rows ----------------------------------------------------------------------


def test_an_area_edit_renders_exact_before_and_after_with_the_person(operator):
    parcel = ParcelFactory(parcel_number="HIST-001", area_acres="12.50")
    _patch(
        _client(operator),
        reverse("parcels:edit_field", args=[parcel.pk]),
        field="area_acres",
        value="12.75",
    )

    rows = changes_for(parcel)
    assert [(r.action, r.who) for r in rows] == [("changed", "Dana Reyes"), ("added", "not recorded")]
    changed = rows[0]
    assert [(c.name, c.before, c.after) for c in changed.changes] == [
        ("Area acres", "12.50", "12.75")
    ]
    assert changed.record_type == "Use area"
    assert changed.record_name == "HIST-001"

    html = _client(operator).get(reverse("change_history")).content.decode()
    assert '<span class="change-value">12.50</span> &rarr; <span class="change-value">12.75</span>' in html
    assert "Dana Reyes" in html


def test_a_delete_shows_the_last_values(operator):
    well = WellFactory()
    wip = WellIrrigatedParcelFactory(well=well, fraction="0.4000")
    wip_pk = wip.pk
    wip.delete()

    page = recent_changes({"record_type": "wells.WellIrrigatedParcel", "object_id": wip_pk})
    rows = list(page.object_list)
    assert len(rows) == 1
    row = rows[0]
    # Added and removed with no request or command around either: one row.
    assert row.action == "added and removed"
    assert row.record_name == f"#{wip_pk} (removed)"
    assert ("Fraction", "", "0.40") in [(c.name, c.before, c.after) for c in row.changes]


def test_a_delete_after_an_earlier_insert_reads_removed(operator, administrator):
    well = WellFactory()
    wip = WellIrrigatedParcelFactory(well=well, fraction="0.4000")
    wip_pk = wip.pk
    with command_context(["manage.py", "prune_links"]):
        wip.delete()

    rows = list(
        recent_changes({"record_type": "wells.WellIrrigatedParcel", "object_id": wip_pk}).object_list
    )
    assert [r.action for r in rows] == ["removed", "added"]
    removed = rows[0]
    assert removed.who == "a command: prune_links"
    assert ("Fraction", "0.40", "") in [(c.name, c.before, c.after) for c in removed.changes]


def test_a_command_change_names_the_command(operator):
    parcel = ParcelFactory(area_acres="12.50")
    with command_context(["manage.py", "recalc_parcel_areas"]):
        type(parcel).objects.filter(pk=parcel.pk).update(area_acres=Decimal("13.00"))

    row = changes_for(parcel)[0]
    assert row.who == "a command: recalc_parcel_areas"
    assert [(c.before, c.after) for c in row.changes] == [("12.50", "13.00")]


def test_a_removed_person_is_named_by_number(operator):
    parcel = ParcelFactory(area_acres="12.50")
    _patch(
        _client(operator),
        reverse("parcels:edit_field", args=[parcel.pk]),
        field="area_acres",
        value="14.00",
    )
    gone = operator.pk
    User.objects.filter(pk=gone).delete()

    assert changes_for(parcel)[0].who == f"former user #{gone}"


def test_the_note_shows_on_the_row(administrator):
    call_command("seed_calculation_plan")
    step = CalculationStep.objects.get(step_type="clamp_floor")
    _client(administrator).post(
        reverse("accounting:methodology_step_config", args=[step.pk]),
        {"label": step.label, "floor": "2.5", "bank": "on", "note": "Board set a floor"},
    )

    row = changes_for(step)[0]
    assert row.note == "Board set a floor"
    assert [(c.name, c.before, c.after) for c in row.changes] == [("Config, floor", "0", "2.5")]


# -- The page and the panel -------------------------------------------------------


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_every_signed_in_role_reads_the_page_and_a_visitor_is_sent_to_sign_in(operator):
    assert not operator.is_administrator
    assert _client(operator).get(reverse("change_history")).status_code == 200
    anonymous = Client().get(reverse("change_history"))
    assert anonymous.status_code == 302
    assert "/accounts/login/" in anonymous["Location"]


def test_the_empty_page_says_so(operator):
    # Creating the reader is itself a recorded change; clear it, as the
    # demonstration's golden build does.
    call_command("clear_change_history", "--golden-build")
    html = _client(operator).get(reverse("change_history")).content.decode()
    assert "No changes recorded yet." in html
    assert "0 changes, newest first" in html


def test_filters_narrow_by_record_type_and_person(operator, administrator):
    # Setup writes first: inside one test transaction a request's history
    # context stays set for the statements after it (it is transaction-local,
    # and pytest runs the whole test as one transaction).
    parcel = ParcelFactory(area_acres="12.50")
    call_command("seed_calculation_plan")
    step = CalculationStep.objects.get(step_type="clamp_floor")
    _patch(_client(operator), reverse("parcels:edit_field", args=[parcel.pk]), field="area_acres", value="15.00")
    _client(administrator).post(reverse("accounting:methodology_step_toggle", args=[step.pk]))

    by_person = recent_changes({"person": str(operator.pk)})
    assert [(r.record_type, r.who) for r in by_person.object_list] == [("Use area", "Dana Reyes")]
    by_type = recent_changes({"record_type": "accounting.CalculationStep", "person": str(administrator.pk)})
    assert [(r.record_type, r.who) for r in by_type.object_list] == [("Calculation step", "Lee Ortiz")]

    html = _client(operator).get(
        reverse("change_history") + f"?person={operator.pk}"
    ).content.decode()
    assert "1 change, newest first" in html


def test_the_page_query_count_does_not_grow_with_the_history(operator, django_assert_max_num_queries):
    parcels = [ParcelFactory(area_acres="10.00") for _ in range(3)]
    client = _client(operator)
    url = reverse("change_history")
    client.get(url)  # warm the session and site config
    with CaptureQueriesContext(connection) as small:
        client.get(url)

    for parcel in parcels:
        for step in range(20):
            type(parcel).objects.filter(pk=parcel.pk).update(area_acres=Decimal(f"{11 + step}.00"))
    assert sum(p.events.count() for p in parcels) == 3 + 3 * 20 * 2

    with django_assert_max_num_queries(len(small)):
        client.get(url)


def test_changes_for_can_be_limited_to_the_settings_one_page_shows(administrator):
    """``fields=`` still limits a settings row's changes to the named columns.

    147-01 used this to keep the delivery settings page's (now-removed)
    History panel from showing a surface-only setting on a deployment with no
    Surface module. The panel is gone (147-02), but ``changes_for``'s field
    filtering is the same reading code ``/changes/`` uses, so it stays tested
    directly.
    """
    from core.models import SiteConfig

    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    SiteConfig.objects.filter(pk=config.pk).update(
        diversion_use_type_rule="drop", identifier_host="water.example.org"
    )

    rows = changes_for(config, fields=["identifier_host"])
    assert [(c.name, c.after) for r in rows for c in r.changes] == [
        ("Identifier host", "water.example.org")
    ]


def test_a_well_share_edit_shows_in_the_well_panel_and_its_see_all_page(operator):
    well = WellFactory(name="Linked-history well")
    wip = WellIrrigatedParcelFactory(well=well, fraction="0.2500")
    _patch(
        _client(operator),
        reverse("wells:irrigated_parcel_edit_share", args=[well.pk, wip.pk]),
        value="0.4",
    )

    rows = changes_for(well)
    shares = [r for r in rows if r.record_type == "Well use area share"]
    assert [(r.action, r.who) for r in shares][0] == ("changed", "Dana Reyes")
    assert [(c.name, c.before, c.after) for c in shares[0].changes] == [
        ("Fraction", "0.25", "0.40")
    ]

    html = _client(operator).get(
        reverse("change_history") + f"?type=wells.Well&record={well.pk}"
    ).content.decode()
    assert "to one record and the records linked to it" in html
    assert '<span class="change-value">0.25</span> &rarr; <span class="change-value">0.40</span>' in html


def test_a_diversion_record_edit_shows_in_the_point_of_diversion_panel(operator):
    from tests.factories import DiversionRecordFactory, PointOfDiversionFactory

    pod = PointOfDiversionFactory()
    record = DiversionRecordFactory(point_of_diversion=pod, volume_acre_feet=Decimal("11.4158"))
    type(record).objects.filter(pk=record.pk).update(volume_acre_feet=Decimal("15.0000"))

    rows = [r for r in changes_for(pod) if r.record_type == "Diversion record"]
    assert rows, "the diversion record's history is missing from its point's panel"
    values = [(c.name, c.after) for r in rows for c in r.changes if c.name == "Volume acre feet"]
    assert ("Volume acre feet", "15.00") in values
