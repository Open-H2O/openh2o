# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-05 checkpoint, Brent's ruling 1 (2026-09-23): the demo's round use areas
say Center Pivot.

`seed_merced_pivot_irrigation` sets `parcels.ParcelIrrigationMethod` to the
seeded "Center Pivot" row on every use area whose outline fills at least 90%
of its own minimum bounding circle -- the same test measured on staging:

    ST_Area(g_3310) / ST_Area(ST_MinimumBoundingCircle(g_3310))

A circle (approximated here by a many-sided `buffer()` polygon) sits near 1.0;
a square sits near 2/pi (~0.637, matching the ~0.656-and-under the main
session measured for every non-pivot use area on staging). Both are built in
SRID 4326 near the Merced demonstration's own coordinates (-119.5, 36.5) so
the ST_Transform to EPSG:3310 the command runs behaves the way it does on
real data, not at some distorting edge of the projection.

`parcels.IrrigationMethod` is seeded by a data migration
(`parcels/0013_irrigation_method` since 150.2-01), so "Center Pivot" already exists in
the test database once migrations have run -- no fixture needed here.
"""
from io import StringIO

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import call_command
from django.test import override_settings

from tests.factories import ParcelFactory

pytestmark = pytest.mark.django_db

#: The shape-4 module list (145-02-EVIDENCE.md's per-shape table): use areas,
#: accounts and wells, no surface water. Matches tests/test_irrigation_method.py.
_SHAPE_4 = (
    "core", "geography", "measurements", "standards", "parcels", "accounting",
    "wells", "datasync", "setup", "infrastructure", "health", "feedback",
)


def _circle(cx=-119.5, cy=36.5, radius_m=500):
    """A 32-sided polygon, a true circle of the given radius IN METERS.

    Built by buffering in EPSG:3310 (a projected, equal-distance CRS) and
    transforming back to 4326 for storage -- not by buffering directly in
    4326. A `Point(...).buffer(0.005)` in degrees is circular in DEGREE
    space, but 1 degree of longitude and 1 degree of latitude are not the
    same distance on the ground (longitude shrinks by cos(latitude)), so
    after `ST_Transform(geometry, 3310)` -- the same transform the command
    itself runs -- that "circle" comes out as an ELLIPSE, at a ratio close to
    cos(36.5 degrees) =~ 0.80: still comfortably a non-pivot by the 0.90
    threshold, and not what this test means to build. Building the circle
    in real meters first and only then projecting it into the stored
    geometry's degrees is what makes it a circle where the command measures
    it -- exactly how a real, GPS-surveyed center pivot's outline works.
    """
    center = Point(cx, cy, srid=4326)
    center.transform(3310)
    circle = center.buffer(radius_m, quadsegs=8)
    circle.srid = 3310
    circle.transform(4326)
    return MultiPolygon(circle)


def _square(cx=-119.5, cy=36.5, half=0.005):
    ring = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


def _run():
    call_command("seed_merced_pivot_irrigation", stdout=StringIO())


def test_a_circular_use_area_gets_center_pivot():
    from parcels.models import ParcelIrrigationMethod

    parcel = ParcelFactory(geometry=_circle())

    _run()

    link = ParcelIrrigationMethod.objects.get(parcel=parcel)
    assert link.method.name == "Center Pivot"


def test_a_square_use_area_does_not():
    from parcels.models import ParcelIrrigationMethod

    parcel = ParcelFactory(geometry=_square())

    _run()

    assert not ParcelIrrigationMethod.objects.filter(parcel=parcel).exists()


def test_an_existing_method_is_never_overwritten():
    from parcels.models import IrrigationMethod, ParcelIrrigationMethod

    parcel = ParcelFactory(geometry=_circle())
    furrow = IrrigationMethod.objects.get(name="Furrow (Conventional)")
    ParcelIrrigationMethod.objects.create(parcel=parcel, method=furrow)

    _run()

    link = ParcelIrrigationMethod.objects.get(parcel=parcel)
    assert link.method.name == "Furrow (Conventional)"


def test_a_rerun_changes_nothing():
    from parcels.models import ParcelIrrigationMethod

    parcel = ParcelFactory(geometry=_circle())

    _run()
    first_link_id = ParcelIrrigationMethod.objects.get(parcel=parcel).pk
    _run()

    assert ParcelIrrigationMethod.objects.filter(parcel=parcel).count() == 1
    assert ParcelIrrigationMethod.objects.get(parcel=parcel).pk == first_link_id


@override_settings(OPENH2O_MODULES=_SHAPE_4)
def test_a_deployment_without_surface_gets_its_pivots_too():
    """150.2-01: the method lives in `parcels` now, so a groundwater-only
    deployment classifies its round fields like any other. Until then this
    test asserted the command skipped (the method lived in `surface`).
    `override_settings` changes what `core.modules.is_enabled` returns, which
    is the boolean the command used to branch on; a truly-uninstalled
    `surface` is the droppability harness's job and
    tests/test_irrigation_method_move.py's."""
    parcel = ParcelFactory(geometry=_circle())

    _run()

    from parcels.models import ParcelIrrigationMethod

    link = ParcelIrrigationMethod.objects.get(parcel=parcel)
    assert link.method.name == "Center Pivot"
