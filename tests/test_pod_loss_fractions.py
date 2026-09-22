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
  3. `miners_inch_gpm` defaults to 11.22 on a POD created with no value.
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


def test_form_accepts_a_fraction_sum_at_exactly_one():
    pod = PointOfDiversionFactory()
    form = PointOfDiversionForm(
        {
            "name": pod.name,
            "status": "active",
            "loss_basis": "district_estimate",
            "evaporation_fraction": "0.50",
            "seepage_fraction": "0.30",
            "spill_fraction": "0.20",
            "miners_inch_gpm": "11.22",
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
            "miners_inch_gpm": "11.22",
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
            "miners_inch_gpm": "11.22",
        },
    )
    assert resp.status_code == 302

    pod.refresh_from_db()
    assert pod.seepage_band_percent == Decimal("35.00")

    detail = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = detail.content.decode()
    assert "±35%" in body or "±35.00%" in body
    assert "District estimate" in body


# ---------------------------------------------------------------------------
# 3. miners_inch_gpm defaults to 11.22
# ---------------------------------------------------------------------------


def test_miners_inch_gpm_defaults_to_11_22():
    pod = PointOfDiversionFactory()
    assert pod.miners_inch_gpm == Decimal("11.22")


def test_miners_inch_gpm_default_survives_a_blank_infrastructure_add_submit(auth_client):
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
    pod = PointOfDiversion.objects.get(name="New Turnout")
    assert pod.miners_inch_gpm == Decimal("11.22")


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
