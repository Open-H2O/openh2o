# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the GSA basin recharge pool (Phase 52.6-02, ISS-053).

``deposit_to_basin_pool`` accumulates recharge that infiltrates the shared
aquifer but belongs to no single parcel into one ``AllocationCarryover`` row per
``(zone, water_type, water_year, origin)``. These prove the two invariants the
rest of the plan leans on:

  - Additive + single-row — repeated deposits to the same key SUM into ONE row
    (so the engine's per-parcel loop can deposit many times without duplicating).
  - Coexistence — a basin-pool row sits alongside a normal allocation-carryover
    row for the same zone/water-type/year, because ``origin`` is in the unique
    key (a stray IntegrityError here would mean the migration's widened
    unique_together didn't take).

Runs in the web container (needs the DB).
"""
from decimal import Decimal

import pytest

from accounting.models import AllocationCarryover
from accounting.services import (
    BASIN_RECHARGE_POOL,
    INCIDENTAL_RECHARGE_POOL,
    deposit_to_basin_pool,
)
from tests.factories import WaterTypeFactory, ZoneFactory

Q = Decimal("0.0001")


@pytest.mark.django_db
def test_two_deposits_to_same_key_sum_into_one_pool_row():
    zone = ZoneFactory(zone_type="management_area")
    gw = WaterTypeFactory(code="GW")

    deposit_to_basin_pool(zone, gw, 2025, Decimal("600"))
    deposit_to_basin_pool(zone, gw, 2025, Decimal("375"))

    rows = AllocationCarryover.objects.filter(
        zone=zone, water_type=gw, water_year=2025, origin=BASIN_RECHARGE_POOL
    )
    assert rows.count() == 1  # additive, not a second row
    assert rows.first().amount_af.quantize(Q) == Decimal("975.0000")


@pytest.mark.django_db
def test_deposit_returns_the_pool_row():
    zone = ZoneFactory(zone_type="management_area")
    gw = WaterTypeFactory(code="GW")

    row = deposit_to_basin_pool(zone, gw, 2025, Decimal("100"))
    assert row.origin == BASIN_RECHARGE_POOL
    assert row.amount_af.quantize(Q) == Decimal("100.0000")


@pytest.mark.django_db
def test_negative_delta_subtracts_so_a_rerun_can_stay_idempotent():
    """The engine deposits a signed delta (new − prior) per parcel-month; a delta
    that reverses an earlier deposit must reduce the pool, not error."""
    zone = ZoneFactory(zone_type="management_area")
    gw = WaterTypeFactory(code="GW")

    deposit_to_basin_pool(zone, gw, 2025, Decimal("12.57"), origin=INCIDENTAL_RECHARGE_POOL)
    deposit_to_basin_pool(zone, gw, 2025, Decimal("-12.57"), origin=INCIDENTAL_RECHARGE_POOL)

    row = AllocationCarryover.objects.get(
        zone=zone, water_type=gw, water_year=2025, origin=INCIDENTAL_RECHARGE_POOL
    )
    assert row.amount_af.quantize(Q) == Decimal("0.0000")


@pytest.mark.django_db
def test_pool_row_coexists_with_an_allocation_carryover_row():
    """origin is in the unique key, so a rollover carryover and a basin-pool row
    for the same zone/type/year live side by side — no IntegrityError."""
    zone = ZoneFactory(zone_type="management_area")
    gw = WaterTypeFactory(code="GW")

    carryover = AllocationCarryover.objects.create(
        zone=zone,
        water_type=gw,
        water_year=2025,
        amount_af=Decimal("50.0000"),
        origin="allocation_carryover",
    )
    pool = deposit_to_basin_pool(zone, gw, 2025, Decimal("975"))

    assert carryover.pk != pool.pk
    assert (
        AllocationCarryover.objects.filter(
            zone=zone, water_type=gw, water_year=2025
        ).count()
        == 2
    )
