# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Parcel owner-name truthfulness (ISS-043b).

The full map's parcel popup reads owner_name + area_acres + status from the
``parcels:geojson`` FeatureCollection. The Kaweah seed used to store a land-use
string in owner_name, so "Owner" showed the crop. These tests lock the
GeoJSON contract (the popup's fields are present) and the backfill command that
replaces land-use values with realistic demo owner names — deterministic and
idempotent, touching only owner_name.
"""
import json
from decimal import Decimal
from io import StringIO

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from core.management.commands.backfill_parcel_owners import KAWEAH_PARCEL_OWNERS
from parcels.models import Parcel
from tests.factories import ParcelFactory, PointOfDiversionFactory


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"owneruser{n}")
    email = factory.Sequence(lambda n: f"owneruser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(UserFactory())
    return c


@pytest.mark.django_db
def test_parcels_geojson_carries_popup_fields(auth_client):
    """The map GeoJSON must expose every field the parcel popup renders."""
    ParcelFactory(
        parcel_number="APN-POPUP-1",
        owner_name="Sierra Vista Ranch",
        area_acres=Decimal("38.42"),
        status="active",
    )
    resp = auth_client.get(reverse("parcels:geojson"))
    assert resp.status_code == 200
    data = json.loads(resp.content)
    props = data["features"][0]["properties"]
    for field in ("parcel_number", "owner_name", "area_acres", "status", "pk"):
        assert field in props, f"parcels_geojson missing '{field}'"
    assert props["owner_name"] == "Sierra Vista Ranch"


@pytest.mark.django_db
def test_pods_geojson_injects_pk(auth_client):
    """The POD full-map popup links to /surface/diversion/<pk>/, so pk must ship."""
    pod = PointOfDiversionFactory(name="Ivanhoe Ditch Head")
    resp = auth_client.get(reverse("surface:pods_geojson"))
    assert resp.status_code == 200
    data = json.loads(resp.content)
    feature = data["features"][0]
    assert feature["properties"]["pk"] == pod.pk


@pytest.mark.django_db
class TestBackfillParcelOwners:
    def _make_kaweah(self, n):
        for i in range(1, n + 1):
            ParcelFactory(
                parcel_number=f"KAW-APN-{i:03d}",
                owner_name="Deciduous Nut Trees",  # land-use masquerading as owner
            )

    def test_replaces_landuse_with_real_owners(self):
        self._make_kaweah(5)
        call_command("backfill_parcel_owners", stdout=StringIO())
        for p in Parcel.objects.filter(parcel_number__startswith="KAW-APN-"):
            assert p.owner_name in KAWEAH_PARCEL_OWNERS
            assert p.owner_name != "Deciduous Nut Trees"

    def test_deterministic_and_idempotent(self):
        self._make_kaweah(5)
        call_command("backfill_parcel_owners", stdout=StringIO())
        first = {
            p.parcel_number: p.owner_name
            for p in Parcel.objects.filter(parcel_number__startswith="KAW-APN-")
        }
        out = StringIO()
        call_command("backfill_parcel_owners", stdout=out)
        # Second run changes nothing.
        assert "Updated 0" in out.getvalue()
        second = {
            p.parcel_number: p.owner_name
            for p in Parcel.objects.filter(parcel_number__startswith="KAW-APN-")
        }
        assert first == second

    def test_leaves_non_kaweah_parcels_alone(self):
        other = ParcelFactory(parcel_number="APN-000999", owner_name="Real Owner")
        self._make_kaweah(2)
        call_command("backfill_parcel_owners", stdout=StringIO())
        other.refresh_from_db()
        assert other.owner_name == "Real Owner"

    def test_dry_run_writes_nothing(self):
        self._make_kaweah(3)
        call_command("backfill_parcel_owners", "--dry-run", stdout=StringIO())
        for p in Parcel.objects.filter(parcel_number__startswith="KAW-APN-"):
            assert p.owner_name == "Deciduous Nut Trees"
