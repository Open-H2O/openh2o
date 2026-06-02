# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry-boundary numeric validation across the three raw-input paths (ISS-033).

Covers the parcel inline editor, the well inline editor, and the multi-type
infrastructure "Add" form. Each must reject non-numeric and out-of-range input
with a friendly error and HTTP 200 — never a 500 — and must never persist an
invalid row. The infra path must additionally preserve the drawn geometry on a
failed submit.
"""
import json

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse
from django.utils.http import urlencode

from parcels.models import Parcel
from surface.models import PointOfDiversion
from tests.factories import ParcelFactory, WellFactory
from wells.models import Well

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"valuser{n}")
    email = factory.Sequence(lambda n: f"valuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


def _patch_field(client, url, field, value):
    """PATCH the inline editor the way the HTMX form does (urlencoded body)."""
    body = urlencode({"field": field, "value": value})
    return client.patch(url, data=body, content_type="application/x-www-form-urlencoded")


# ---------------------------------------------------------------------------
# Parcel inline editor
# ---------------------------------------------------------------------------


class TestParcelInlineValidation:
    def test_non_numeric_area_is_rejected_without_500_or_save(self, auth_client):
        parcel = ParcelFactory(area_acres="80.00")
        url = reverse("parcels:edit_field", args=[parcel.pk])

        resp = _patch_field(auth_client, url, "area_acres", "not-a-number")

        assert resp.status_code == 200
        assert b"must be a number" in resp.content
        parcel.refresh_from_db()
        assert str(parcel.area_acres) == "80.00"  # unchanged

    def test_negative_area_is_rejected(self, auth_client):
        parcel = ParcelFactory(area_acres="80.00")
        url = reverse("parcels:edit_field", args=[parcel.pk])

        resp = _patch_field(auth_client, url, "area_acres", "-5")

        assert resp.status_code == 200
        assert b"greater than 0" in resp.content
        parcel.refresh_from_db()
        assert str(parcel.area_acres) == "80.00"

    def test_zero_area_is_rejected(self, auth_client):
        parcel = ParcelFactory(area_acres="80.00")
        url = reverse("parcels:edit_field", args=[parcel.pk])

        resp = _patch_field(auth_client, url, "area_acres", "0")

        assert resp.status_code == 200
        assert b"greater than 0" in resp.content
        parcel.refresh_from_db()
        assert str(parcel.area_acres) == "80.00"

    def test_valid_area_is_saved(self, auth_client):
        parcel = ParcelFactory(area_acres="80.00")
        url = reverse("parcels:edit_field", args=[parcel.pk])

        resp = _patch_field(auth_client, url, "area_acres", "123.45")

        assert resp.status_code == 200
        parcel.refresh_from_db()
        assert str(parcel.area_acres) == "123.45"

    def test_blank_area_is_accepted_not_rejected(self, auth_client):
        # Blank is a valid "clear" for a nullable field, so coercion must let it
        # through without a 500 or a validation error. (A parcel with geometry
        # then auto-recomputes area_acres from the polygon via the post_save
        # signal in parcels/signals.py — existing behavior, not the bound check.)
        parcel = ParcelFactory(area_acres="80.00")
        url = reverse("parcels:edit_field", args=[parcel.pk])

        resp = _patch_field(auth_client, url, "area_acres", "")

        assert resp.status_code == 200
        assert b"must be" not in resp.content  # no validation error rendered


# ---------------------------------------------------------------------------
# Well inline editor
# ---------------------------------------------------------------------------


class TestWellInlineValidation:
    def test_non_numeric_capacity_is_rejected_without_500_or_save(self, auth_client):
        well = WellFactory(capacity_gpm="500.00")
        url = reverse("wells:edit_field", args=[well.pk])

        resp = _patch_field(auth_client, url, "capacity_gpm", "lots")

        assert resp.status_code == 200
        assert b"must be a number" in resp.content
        well.refresh_from_db()
        assert str(well.capacity_gpm) == "500.00"

    def test_negative_depth_is_rejected(self, auth_client):
        well = WellFactory(depth_ft="350.00")
        url = reverse("wells:edit_field", args=[well.pk])

        resp = _patch_field(auth_client, url, "depth_ft", "-10")

        assert resp.status_code == 200
        assert b"cannot be negative" in resp.content
        well.refresh_from_db()
        assert str(well.depth_ft) == "350.00"

    def test_year_below_lower_bound_is_rejected(self, auth_client):
        well = WellFactory(year_pumping_began=1990)
        url = reverse("wells:edit_field", args=[well.pk])

        resp = _patch_field(auth_client, url, "year_pumping_began", "1700")

        assert resp.status_code == 200
        assert b"at least 1850" in resp.content
        well.refresh_from_db()
        assert well.year_pumping_began == 1990

    def test_year_in_the_future_is_rejected(self, auth_client):
        well = WellFactory(year_pumping_began=1990)
        url = reverse("wells:edit_field", args=[well.pk])

        resp = _patch_field(auth_client, url, "year_pumping_began", "3000")

        assert resp.status_code == 200
        assert b"at most" in resp.content
        well.refresh_from_db()
        assert well.year_pumping_began == 1990

    def test_non_integer_year_is_rejected(self, auth_client):
        well = WellFactory(year_pumping_began=1990)
        url = reverse("wells:edit_field", args=[well.pk])

        resp = _patch_field(auth_client, url, "year_pumping_began", "19.5")

        assert resp.status_code == 200
        assert b"whole number" in resp.content
        well.refresh_from_db()
        assert well.year_pumping_began == 1990

    def test_valid_capacity_is_saved(self, auth_client):
        well = WellFactory(capacity_gpm="500.00")
        url = reverse("wells:edit_field", args=[well.pk])

        resp = _patch_field(auth_client, url, "capacity_gpm", "750.25")

        assert resp.status_code == 200
        well.refresh_from_db()
        assert str(well.capacity_gpm) == "750.25"


# ---------------------------------------------------------------------------
# Infrastructure "Add" form (also preserves drawn geometry on failure)
# ---------------------------------------------------------------------------


class TestInfrastructureAddValidation:
    POINT = {"type": "Point", "coordinates": [-119.5, 36.5]}

    def _well_post(self, **overrides):
        data = {
            "infra_type": "well",
            "name": "Test Well",
            "status": "active",
            "geometry_json": json.dumps(self.POINT),
        }
        data.update(overrides)
        return data

    def test_non_numeric_depth_does_not_500_or_create(self, auth_client):
        url = reverse("infrastructure:add")
        resp = auth_client.post(url, self._well_post(depth_ft="deep"))

        assert resp.status_code == 200  # re-rendered form, not a 500
        assert b"must be a number" in resp.content
        assert Well.objects.count() == 0

    def test_negative_capacity_does_not_create(self, auth_client):
        url = reverse("infrastructure:add")
        resp = auth_client.post(url, self._well_post(capacity_gpm="-100"))

        assert resp.status_code == 200
        assert b"cannot be negative" in resp.content
        assert Well.objects.count() == 0

    def test_failed_submit_preserves_drawn_geometry(self, auth_client):
        url = reverse("infrastructure:add")
        resp = auth_client.post(url, self._well_post(depth_ft="oops"))

        assert resp.status_code == 200
        body = resp.content.decode()
        # The hidden geometry_json input must echo back the drawn coordinates so a
        # corrected re-submit keeps the geometry instead of forcing a redraw.
        assert "-119.5" in body
        assert "36.5" in body
        assert Well.objects.count() == 0

    def test_diversion_negative_rate_does_not_create(self, auth_client):
        url = reverse("infrastructure:add")
        resp = auth_client.post(url, {
            "infra_type": "diversion",
            "name": "Test POD",
            "status": "active",
            "geometry_json": json.dumps(self.POINT),
            "max_rate_cfs": "-2.5",
        })

        assert resp.status_code == 200
        assert b"cannot be negative" in resp.content
        assert PointOfDiversion.objects.count() == 0

    def test_valid_well_is_created(self, auth_client):
        url = reverse("infrastructure:add")
        resp = auth_client.post(url, self._well_post(depth_ft="350", capacity_gpm="500"))

        # Successful create redirects to the new well's detail page.
        assert resp.status_code == 302
        assert Well.objects.count() == 1
        well = Well.objects.get()
        assert str(well.depth_ft) == "350.00"
