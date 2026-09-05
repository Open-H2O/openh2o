# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec for seed_merced_recharge_events (Phase 52.6-02, ISS-053).

The managed-recharge half of an honest groundwater budget. As of 52.6-02 the
event volume NO LONGER smears area-weighted across every parcel in the zone (the
ISS-053 phantom: a recoverable credit on surface-only parcels that have no well).
Instead the whole volume deposits to the zone's GSA basin recharge pool — an
``AllocationCarryover`` row, origin ``basin_recharge_pool``. These prove:

  - Pooled — the season's full capacity lands in ONE basin-pool row (GW, the
    event water-year), not spread across parcels.
  - No smear — ZERO per-parcel ``source_type="recharge"`` ledger rows are
    written for the managed event; the phantom parcel (MER-APN-031, no well)
    receives nothing.
  - Idempotent — re-running resets the seed's pool slice and re-deposits, so the
    pool total is unchanged (no double-count).
  - Distinct from incidental — the self-flush keys on the managed origin /
    "Recharge from <basin>" description, so the engine's separate incidental pool
    and its "Incidental recharge" ledger rows survive untouched.

Runs in the web container (needs the DB).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command

from accounting.models import AllocationCarryover, WaterType
from accounting.services import BASIN_RECHARGE_POOL, INCIDENTAL_RECHARGE_POOL
from parcels.models import ParcelLedger
from recharge.models import RechargeEvent
from tests.factories import (
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    RechargeSiteFactory,
    WaterTypeFactory,
    ZoneFactory,
)

Q = Decimal("0.0001")
BASIN = "Cressey-Winton Recharge Basin"
# Events span Dec 2024 – Mar 2025 → all water year 2025 (Oct–Sep, named by end).
EVENT_WY = 2025
# 133-02: the dry year's two fills land in the following water year, so they pool
# to their OWN AllocationCarryover row rather than adding to the wet year's.
DRY_EVENT_WY = 2026


def _fixture(capacity="100.0000", areas=("40", "30", "30")):
    """A GSA zone with parcels (incl. the phantom MER-APN-031, no well) + one named
    basin (zone FK set) + BOTH WY periods + a GW water type.

    133-02: the seed now writes a season for each demonstration water year and
    checks both periods exist as its prerequisite, so the fixture builds both.
    """
    WaterTypeFactory(code="GW", name="Groundwater")
    period = ReportingPeriodFactory(
        name="WY 2024-2025",
        start_date=date(2024, 10, 1),
        end_date=date(2025, 9, 30),
    )
    ReportingPeriodFactory(
        name="WY 2025-2026",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )
    zone = ZoneFactory(zone_type="management_area")
    parcels = []
    # MER-APN-031 is the ISS-053 phantom: a surface-only, no-well parcel that the
    # old smear handed a groundwater recharge credit it cannot pump.
    numbers = ["MER-APN-031", "MER-APN-040", "MER-APN-041"]
    for number, acres in zip(numbers, areas):
        p = ParcelFactory(parcel_number=number, area_acres=Decimal(acres))
        ParcelZoneFactory(parcel=p, zone=zone)
        parcels.append(p)
    # operator + spreading_basin are how seed_merced_recharge_events now finds the
    # Merced recharge areas (by operator, not hardcoded names — Phase 62).
    basin = RechargeSiteFactory(
        name=BASIN, zone=zone, capacity_acre_feet=Decimal(capacity),
        operator="Halvern Irrigation District", site_type="spreading_basin",
    )
    return period, zone, parcels, basin


def _pool_total(zone, origin=BASIN_RECHARGE_POOL):
    return sum(
        (
            r.amount_af
            for r in AllocationCarryover.objects.filter(zone=zone, origin=origin)
        ),
        Decimal("0"),
    )


@pytest.mark.django_db
def test_managed_recharge_pools_at_gsa_level_not_per_parcel():
    _, zone, _, _ = _fixture(capacity="100.0000")
    call_command("seed_merced_recharge_events")

    rows = AllocationCarryover.objects.filter(
        zone=zone, origin=BASIN_RECHARGE_POOL, water_year=EVENT_WY
    )
    assert rows.count() == 1  # one pool row, not a per-parcel spread
    pool = rows.first()
    assert pool.water_type.code == "GW"
    # Whole season totals one basin capacity (0.20+0.30+0.30+0.20 = 1.00).
    assert pool.amount_af.quantize(Q) == Decimal("100.0000")


@pytest.mark.django_db
def test_no_per_parcel_recharge_ledger_rows_are_written():
    """The managed event writes NO ParcelLedger recharge rows — the area-weighted
    smear is gone."""
    _fixture()
    call_command("seed_merced_recharge_events")
    assert ParcelLedger.objects.filter(source_type="recharge").count() == 0


