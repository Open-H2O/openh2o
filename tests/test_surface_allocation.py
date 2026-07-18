# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for surface.services.allocate_district_delivery (Phase 55-02).

Proves the platform allocation service wires the Plan-01 demand-weighting kernel
to real recorded diversions correctly: an AMPLE district caps each parcel at
demand/efficiency; a SHORT district splits the whole recorded delivery by demand
weight (thirstier parcel gets more) summing EXACTLY to the recorded total; a
month with no measured ET demand falls back to the static fraction split so the
delivery is never dropped; re-runs are idempotent; dry_run writes nothing; and
efficiency defaults to the agency-wide SiteConfig setting.
"""

from datetime import date
from decimal import Decimal

import pytest

from accounting.models import CalculationRun, WaterType
from core.models import SiteConfig
from parcels.models import ParcelLedger
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db

EFF = Decimal("0.75")
JAN = date(2024, 1, 1)  # inside the ReportingPeriodFactory default WY 2023-2024


def _run(parcel, period, net_demand):
    """A minimal CalculationRun carrying a known net consumptive use (the demand)."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(net_demand)),
        net_consumptive_use_af=Decimal(str(net_demand)),
        final_af=Decimal("0"),
    )


def _surface_rows():
    return ParcelLedger.objects.filter(source_type="surface_diversion")


def test_ample_district_caps_each_parcel_at_demand_over_efficiency():
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.5"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.5"))
    _run(a, "2024-01", 10)  # cap 10/0.75 = 13.3333
    _run(b, "2024-01", 20)  # cap 20/0.75 = 26.6667
    # delivery 50 AF > sum(caps) 40 -> AMPLE
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    by_parcel = {r.parcel_id: r.amount_acre_feet for r in rows}
    assert by_parcel[a.id] == Decimal("-13.3333")
    assert by_parcel[b.id] == Decimal("-26.6667")
    # Sums to sum(caps), NOT the 50 AF delivery — the 10 AF leftover is the
    # recovery-horizon surplus the caller routes (Plan 02/03), by design.
    assert sum(by_parcel.values()) == Decimal("-40.0000")
    assert all(v < 0 for v in by_parcel.values())


def test_short_district_splits_whole_delivery_by_demand():
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b)
    _run(a, "2024-01", 10)
    _run(b, "2024-01", 20)
    # delivery 20 AF < sum(caps) 40 -> SHORT
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("20"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    by_parcel = {r.parcel_id: r.amount_acre_feet for r in rows}
    # whole 20 AF split by demand weight 10:20 -> 6.6667 / 13.3333
    assert by_parcel[a.id] == Decimal("-6.6667")
    assert by_parcel[b.id] == Decimal("-13.3333")
    # SHORT sums EXACTLY to the recorded delivery, and the thirstier parcel wins.
    assert sum(by_parcel.values()) == Decimal("-20.0000")
    assert abs(by_parcel[b.id]) > abs(by_parcel[a.id])


def test_no_et_demand_falls_back_to_fraction_split():
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.6"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.4"))
    # NO CalculationRun -> no demand signal -> kernel returns {} -> fraction split.
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    by_parcel = {r.parcel_id: r.amount_acre_feet for r in rows}
    # static fraction split: 50*0.6 = 30, residual on last = 50-30 = 20
    assert by_parcel[a.id] == Decimal("-30.0000")
    assert by_parcel[b.id] == Decimal("-20.0000")
    assert sum(by_parcel.values()) == Decimal("-50.0000")
    assert "static fraction fallback" in rows[0].description


def test_idempotent_rerun_produces_identical_rows():
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b)
    _run(a, "2024-01", 10)
    _run(b, "2024-01", 20)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)
    first = sorted((r.parcel_id, r.amount_acre_feet) for r in _surface_rows())
    allocate_district_delivery(pod, rp, efficiency=EFF)
    second = sorted((r.parcel_id, r.amount_acre_feet) for r in _surface_rows())

    assert _surface_rows().count() == 2  # not 4 — prior rows deleted, not appended
    assert first == second


def test_dry_run_writes_nothing():
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b)
    _run(a, "2024-01", 10)
    _run(b, "2024-01", 20)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF, dry_run=True)

    assert len(rows) == 2
    assert all(r.pk is None for r in rows)  # unsaved instances
    assert _surface_rows().count() == 0  # nothing persisted


def test_efficiency_defaults_to_siteconfig():
    SiteConfig.objects.create(agency_name="Test GSA")  # default efficiency 0.750
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    _run(a, "2024-01", 30)  # cap 30/0.750 = 40
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),  # ample
    )

    rows = allocate_district_delivery(pod, rp)  # no efficiency arg

    # Capped at demand/efficiency using the agency default 0.750.
    assert rows[0].amount_acre_feet == Decimal("-40.0000")


