# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-02 Task 2, D3: a water right's places of use, and an editable share on a
point-to-field link.

Proven here, each RED against the unfixed tree (the exact quotes live in
146-02-EVIDENCE.md):

  1. The right's page: search by parcel number, assign, remove -- writing
     WaterRightParcel (the account page's search-parcels / assign fragment
     shape, reused, never its views).
  2. The bulk POD import's PARCEL_NUMBER column, when present and matching a
     Parcel, writes a PointOfDiversionParcel at fraction 1.0.
  3. The inline fraction editor on the POD page's and the well page's linked
     use-area rows (the wells:edit_field GET/PATCH pattern): 0.5 accepted, 0
     and 1.5 rejected.
  4. The places-of-use panel is absent when `parcels` is off. `surface`
     requires `parcels` (core/modules.py), so a real deployment can never
     reach "surface on, parcels off" through OPENH2O_MODULES -- setting it
     that way raises ImproperlyConfigured before a page could render at all.
     What IS reachable, and what this proves, is the template guard itself:
     rendered directly with an `enabled_modules` list that omits "parcels",
     the panel's `{% if 'parcels' in enabled_modules %}` renders nothing.
"""
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django.utils.http import urlencode
import factory
import pytest
from django.contrib.auth.hashers import make_password

from infrastructure import importer
from surface.models import PointOfDiversion, PointOfDiversionParcel, WaterRightParcel
from tests.factories import (
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    WaterRightFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"pouuser{n}")
    email = factory.Sequence(lambda n: f"pouuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


def _patch(client, url, value):
    body = urlencode({"value": value})
    return client.patch(url, data=body, content_type="application/x-www-form-urlencoded")


# ---------------------------------------------------------------------------
# 1. Places of use: assign, remove, search
# ---------------------------------------------------------------------------


def test_assign_place_of_use_creates_water_right_parcel(auth_client):
    right = WaterRightFactory(right_id="A001885")
    parcel = ParcelFactory(parcel_number="APN-100001")

    resp = auth_client.post(
        reverse("surface:water_right_assign_parcel", args=[right.pk]),
        {"parcel_id": parcel.pk},
    )

    assert resp.status_code == 200
    assert WaterRightParcel.objects.filter(water_right=right, parcel=parcel).exists()
    assert b"APN-100001" in resp.content


def test_remove_place_of_use_deletes_the_row(auth_client):
    right = WaterRightFactory(right_id="A005724")
    parcel = ParcelFactory(parcel_number="APN-100002")
    wrp = WaterRightParcel.objects.create(water_right=right, parcel=parcel)

    resp = auth_client.post(
        reverse("surface:water_right_remove_parcel", args=[right.pk, wrp.pk])
    )

    assert resp.status_code == 200
    assert not WaterRightParcel.objects.filter(pk=wrp.pk).exists()
    assert b"No places of use assigned to this right." in resp.content


def test_search_places_of_use_excludes_already_assigned(auth_client):
    right = WaterRightFactory(right_id="A006111")
    already = ParcelFactory(parcel_number="APN-200001")
    ParcelFactory(parcel_number="APN-200002")
    WaterRightParcel.objects.create(water_right=right, parcel=already)

    resp = auth_client.get(
        reverse("surface:water_right_search_parcels", args=[right.pk]),
        {"q": "APN-2"},
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "APN-200002" in body
    assert "APN-200001" not in body


# ---------------------------------------------------------------------------
# 2. Bulk POD import links PARCEL_NUMBER at fraction 1.0
# ---------------------------------------------------------------------------


def test_bulk_import_parcel_number_links_use_area_at_full_share():
    parcel = ParcelFactory(parcel_number="APN-300001")
    rows = [{
        "NAME": "POD Linked", "LAT": "37.35", "LON": "-120.90",
        "PARCEL_NUMBER": "APN-300001",
    }]
    mapping = {
        "name": "NAME", "latitude": "LAT", "longitude": "LON",
        "parcel_number": "PARCEL_NUMBER",
    }
    results = importer.validate_rows(rows, mapping, "diversion", set())
    assert results[0]["errors"] == []
    assert any("APN-300001" in w for w in results[0]["warnings"])

    created = importer.commit_rows(results, "diversion")
    assert created == 1
    pod = PointOfDiversion.objects.get(name="POD Linked")
    link = PointOfDiversionParcel.objects.get(point_of_diversion=pod, parcel=parcel)
    assert link.fraction == 1


def test_bulk_import_unmatched_parcel_number_is_not_an_error():
    rows = [{
        "NAME": "POD Unmatched", "LAT": "37.35", "LON": "-120.90",
        "PARCEL_NUMBER": "APN-NOTFOUND",
    }]
    mapping = {
        "name": "NAME", "latitude": "LAT", "longitude": "LON",
        "parcel_number": "PARCEL_NUMBER",
    }
    results = importer.validate_rows(rows, mapping, "diversion", set())
    assert results[0]["errors"] == []
    created = importer.commit_rows(results, "diversion")
    assert created == 1
    pod = PointOfDiversion.objects.get(name="POD Unmatched")
    assert not PointOfDiversionParcel.objects.filter(point_of_diversion=pod).exists()


# ---------------------------------------------------------------------------
# 3. The share editors: POD and well
# ---------------------------------------------------------------------------


def test_pod_share_editor_accepts_half(auth_client):
    pod = PointOfDiversionFactory()
    pp = PointOfDiversionParcelFactory(point_of_diversion=pod, fraction="1.0000")

    resp = _patch(
        auth_client, reverse("surface:pod_parcel_edit_share", args=[pod.pk, pp.pk]), "0.5"
    )

    assert resp.status_code == 200
    pp.refresh_from_db()
    assert pp.fraction == Decimal("0.5000")
    assert b"share 0.5000" in resp.content


def test_pod_share_editor_rejects_zero(auth_client):
    pod = PointOfDiversionFactory()
    pp = PointOfDiversionParcelFactory(point_of_diversion=pod, fraction="1.0000")

    resp = _patch(
        auth_client, reverse("surface:pod_parcel_edit_share", args=[pod.pk, pp.pk]), "0"
    )

    assert resp.status_code == 200
    pp.refresh_from_db()
    assert pp.fraction == 1  # unchanged
    assert b"greater than 0" in resp.content


def test_pod_share_editor_rejects_over_one(auth_client):
    pod = PointOfDiversionFactory()
    pp = PointOfDiversionParcelFactory(point_of_diversion=pod, fraction="1.0000")

    resp = _patch(
        auth_client, reverse("surface:pod_parcel_edit_share", args=[pod.pk, pp.pk]), "1.5"
    )

    assert resp.status_code == 200
    pp.refresh_from_db()
    assert pp.fraction == 1  # unchanged
    assert b"no more than 1" in resp.content


def test_well_share_editor_accepts_half_and_rejects_out_of_range(auth_client):
    well = WellFactory()
    wip = WellIrrigatedParcelFactory(well=well, fraction="1.0000")
    url = reverse("wells:irrigated_parcel_edit_share", args=[well.pk, wip.pk])

    ok = _patch(auth_client, url, "0.5")
    assert ok.status_code == 200
    wip.refresh_from_db()
    assert wip.fraction == Decimal("0.5000")
    assert b"share 0.5000" in ok.content

    too_big = _patch(auth_client, url, "1.5")
    assert too_big.status_code == 200
    wip.refresh_from_db()
    assert wip.fraction == Decimal("0.5000")  # unchanged from the accepted save above
    assert b"no more than 1" in too_big.content

    zero = _patch(auth_client, url, "0")
    assert zero.status_code == 200
    wip.refresh_from_db()
    assert wip.fraction == Decimal("0.5000")  # unchanged
    assert b"greater than 0" in zero.content


# ---------------------------------------------------------------------------
# 4. The places-of-use panel's `parcels` guard
# ---------------------------------------------------------------------------


def test_places_of_use_panel_renders_when_parcels_is_enabled():
    right = WaterRightFactory(right_id="A007012")
    html = render_to_string("surface/partials/_places_of_use.html", {
        "water_right": right,
        "places_of_use": [],
        "enabled_modules": ["surface", "parcels", "accounting"],
    })
    assert "Places of use" in html
    assert reverse("surface:water_right_search_parcels", args=[right.pk]) in html


def test_places_of_use_panel_is_absent_when_parcels_is_off():
    right = WaterRightFactory(right_id="A007013")
    html = render_to_string("surface/partials/_places_of_use.html", {
        "water_right": right,
        "places_of_use": [],
        "enabled_modules": ["surface", "accounting"],
    })
    assert "Places of use" not in html
    assert html.strip() == ""