@pytest.mark.django_db
def test_phantom_parcel_receives_zero_recharge():
    """MER-APN-031 (no well) gets zero recharge ledger AF from the managed event —
    the ISS-053 phantom is dead at the source."""
    _, _, parcels, _ = _fixture()
    call_command("seed_merced_recharge_events")
    phantom = parcels[0]
    assert phantom.parcel_number == "MER-APN-031"
    assert not ParcelLedger.objects.filter(
        parcel=phantom, source_type="recharge"
    ).exists()


@pytest.mark.django_db
def test_seed_is_idempotent_no_double_count():
    _, zone, _, _ = _fixture(capacity="100.0000")
    call_command("seed_merced_recharge_events")
    first_total = _pool_total(zone)
    events_first = RechargeEvent.objects.count()

    call_command("seed_merced_recharge_events")  # re-run
    assert _pool_total(zone).quantize(Q) == first_total.quantize(Q)
    # 1.00x capacity in the wet year plus 0.50x in the dry one (133-02).
    assert _pool_total(zone).quantize(Q) == Decimal("150.0000")
    assert RechargeEvent.objects.count() == events_first
    # One pool row PER WATER YEAR, still never one per parcel.
    assert (
        AllocationCarryover.objects.filter(
            zone=zone, origin=BASIN_RECHARGE_POOL
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_flush_leaves_engine_incidental_pool_and_rows_untouched():
    """The self-flush touches only the MANAGED origin / 'Recharge from <basin>'
    rows, so the engine's incidental pool AND its 'Incidental recharge' ledger
    rows survive a re-seed."""
    _, zone, parcels, _ = _fixture()
    # An engine-style incidental pool row (separate origin) + a personal-credit
    # incidental ledger row, both pre-existing.
    AllocationCarryover.objects.create(
        zone=zone,
        water_type=WaterType.objects.get(code="GW"),
        water_year=EVENT_WY,
        amount_af=Decimal("7.5000"),
        origin=INCIDENTAL_RECHARGE_POOL,
    )
    incidental = ParcelLedger.objects.create(
        parcel=parcels[0],
        transaction_date=date(2025, 7, 1),
        effective_date=date(2025, 7, 1),
        amount_acre_feet=Decimal("2.5000"),
        source_type="recharge",
        description="Incidental recharge — deep percolation from surface over-delivery",
    )

    call_command("seed_merced_recharge_events")
    call_command("seed_merced_recharge_events")  # re-run: flush must spare both

    assert ParcelLedger.objects.filter(pk=incidental.pk).exists()
    assert _pool_total(zone, origin=INCIDENTAL_RECHARGE_POOL).quantize(Q) == Decimal(
        "7.5000"
    )


# --------------------------------------------------------------------------
# 133-02 — the second water year's recharge: smaller, not absent
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_dry_year_recharges_half_as_much_as_the_wet_year():
    """Both years spread water; the dry year spreads half a basin capacity.

    Not "some less" — the ratio is the 0.50 rainfall multiplier 133-01 applied to
    the satellite record, so the two halves of the demonstration agree about how
    dry the dry year was.
    """
    _, zone, _, _ = _fixture(capacity="100.0000")
    call_command("seed_merced_recharge_events")

    def pooled(water_year):
        return _pool_total_for_year(zone, water_year)

    assert pooled(EVENT_WY).quantize(Q) == Decimal("100.0000")
    assert pooled(DRY_EVENT_WY).quantize(Q) == Decimal("50.0000")
    assert pooled(DRY_EVENT_WY) == pooled(EVENT_WY) / 2


@pytest.mark.django_db
def test_the_dry_year_has_fewer_storms_not_smaller_ones():
    """Two fills in the dry winter against four in the wet one.

    A dry winter is short of storms before it is short of water in each one, and
    the shoulder months (December, March) do not happen at all.
    """
    _fixture()
    call_command("seed_merced_recharge_events")

    months = sorted(
        (e.start_date.year, e.start_date.month)
        for e in RechargeEvent.objects.all()
    )
    assert months == [
        (2024, 12), (2025, 1), (2025, 2), (2025, 3),   # wet: four fills
        (2026, 1), (2026, 2),                          # dry: two mid-winter
    ]


@pytest.mark.django_db
def test_every_event_falls_inside_a_demonstration_reporting_period():
    """No fill is dated into a year the demonstration does not account for."""
    from accounting.models import ReportingPeriod

    _fixture()
    call_command("seed_merced_recharge_events")

    spans = [
        (rp.start_date, rp.end_date) for rp in ReportingPeriod.objects.all()
    ]
    for event in RechargeEvent.objects.all():
        assert any(lo <= event.start_date <= hi for lo, hi in spans), (
            f"{event.start_date} falls outside every reporting period"
        )


def _pool_total_for_year(zone, water_year):
    return sum(
        (
            r.amount_af
            for r in AllocationCarryover.objects.filter(
                zone=zone, origin=BASIN_RECHARGE_POOL, water_year=water_year
            )
        ),
        Decimal("0"),
    )