def test_demand_weighted_rows_carry_surface_water_type():
    """Every demand-weighted surface row is stamped Surface Water (not blank)."""
    WaterType.objects.create(code="SW", name="Surface Water")
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b)
    _run(a, "2024-01", 10)  # ET demand present -> demand-weighted path
    _run(b, "2024-01", 20)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("20"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    assert rows  # demand-weighted path produced rows
    assert "demand-weighted" in rows[0].description  # confirm the path taken
    assert all(r.water_type is not None for r in rows)
    assert all(r.water_type.code == "SW" for r in rows)


def test_fraction_fallback_rows_carry_surface_water_type():
    """The no-ET-demand fraction fallback also stamps Surface Water."""
    WaterType.objects.create(code="SW", name="Surface Water")
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.6"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.4"))
    # NO CalculationRun -> kernel returns {} -> static fraction fallback path.
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    assert "static fraction fallback" in rows[0].description  # confirm the path taken
    assert all(r.water_type is not None for r in rows)
    assert all(r.water_type.code == "SW" for r in rows)


# ---------------------------------------------------------------------------
# T3/T4 (math eval 2026-07-18): the fraction split must normalize, and the
# ample-delivery surplus must be recorded instead of vanishing.
# ---------------------------------------------------------------------------


def test_fraction_fallback_normalizes_fractions_that_do_not_sum_to_one():
    """Raw fractions summing to 1.8 must not invent a positive supply row.

    Nothing in the model forces a POD's fractions to sum to 1. The old split
    multiplied by the raw fraction and dropped the remainder on the last row, so
    [0.6, 0.6, 0.6] on 100 AF produced 60/60/-20 — the last row came out POSITIVE,
    a phantom supply row on a diversion.
    """
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-N1")
    b = ParcelFactory(parcel_number="APN-N2")
    c = ParcelFactory(parcel_number="APN-N3")
    pod = PointOfDiversionFactory()
    for p in (a, b, c):
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p, fraction=Decimal("0.6")
        )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("100"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    by_parcel = {r.parcel_id: r.amount_acre_feet for r in rows}
    # Equal stored fractions normalize to equal thirds of the delivery.
    assert sum(by_parcel.values()) == Decimal("-100.0000")
    assert all(v < 0 for v in by_parcel.values()), "no row may be a positive supply"
    assert by_parcel[a.id] == Decimal("-33.3333")
    assert by_parcel[b.id] == Decimal("-33.3333")
    assert by_parcel[c.id] == Decimal("-33.3334")  # residual on the last key


def test_fraction_fallback_with_untouched_defaults_splits_evenly():
    """Default fractions (1.0 each) must not hand parcel 1 the whole delivery."""
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-D1")
    b = ParcelFactory(parcel_number="APN-D2")
    pod = PointOfDiversionFactory()
    for p in (a, b):
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p, fraction=Decimal("1.0")
        )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("80"),
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    by_parcel = {r.parcel_id: r.amount_acre_feet for r in rows}
    assert by_parcel[a.id] == Decimal("-40.0000")
    assert by_parcel[b.id] == Decimal("-40.0000")


def test_ample_surplus_is_recorded_as_unallocated_delivery():
    """The leftover above sum(caps) is recorded against the POD, not dropped."""
    from surface.models import UnallocatedDelivery

    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-S1")
    b = ParcelFactory(parcel_number="APN-S2")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.5"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.5"))
    _run(a, "2024-01", 10)  # cap 13.3333
    _run(b, "2024-01", 20)  # cap 26.6667
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),  # 50 delivered vs 40 of caps
    )

    rows = allocate_district_delivery(pod, rp, efficiency=EFF)

    assert sum(r.amount_acre_feet for r in rows) == Decimal("-40.0000")
    surplus = UnallocatedDelivery.objects.get(point_of_diversion=pod, month=JAN)
    assert surplus.amount_acre_feet == Decimal("10.0000")
    assert surplus.delivery_acre_feet == Decimal("50.0000")
    assert surplus.reporting_period == rp
    # Parcel rows plus the recorded surplus account for the whole delivery.
    assert (
        abs(sum(r.amount_acre_feet for r in rows)) + surplus.amount_acre_feet
        == Decimal("50.0000")
    )


def test_short_district_records_no_unallocated_surplus():
    """A short delivery is fully distributed, so there is nothing to record."""
    from surface.models import UnallocatedDelivery

    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-S3")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("1.0"))
    _run(a, "2024-01", 100)  # cap 133.33, delivery well under it
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("20"),
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)

    assert not UnallocatedDelivery.objects.filter(point_of_diversion=pod).exists()


def test_rerun_does_not_duplicate_or_strand_unallocated_surplus():
    """Re-allocation clears the prior surplus rather than stacking another."""
    from surface.models import UnallocatedDelivery

    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-S4")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("1.0"))
    _run(a, "2024-01", 10)  # cap 13.3333
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=Decimal("50"),
    )

    allocate_district_delivery(pod, rp, efficiency=EFF)
    allocate_district_delivery(pod, rp, efficiency=EFF)

    rows = UnallocatedDelivery.objects.filter(point_of_diversion=pod, month=JAN)
    assert rows.count() == 1
    assert rows.first().amount_acre_feet == Decimal("36.6667")
