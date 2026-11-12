# SPDX-License-Identifier: AGPL-3.0-or-later
"""The El Nido allocation note on a site that loaded the demonstration earlier.

accounting migration 0047 rewrites the stored "Surface allocation reduced for a
dry year." to the words the seed now writes (ruling 141), and touches no other
note.
"""

import datetime as dt
import importlib
from decimal import Decimal

import pytest

from accounting.models import AllocationPlan, ReportingPeriod, WaterType
from geography.models import Boundary, Zone

migration = importlib.import_module("accounting.migrations.0047_el_nido_allocation_note_words")

pytestmark = pytest.mark.django_db


def _plan(name, notes, period):
    from django.contrib.gis.geos import MultiPolygon, Polygon

    shape = MultiPolygon(Polygon.from_bbox((-120.5, 37.2, -120.4, 37.3)), srid=4326)
    boundary, _ = Boundary.objects.get_or_create(name="Note test", defaults={"geometry": shape})
    zone = Zone.objects.create(name=name, boundary=boundary, geometry=shape, zone_type="custom")
    sw, _ = WaterType.objects.get_or_create(code="SW", defaults={"name": "Surface Water"})
    return AllocationPlan.objects.create(
        name=name, zone=zone, water_type=sw, reporting_period=period,
        allocation_acre_feet=Decimal("134.1814"), notes=notes,
    )


def test_the_old_note_is_reworded_and_no_other_note_moves():
    period = ReportingPeriod.objects.create(
        name="WY 2025-2026", start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30)
    )
    old = _plan("El Nido", "Surface allocation reduced for a dry year.", period)
    other = _plan("Other", "Surface allocation reduced for a dry year, by the board.", period)

    assert migration.reword_note(AllocationPlan) == 1

    old.refresh_from_db()
    other.refresh_from_db()
    assert old.notes == (
        "Surface allocation for the demonstration: a tenth of the district's "
        "allocation for WY 2024-2025."
    )
    assert other.notes == "Surface allocation reduced for a dry year, by the board."
