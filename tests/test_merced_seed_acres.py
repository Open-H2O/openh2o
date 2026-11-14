# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-410: each demonstration use area's recorded acres equal its outline's.

seed_merced_operations places MER-APN-001 to 018 as placeholder squares, and the
post-save signal fills `area_acres` from those squares. seed_merced_parcels_from_selection
then gives each its real outline, and the signal never refills an acreage already on
file (parcels/signals.py), so the square's acres stayed: MER-APN-015 recorded 149.73
acres on a 60.21-acre outline. Every figure split by acreage (a headgate's water
shared among its fields) used the square's acres.

The rule for a real site is unchanged: an acreage on file is the district's record
and a later outline edit does not overwrite it. Only the demonstration seed, which
replaces its own placeholder, sets the acres from the outline it lays down.
"""
import json
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.db import connection

from core.management.commands import seed_merced_parcels_from_selection as seed_cmd
from parcels.models import Parcel

CMD = "seed_merced_parcels_from_selection"
SQ_M_PER_ACRE = Decimal("4046.8564224")


def _ring(x, y, size):
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]


def _feature(ring, uid):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "served_by": "",
            "water_source": "groundwater",
            "well_group": "",
            "MAIN_CROP": "Almonds",
            "crop_class": "irrigated",
            "COUNTY": "Merced",
            "UniqueID": uid,
        },
    }


def _outline_acres(parcel_number):
    """The outline's acres in EPSG 3310 (California Albers, equal area), to 0.01."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_Area(ST_Transform(geometry, 3310)) FROM parcels_parcel"
            " WHERE parcel_number = %s",
            [parcel_number],
        )
        sq_m = Decimal(str(cursor.fetchone()[0]))
    return (sq_m / SQ_M_PER_ACRE).quantize(Decimal("0.01"))


@pytest.fixture
def fixture_writer(tmp_path, monkeypatch):
    path = tmp_path / "selected_parcels.geojson"
    monkeypatch.setattr(seed_cmd, "FIXTURE", str(path))
    monkeypatch.setattr(seed_cmd, "RIVER_FIXTURE", str(tmp_path / "nope.geojson"))

    def write(features):
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))

    return write


@pytest.fixture
def gsa_zone(db):
    from tests.factories import ZoneFactory

    return ZoneFactory(
        name="Test Merced GSA", zone_type="management_area", basin_code="5-022.04",
    )


def _placeholder_square(parcel_number, x, y, size):
    """What seed_merced_operations leaves: a square whose acres the signal filled."""
    parcel = Parcel.objects.create(
        parcel_number=parcel_number,
        owner_name="Placeholder",
        geometry=MultiPolygon(Polygon(_ring(x, y, size)), srid=4326),
        status="active",
    )
    parcel.refresh_from_db()
    assert parcel.area_acres is not None
    return parcel


@pytest.mark.django_db
def test_seed_sets_acres_from_the_outline_it_lays_over_a_placeholder(fixture_writer, gsa_zone):
    """The square was about 4 times the outline; the recorded acres follow the outline."""
    square = _placeholder_square("MER-APN-001", -120.40, 37.30, 0.02)
    fixture_writer([_feature(_ring(-120.40, 37.30, 0.01), "F1")])

    call_command(CMD, stdout=StringIO())

    parcel = Parcel.objects.get(parcel_number="MER-APN-001")
    assert parcel.area_acres != square.area_acres
    assert parcel.area_acres == _outline_acres("MER-APN-001")


@pytest.mark.django_db
def test_seed_sets_acres_when_the_outline_is_larger_than_the_placeholder(fixture_writer, gsa_zone):
    """Four of the eighteen recorded fewer acres than their outline (MER-APN-012)."""
    _placeholder_square("MER-APN-001", -120.40, 37.30, 0.005)
    fixture_writer([_feature(_ring(-120.40, 37.30, 0.01), "F1")])

    call_command(CMD, stdout=StringIO())

    parcel = Parcel.objects.get(parcel_number="MER-APN-001")
    assert parcel.area_acres == _outline_acres("MER-APN-001")


@pytest.mark.django_db
def test_a_reseed_with_the_same_outline_keeps_the_acres(fixture_writer, gsa_zone):
    fixture_writer([_feature(_ring(-120.40, 37.30, 0.01), "F1")])
    call_command(CMD, stdout=StringIO())
    first = Parcel.objects.get(parcel_number="MER-APN-001").area_acres

    call_command(CMD, stdout=StringIO())

    assert Parcel.objects.get(parcel_number="MER-APN-001").area_acres == first


@pytest.mark.django_db
def test_an_ordinary_outline_edit_keeps_the_acreage_on_file(db):
    """A real site's typed acreage is its record; saving a new outline leaves it alone."""
    parcel = Parcel.objects.create(
        parcel_number="APN-REAL-1",
        owner_name="District",
        area_acres=Decimal("42.00"),
        geometry=MultiPolygon(Polygon(_ring(-120.40, 37.30, 0.01)), srid=4326),
        status="active",
    )
    parcel.geometry = MultiPolygon(Polygon(_ring(-120.40, 37.30, 0.02)), srid=4326)
    parcel.save()
    parcel.refresh_from_db()
    assert parcel.area_acres == Decimal("42.00")
