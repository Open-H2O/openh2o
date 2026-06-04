# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec for seed_merced_recharge_events (Phase 52.5-03).

The managed-recharge half of an honest groundwater budget: wet-season
RechargeEvent rows on the Merced spreading basins, distributed as GROUNDWATER
credits across the overlying GSA's parcels. These tests prove the invariants:

  - GW credit — rows are source_type="recharge", POSITIVE, water_type code "GW".
  - Conservative — per-event distributed amounts sum exactly to the event volume
    (no rounding drift); the season totals one basin capacity.
  - Period-attributed — rows carry the WY 2024-2025 ReportingPeriod (so the
    dashboard, which filters supply by period, counts them), NOT the service's
    default null.
  - Idempotent — re-running reproduces identical rows, no duplication.
  - Distinct from incidental — the self-flush leaves the engine's "Incidental
    recharge" rows untouched (the two recharge kinds never collide).

Runs in the Butler web container (needs the DB).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command

from parcels.models import ParcelLedger
from recharge.models import RechargeEvent
from tests.factories import (
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    RechargeSiteFactory,
    ZoneFactory,
)

Q = Decimal("0.0001")
BASIN = "Cressey-Winton Recharge Basin"


def _fixture(capacity="100.0000", areas=("40", "30", "30")):
    """A GSA zone with parcels + one named basin (zone FK set) + the WY period."""
    period = ReportingPeriodFactory(
        name="WY 2024-2025",
        start_date=date(2024, 10, 1),
        end_date=date(2025, 9, 30),
    )
    zone = ZoneFactory(zone_type="management_area")
    parcels = []
    for i, acres in enumerate(areas):
        p = ParcelFactory(parcel_number=f"MER-APN-{i:06d}", area_acres=Decimal(acres))
        ParcelZoneFactory(parcel=p, zone=zone)
        parcels.append(p)
    basin = RechargeSiteFactory(
        name=BASIN, zone=zone, capacity_acre_feet=Decimal(capacity)
    )
    return period, zone, parcels, basin


@pytest.mark.django_db
def test_managed_recharge_rows_are_positive_gw_credits():
    _fixture()
    call_command("seed_merced_recharge_events")

    rows = ParcelLedger.objects.filter(source_type="recharge")
    assert rows.exists()
    assert all(r.amount_acre_feet > 0 for r in rows)
    assert all(r.water_type and r.water_type.code == "GW" for r in rows)
    assert all(r.description.startswith("Recharge from") for r in rows)


@pytest.mark.django_db
def test_each_event_distributes_exactly_to_its_volume():
    _, _, _, basin = _fixture(capacity="100.0000")
    call_command("seed_merced_recharge_events")

    # Four wet-season events; each event's rows must sum to that event's volume.
    for event in RechargeEvent.objects.filter(recharge_site=basin):
        rows = ParcelLedger.objects.filter(
            source_type="recharge", effective_date=event.start_date
        )
        assert sum((r.amount_acre_feet for r in rows), Decimal("0")) == (
            event.volume_acre_feet
        )
    # Whole season totals one basin capacity (0.20+0.30+0.30+0.20 = 1.00).
    total = sum(
        (r.amount_acre_feet for r in ParcelLedger.objects.filter(
            source_type="recharge")),
        Decimal("0"),
    )
    assert total.quantize(Q) == Decimal("100.0000")


@pytest.mark.django_db
def test_rows_are_attributed_to_the_reporting_period():
    period, _, _, _ = _fixture()
    call_command("seed_merced_recharge_events")
    rows = ParcelLedger.objects.filter(source_type="recharge")
    assert rows.exists()
    assert all(r.reporting_period_id == period.id for r in rows)


@pytest.mark.django_db
def test_seed_is_idempotent():
    _fixture()
    call_command("seed_merced_recharge_events")
    first = ParcelLedger.objects.filter(source_type="recharge").count()
    events_first = RechargeEvent.objects.count()
    call_command("seed_merced_recharge_events")
    assert ParcelLedger.objects.filter(source_type="recharge").count() == first
    assert RechargeEvent.objects.count() == events_first
    assert first > 0


@pytest.mark.django_db
def test_flush_leaves_engine_incidental_recharge_untouched():
    """The self-flush keys on the 'Recharge from <basin>' description, so the
    engine's 'Incidental recharge' rows (same source_type) survive."""
    _, _, parcels, _ = _fixture()
    incidental = ParcelLedger.objects.create(
        parcel=parcels[0],
        transaction_date=date(2025, 7, 1),
        effective_date=date(2025, 7, 1),
        amount_acre_feet=Decimal("2.5000"),
        source_type="recharge",
        description="Incidental recharge — deep percolation from surface over-delivery",
    )
    call_command("seed_merced_recharge_events")
    call_command("seed_merced_recharge_events")  # re-run: flush must spare it
    assert ParcelLedger.objects.filter(pk=incidental.pk).exists()
    assert ParcelLedger.objects.filter(
        source_type="recharge", description__startswith="Incidental"
    ).count() == 1
