# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 3: the three loss fractions with bands, the local name and the

contract unit on PointOfDiversion.

Convention 4 and convention 11 of the design-implications document
(2026-09-18): the three canal losses default to 0.01 / 0 / 0, and a band is
the district's own stated uncertainty (Turlock publishes seepage at ±35%),
never a model spread. Four doors proven here, each RED against the unfixed
tree (the exact quotes live in 146-03-EVIDENCE.md):

  1. `PointOfDiversionForm` rejects a fraction sum over 1 with a plain
     sentence.
  2. A band saved through `surface:pod_edit` shows "±35%" on the POD page.
  3. The contract unit and miner's inch fields are gone (2026-10-13).
  4. "Known locally as <local_name>" appears on the POD page once set.
"""
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.forms import PointOfDiversionForm
from surface.models import PointOfDiversion
from tests.factories import PointOfDiversionFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"poduser{n}")
    email = factory.Sequence(lambda n: f"poduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. The form rejects a fraction sum over 1
# ---------------------------------------------------------------------------


def test_form_rejects_fraction_sum_over_one():
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(
        {
            "name": pod.name,
            "status": "active",
            "loss_basis": "district_estimate",
            "evaporation_fraction": "0.50",
            "seepage_fraction": "0.40",
            "spill_fraction": "0.20",
        },
        instance=pod,
    )
    assert not form.is_valid()
    assert any(
        "cannot exceed the whole" in msg for msg in form.non_field_errors()
    )


def test_form_rejects_a_fraction_sum_at_exactly_one():
    # 149-02: three shares that take the whole diverted volume leave nothing for
    # the fields, and the canal split refuses such a month, so the form does too.
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(
        {
            "name": pod.name,
            "status": "active",
            "loss_basis": "district_estimate",
            "evaporation_fraction": "0.50",
            "seepage_fraction": "0.30",
            "spill_fraction": "0.20",
        },
        instance=pod,
    )
    assert not form.is_valid()
    assert any("or equal it" in msg for msg in form.non_field_errors())


def test_form_accepts_a_fraction_sum_just_under_one():
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(
        {
            "name": pod.name,
            "status": "active",
            "loss_basis": "district_estimate",
            "evaporation_fraction": "0.50",
            "seepage_fraction": "0.30",
            "spill_fraction": "0.1999",
        },
        instance=pod,
    )
    assert form.is_valid(), form.errors


def test_view_re_renders_the_form_with_the_error_and_saves_nothing(auth_client):
    pod = PointOfDiversionFactory()
    resp = auth_client.post(
        reverse("surface:pod_edit", args=[pod.pk]),
        {
            "name": pod.name,
            "status": "active",
            "loss_basis": "district_estimate",
            "evaporation_fraction": "0.60",
            "seepage_fraction": "0.60",
            "spill_fraction": "0",
        },
    )
    assert resp.status_code == 200
    assert b"cannot exceed the whole" in resp.content
    pod.refresh_from_db()
    assert pod.evaporation_fraction == Decimal("0.0100")  # unchanged default


# ---------------------------------------------------------------------------
# 2. A band saves through the edit door and the POD page shows "±35%"
# ---------------------------------------------------------------------------


def test_band_saves_and_the_page_shows_it(auth_client):
    pod = PointOfDiversionFactory()

    resp = auth_client.post(
        reverse("surface:pod_edit", args=[pod.pk]),
        {
            "name": pod.name,
            "status": "active",
            "loss_basis": "district_estimate",
            "evaporation_fraction": "0.01",
            "seepage_fraction": "0.12",
            "seepage_band_percent": "35",
            "spill_fraction": "0",
        },
    )
    assert resp.status_code == 302

    pod.refresh_from_db()
    assert pod.seepage_band_percent == Decimal("35.00")

    detail = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = detail.content.decode()
    assert "±35%" in body or "±35.00%" in body
    assert "Estimated" in body


# ---------------------------------------------------------------------------
# 3. Contract unit and miner's inch are gone (Brent 2026-10-13 07:22 "yes",
#    150.1-02 screen 7 row 9: nothing in OpenH2O read either field)
# ---------------------------------------------------------------------------


def test_contract_unit_and_miners_inch_are_not_fields():
    names = {f.name for f in PointOfDiversion._meta.get_fields()}
    assert "contract_unit" not in names
    assert "miners_inch_gpm" not in names


def test_a_blank_infrastructure_add_submit_still_creates_the_point(auth_client):
    resp = auth_client.get(reverse("infrastructure:add"))
    assert 'name="miners_inch_gpm"' not in resp.content.decode()
    assert 'name="contract_unit"' not in resp.content.decode()
    resp = auth_client.post(
        reverse("infrastructure:add"),
        {
            "infra_type": "diversion",
            "name": "New Turnout",
            "status": "active",
            "geometry_json": '{"type": "Point", "coordinates": [-119.5, 36.5]}',
        },
    )
    assert resp.status_code == 302
    assert PointOfDiversion.objects.filter(name="New Turnout").exists()


# ---------------------------------------------------------------------------
# 4. "Known locally as" on the POD page
# ---------------------------------------------------------------------------


def test_known_locally_as_appears_when_set(auth_client):
    pod = PointOfDiversionFactory(local_name="Turnout 14")
    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = resp.content.decode()
    assert "Known locally as" in body
    assert "Turnout 14" in body


def test_known_locally_as_is_absent_when_blank(auth_client):
    pod = PointOfDiversionFactory()
    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    assert "Known locally as" not in resp.content.decode()
