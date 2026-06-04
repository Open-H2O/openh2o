# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for per-district recovery horizon in rollover_allocations (Phase 55-02).

The Phase 39 rollover banked every zone's year-end remainder forward. 55-02 adds
the per-district CHOICE: a district on a "same_water_year" (expire) horizon sheds
its unused SURPLUS at year-end (use-it-or-lose-it), but still carries a DEBT (an
overdraw is a real obligation policy can't wish away). A carry_forward district is
unchanged, and a district with no override inherits the agency-wide SiteConfig
default. carry_forward is the default everywhere, so Phase 39 behavior is preserved.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounting.models import AllocationCarryover
from core.models import SiteConfig
from parcels.models import ParcelLedger
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


def gw_type():
    return WaterTypeFactory(name="Groundwater", code="GW")


def wy_period(finalized=True):
    return ReportingPeriodFactory(
        name="WY 2023-2024",
        start_date=date(2023, 10, 1),
        end_date=date(2024, 9, 30),
        is_finalized=finalized,
    )


def _usage_row(parcel, af):
    """A negative (groundwater usage) et_estimate row inside WY 2024."""
    ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=date.today(),
        effective_date=date(2024, 6, 1),
        amount_acre_feet=Decimal(str(-abs(af))),
        source_type="et_estimate",
    )


def make_zone(gw, period, *, alloc, usage, recovery_horizon=None):
    zone = ZoneFactory(recovery_horizon=recovery_horizon)
    parcel = ParcelFactory()
    ParcelZoneFactory(parcel=parcel, zone=zone)
    AllocationPlanFactory(
        zone=zone,
        water_type=gw,
        reporting_period=period,
        allocation_acre_feet=Decimal(str(alloc)),
    )
    if usage:
        _usage_row(parcel, usage)
    return zone


def test_carry_forward_zone_banks_surplus():
    """Default (no override, no SiteConfig) carries surplus forward — Phase 39."""
    gw = gw_type()
    period = wy_period()
    zone = make_zone(gw, period, alloc=100, usage=30)

    call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())

    row = AllocationCarryover.objects.get(zone=zone, water_type=gw)
    assert row.amount_af == Decimal("70.0000")


def test_expire_zone_surplus_not_written():
    """A same_water_year district's surplus expires — no carry-over row."""
    gw = gw_type()
    period = wy_period()
    zone = make_zone(gw, period, alloc=100, usage=30, recovery_horizon="same_water_year")

    out = StringIO()
    call_command("rollover_allocations", "--water-year", "2024", stdout=out)

    assert not AllocationCarryover.objects.filter(zone=zone).exists()
    assert "EXPIRES" in out.getvalue()


def test_expire_zone_debt_still_written():
    """A same_water_year district's DEBT still carries — an overdraw is owed."""
    gw = gw_type()
    period = wy_period()
    zone = make_zone(gw, period, alloc=100, usage=130, recovery_horizon="same_water_year")

    call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())

    row = AllocationCarryover.objects.get(zone=zone, water_type=gw)
    assert row.amount_af == Decimal("-30.0000")


def test_null_override_follows_agency_default():
    """A zone with no override inherits SiteConfig.default_recovery_horizon."""
    SiteConfig.objects.create(
        agency_name="Test GSA", default_recovery_horizon="same_water_year"
    )
    gw = gw_type()
    period = wy_period()
    zone = make_zone(gw, period, alloc=100, usage=30, recovery_horizon=None)

    call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())

    # Inherited expire policy: the surplus is shed.
    assert not AllocationCarryover.objects.filter(zone=zone).exists()


def test_idempotent_with_mixed_horizons():
    """Mixed horizons: carry surplus + expire debt written, expire surplus shed;
    a re-run is byte-identical (delete-then-insert contract preserved)."""
    gw = gw_type()
    period = wy_period()
    carry = make_zone(gw, period, alloc=100, usage=30)  # carry_forward surplus -> +70
    expire_surplus = make_zone(
        gw, period, alloc=100, usage=30, recovery_horizon="same_water_year"
    )  # surplus -> shed
    expire_debt = make_zone(
        gw, period, alloc=100, usage=130, recovery_horizon="same_water_year"
    )  # debt -> -30 still carried

    call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())
    first = sorted((c.zone_id, c.amount_af) for c in AllocationCarryover.objects.all())
    call_command("rollover_allocations", "--water-year", "2024", stdout=StringIO())
    second = sorted((c.zone_id, c.amount_af) for c in AllocationCarryover.objects.all())

    assert AllocationCarryover.objects.count() == 2  # expire surplus suppressed
    assert first == second
    assert not AllocationCarryover.objects.filter(zone=expire_surplus).exists()
    assert AllocationCarryover.objects.get(zone=carry).amount_af == Decimal("70.0000")
    assert AllocationCarryover.objects.get(zone=expire_debt).amount_af == Decimal("-30.0000")
