# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guard for ISS-055: rollover_allocations must scope its target-year
delete to its OWN origin (allocation_carryover), never the basin recharge pool.

The rollover writes carry-over rows for the NEXT water year and clears that
year's rows first so a re-run is idempotent. Before the fix the delete filtered
on water_year alone, so a basin_recharge_pool deposit that happened to live in
the target year was wiped along with the rollover's own rows. Phase 62's re-seed
deposits managed recharge into the pool, then rolls the year forward — exactly
the collision this test pins down.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounting.models import AllocationCarryover
from accounting.services import BASIN_RECHARGE_POOL, deposit_to_basin_pool
from tests.factories import (
    AllocationPlanFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


def test_rollover_preserves_basin_pool_row_in_target_year():
    """A basin_recharge_pool deposit in the rollover's target year survives the
    rollover. --water-year 2024 rolls into 2025; the 2025 pool row must remain."""
    gw = WaterTypeFactory(name="Groundwater", code="GW")
    period = ReportingPeriodFactory(
        name="WY 2023-2024",
        start_date=date(2023, 10, 1),
        end_date=date(2024, 9, 30),
        is_finalized=True,
    )
    zone = ZoneFactory()
    AllocationPlanFactory(
        zone=zone,
        water_type=gw,
        reporting_period=period,
        allocation_acre_feet=Decimal("100"),
    )

    # Managed recharge already deposited into the pool for the TARGET year (2025).
    deposit_to_basin_pool(zone, gw, 2025, Decimal("975.0000"))
    assert AllocationCarryover.objects.filter(
        zone=zone, water_type=gw, water_year=2025, origin=BASIN_RECHARGE_POOL
    ).exists()

    call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())

    pool = AllocationCarryover.objects.get(
        zone=zone, water_type=gw, water_year=2025, origin=BASIN_RECHARGE_POOL
    )
    assert pool.amount_af == Decimal("975.0000")  # untouched by the rollover

    # The rollover still wrote its OWN carry-over row alongside the pool row.
    assert AllocationCarryover.objects.filter(
        zone=zone, water_type=gw, water_year=2025, origin="allocation_carryover"
    ).exists()
