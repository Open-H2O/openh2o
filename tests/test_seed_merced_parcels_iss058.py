# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-058: a full Merced re-seed must NOT re-fetch OpenET for unchanged parcels.

The bug: seed_merced_parcels_from_selection used to delete every MER-APN- parcel
up front, rotating their PKs. OpenETCache.parcel is a CASCADE FK, so the flush
wiped the cache and the next sync_openet_parcels re-fetched ALL parcels from
Google Earth Engine — paid compute even for fields whose footprint never changed.

The fix makes the seed prune-only: update_or_create keeps an unchanged parcel's
PK (so its cached ET + precip survive), a moved parcel's stale cache is dropped
(the GEE adapter matches the cache by parcel_id, never by geometry), and parcels
dropped from the selection are deleted at the end.

These tests use all-groundwater parcels so no PointOfDiversion / WaterRight setup
is needed — the only prerequisite is one Merced GSA zone.
"""
import json
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from core.management.commands import seed_merced_parcels_from_selection as seed_cmd
from datasync.models import OpenETCache
from geography.models import Zone
from parcels.models import Parcel

CMD = "seed_merced_parcels_from_selection"


def _feature(offset, uid):
    """A small groundwater field square, shifted east by `offset` degrees."""
    x = -120.40 + offset
    y = 37.30
    ring = [[x, y], [x + 0.01, y], [x + 0.01, y + 0.01], [x, y + 0.01], [x, y]]
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "served_by": "",            # blank → no POD needed (groundwater)
            "water_source": "groundwater",
            "well_group": "",
            "MAIN_CROP": "Almonds",
            "crop_class": "irrigated",
            "COUNTY": "Merced",
            "UniqueID": uid,
            "ACRES": 80,
        },
    }


@pytest.fixture
def fixture_writer(tmp_path, monkeypatch):
    """Point the command at a temp selection fixture; disable the river fixture."""
    path = tmp_path / "selected_parcels.geojson"
    monkeypatch.setattr(seed_cmd, "FIXTURE", str(path))
    monkeypatch.setattr(seed_cmd, "RIVER_FIXTURE", str(tmp_path / "nope.geojson"))

    def write(features):
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))

    return write


@pytest.fixture
def gsa_zone(db):
    """The one prerequisite: a Merced GSA management area for the parcels to fall in."""
    from tests.factories import ZoneFactory

    return ZoneFactory(
        name="Test Merced GSA",
        zone_type="management_area",
        basin_code="5-022.04",
    )


def _seed():
    call_command(CMD, stdout=StringIO())


def _cache_for(parcel, variable="ET"):
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=parcel.geometry,
        start_date=date(2023, 10, 1),
        end_date=date(2024, 9, 30),
        variable=variable,
        et_data=[{"date": "2024-01-01", "et": 1.23}],
    )


@pytest.mark.django_db
def test_unchanged_reseed_preserves_pk_and_cache(fixture_writer, gsa_zone):
    """A same-footprint re-seed keeps each parcel's PK and its cached ET + precip."""
    fixture_writer([_feature(0.00, "F1"), _feature(0.05, "F2")])
    _seed()

    p1 = Parcel.objects.get(parcel_number="MER-APN-001")
    original_pk = p1.pk
    et_cache = _cache_for(p1, "ET")
    precip_cache = _cache_for(p1, "precip")

    _seed()  # re-seed, identical fixture

    p1_after = Parcel.objects.get(parcel_number="MER-APN-001")
    assert p1_after.pk == original_pk, "PK rotated → cache would have cascaded away"
    assert OpenETCache.objects.filter(pk=et_cache.pk).exists()
    assert OpenETCache.objects.filter(pk=precip_cache.pk).exists()


@pytest.mark.django_db
def test_geometry_change_invalidates_cache(fixture_writer, gsa_zone):
    """A parcel that kept its number but MOVED loses its now-stale cache."""
    fixture_writer([_feature(0.00, "F1"), _feature(0.05, "F2")])
    _seed()

    p1 = Parcel.objects.get(parcel_number="MER-APN-001")
    p2 = Parcel.objects.get(parcel_number="MER-APN-002")
    stale = _cache_for(p1, "ET")
    kept = _cache_for(p2, "ET")

    # Re-seed with parcel 1 moved (parcel 2 unchanged).
    fixture_writer([_feature(0.20, "F1"), _feature(0.05, "F2")])
    _seed()

    assert not OpenETCache.objects.filter(pk=stale.pk).exists(), "moved parcel kept stale ET"
    assert OpenETCache.objects.filter(pk=kept.pk).exists(), "unchanged parcel lost its ET"


@pytest.mark.django_db
def test_dropped_parcel_is_pruned(fixture_writer, gsa_zone):
    """A field removed from the selection is deleted on the next re-seed."""
    fixture_writer([_feature(0.00, "F1"), _feature(0.05, "F2")])
    _seed()
    assert Parcel.objects.filter(parcel_number="MER-APN-002").exists()

    fixture_writer([_feature(0.00, "F1")])  # F2 dropped
    _seed()

    assert Parcel.objects.filter(parcel_number="MER-APN-001").exists()
    assert not Parcel.objects.filter(parcel_number="MER-APN-002").exists()
