# SPDX-License-Identifier: AGPL-3.0-or-later
"""`seed_merced_basins_from_selection` links the El Nido intake to its own right.

136-02 (ISS-152, option a). The intake POD is owned by this command, which
`update_or_create`s it on every build, so the link has to be made HERE or the
next rebuild erases it. Nothing else in the suite runs this command against the
committed QGIS selection, so this file is the only place the right's creation
is exercised. Observed RED before the seed change (the intake carried
`water_right=None`), GREEN after.

The fixture is the smallest physical slice the command needs: the Merced
Subbasin boundary, one flowline named "El Nido Canal" inside it, the three GSA
zones, the Merced River diversion the Flood-MAR half links to, and the right
type `seed_data` owns.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError

from geography.models import Boundary, Flowline, Zone
from surface.models import (
    PointOfDiversion,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightParcel,
    WaterRightType,
)

INTAKE = "MER-BPOD-001 El Nido Canal Recharge Intake"
RIGHT_ID = "MER-WR-011-DEMO"


def _box(x0, y0, x1, y1):
    return MultiPolygon(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]))


def _slice(with_right_type=True):
    # Covers both committed selections: the El Nido basins near (-120.39, 37.19)
    # and the river parcels near (-120.75, 37.39).
    boundary = Boundary.objects.create(
        name="Merced Subbasin", geometry=_box(-120.9, 37.0, -120.2, 37.6))
    Flowline.objects.create(
        name="El Nido Canal", boundary=boundary, feature_type="Canal",
        geometry=MultiLineString(LineString((-120.41, 37.17), (-120.38, 37.20)), srid=4326),
    )
    for i, name in enumerate([
        "Halvern Valley GSA", "Halvern Irrigation-Urban GSA",
        "Verdano Island Water District GSA",
    ]):
        Zone.objects.create(
            name=name, boundary=boundary, zone_type="management_area",
            basin_code="5-022.04",
            geometry=_box(-120.9 + i * 0.2, 37.0, -120.7 + i * 0.2, 37.6),
        )
    PointOfDiversion.objects.create(
        name="MER-POD-009-DEMO Bottomlands Riparian Take",
        location=Point(-120.75, 37.39), status="active",
    )
    if with_right_type:
        WaterRightType.objects.get_or_create(
            code="POST14", defaults={"name": "Post-1914 Appropriative"})


@pytest.mark.django_db
def test_the_intake_diverts_under_its_own_new_right():
    _slice()
    call_command("seed_merced_basins_from_selection")

    intake = PointOfDiversion.objects.get(name=INTAKE)
    right = intake.water_right
    assert right is not None, "the El Nido intake still carries no water right"
    assert right.right_id == RIGHT_ID
    assert right.holder_name == "Halvern Irrigation District"
    assert right.right_type.name == "Post-1914 Appropriative"
    assert right.status == "active"
    # Read FROM the flowline the intake is snapped to, never typed.
    assert right.source_name == "El Nido Canal"
    assert right.source_name == intake.stream_name
    assert right.face_value_acre_feet == Decimal("3500.0000")
    assert right.priority_date is not None and right.priority_date >= date(2015, 1, 1), (
        "SGMA-era: the demonstration's recharge right post-dates 2014")


@pytest.mark.django_db
def test_the_right_serves_no_parcel():
    """Trap 2 (136-02): a served parcel would put the storm into a field's ledger."""
    _slice()
    call_command("seed_merced_basins_from_selection")
    right = WaterRight.objects.get(right_id=RIGHT_ID)
    intake = PointOfDiversion.objects.get(name=INTAKE)
    assert WaterRightParcel.objects.filter(water_right=right).count() == 0
    assert PointOfDiversionParcel.objects.filter(point_of_diversion=intake).count() == 0


@pytest.mark.django_db
def test_a_re_run_leaves_exactly_one_right_and_keeps_the_link():
    _slice()
    call_command("seed_merced_basins_from_selection")
    call_command("seed_merced_basins_from_selection")
    assert WaterRight.objects.filter(right_id=RIGHT_ID).count() == 1
    assert WaterRight.objects.filter(right_id__startswith="MER-WR-011").count() == 1
    assert PointOfDiversion.objects.get(name=INTAKE).water_right.right_id == RIGHT_ID


@pytest.mark.django_db
def test_a_missing_right_type_fails_loudly_naming_seed_data():
    """`surface.WaterRightType` is pinned at 6 and owned by seed_data; this
    command must never create one to get itself unstuck."""
    _slice(with_right_type=False)
    with pytest.raises(CommandError, match="seed_data"):
        call_command("seed_merced_basins_from_selection")
    assert WaterRightType.objects.count() == 0
