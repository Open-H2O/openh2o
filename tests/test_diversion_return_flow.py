# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 67-01 (TDD): returned-volume withholding + consumptive-spine invariance.

Pins two guarantees for the diversion-reach feature:

1. ``consumed_acre_feet()`` / ``clean()`` — a DiversionRecord carries an absolute
   returned-volume number; ``consumed = abs(volume) - returned``, and a return
   that exceeds the diverted volume is rejected at ``clean()``.
2. SPINE INVARIANCE + WITHHOLDING — every ledger write-site routes the CONSUMED
   magnitude (not the gross diverted volume) into ``surface_diversion`` rows. With
   ``returned_af=0`` the summed magnitude is byte-for-byte today's behavior
   (== ``abs(volume)``); with ``returned_af>0`` only the consumed portion is
   written, so returned water can never inflate the consumptive spine.

All five base-magnitude write-sites are exercised: the single-parcel, apportioned,
and WaterRightParcel-fallback paths of
``accounting.services.create_diversion_ledger_entries``, plus the demand-weighted
and static-fraction-fallback paths of
``surface.services.allocate_district_delivery``.

Also pins the one-hop ``rediverted_from`` self-link on PointOfDiversion.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from accounting.models import CalculationRun
from accounting.services import create_diversion_ledger_entries
from parcels.models import ParcelLedger
from surface.models import DiversionRecord
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterRightParcelFactory,
)

pytestmark = pytest.mark.django_db

EFF = Decimal("0.75")
JAN = date(2024, 1, 1)  # inside ReportingPeriodFactory's default WY 2023-2024
VOL = Decimal("100")

# (returned_af, expected consumed magnitude). returned=0 pins spine invariance
# (today's behavior, == abs(volume)); returned=40 pins withholding (only the
# consumed 60 AF reaches the ledger). Drives every write-site test below.
WITHHOLDING = [
    pytest.param(Decimal("0"), Decimal("100"), id="returned-0-spine-invariant"),
    pytest.param(Decimal("40"), Decimal("60"), id="returned-40-withheld"),
]


def _surface_magnitude():
    """Total magnitude (positive AF) of all surface_diversion ledger rows."""
    rows = ParcelLedger.objects.filter(source_type="surface_diversion")
    return sum((abs(r.amount_acre_feet) for r in rows), Decimal("0"))


# --- 1. consumed_acre_feet() arithmetic ------------------------------------


@pytest.mark.parametrize(
    "volume,returned,consumed",
    [
        (Decimal("100"), Decimal("0"), Decimal("100")),
        (Decimal("100"), Decimal("30"), Decimal("70")),
        (Decimal("100"), Decimal("100"), Decimal("0")),   # pure hydro passthrough
        (Decimal("-100"), Decimal("30"), Decimal("70")),  # abs() on stored sign
    ],
)
def test_consumed_acre_feet(volume, returned, consumed):
    record = DiversionRecord(volume_acre_feet=volume, returned_af=returned)
    assert record.consumed_acre_feet() == consumed


# --- 2. clean() guard ------------------------------------------------------


def test_clean_rejects_return_exceeding_volume():
    record = DiversionRecord(
        volume_acre_feet=Decimal("100"), returned_af=Decimal("101")
    )
    with pytest.raises(ValidationError):
        record.clean()


def test_clean_allows_full_volume_return():
    # The hydropower boundary: a pure passthrough returns the whole diverted volume.
    record = DiversionRecord(
        volume_acre_feet=Decimal("100"), returned_af=Decimal("100")
    )
    record.clean()  # must not raise


def test_clean_allows_zero_return_default():
    record = DiversionRecord(
        volume_acre_feet=Decimal("100"), returned_af=Decimal("0")
    )
    record.clean()  # must not raise


# --- 3 & 4. spine invariance + withholding, all five write-sites -----------


@pytest.mark.parametrize("returned,expected", WITHHOLDING)
def test_single_parcel_path(returned, expected):
    """accounting/services.py:120 — explicit single-parcel entry."""
    rp = ReportingPeriodFactory()
    p = ParcelFactory()
    pod = PointOfDiversionFactory()
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=VOL, returned_af=returned,
    )
    create_diversion_ledger_entries(record, parcel=p)
    assert _surface_magnitude() == expected


@pytest.mark.parametrize("returned,expected", WITHHOLDING)
def test_apportioned_path(returned, expected):
    """accounting/services.py:143 — multi-parcel fraction apportionment."""
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(
        point_of_diversion=pod, parcel=a, fraction=Decimal("0.5")
    )
    PointOfDiversionParcelFactory(
        point_of_diversion=pod, parcel=b, fraction=Decimal("0.5")
    )
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=VOL, returned_af=returned,
    )
    create_diversion_ledger_entries(record)
    assert _surface_magnitude() == expected


@pytest.mark.parametrize("returned,expected", WITHHOLDING)
def test_water_right_fallback_path(returned, expected):
    """accounting/services.py:186 — WaterRightParcel fallback (no POD links)."""
    rp = ReportingPeriodFactory()
    p = ParcelFactory()
    pod = PointOfDiversionFactory()
    WaterRightParcelFactory(water_right=pod.water_right, parcel=p)
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=VOL, returned_af=returned,
    )
    # No explicit parcel and no POD-parcel links -> WaterRightParcel fallback.
    create_diversion_ledger_entries(record)
    assert _surface_magnitude() == expected


@pytest.mark.parametrize("returned,expected", WITHHOLDING)
def test_demand_weighted_path(returned, expected):
    """surface/services.py:203 — ET-demand allocation (SHORT: sums to consumed)."""
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b)
    # demand 50+50 -> caps 66.67 each (sum 133); consumed (<=100) is SHORT, so the
    # whole consumed magnitude is distributed and sums EXACTLY to it.
    CalculationRun.objects.create(
        parcel=a, period="2024-01", gross_et_af=Decimal("50"),
        net_consumptive_use_af=Decimal("50"), final_af=Decimal("0"),
    )
    CalculationRun.objects.create(
        parcel=b, period="2024-01", gross_et_af=Decimal("50"),
        net_consumptive_use_af=Decimal("50"), final_af=Decimal("0"),
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=VOL, returned_af=returned,
    )
    rows = allocate_district_delivery(pod, rp, efficiency=EFF)
    assert "demand-weighted" in rows[0].description  # confirm the path taken
    assert _surface_magnitude() == expected


@pytest.mark.parametrize("returned,expected", WITHHOLDING)
def test_static_fraction_fallback_path(returned, expected):
    """surface/services.py:135 — static-fraction fallback (no ET demand)."""
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(
        point_of_diversion=pod, parcel=a, fraction=Decimal("0.6")
    )
    PointOfDiversionParcelFactory(
        point_of_diversion=pod, parcel=b, fraction=Decimal("0.4")
    )
    # NO CalculationRun -> kernel returns {} -> static-fraction fallback.
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN,
        volume_acre_feet=VOL, returned_af=returned,
    )
    rows = allocate_district_delivery(pod, rp, efficiency=EFF)
    assert "static fraction fallback" in rows[0].description
    assert _surface_magnitude() == expected


# --- 5. rediverted_from one-hop self-link ----------------------------------


def test_rediverted_from_links_upstream_pod():
    upstream = PointOfDiversionFactory()
    downstream = PointOfDiversionFactory(rediverted_from=upstream)
    downstream.refresh_from_db()
    assert downstream.rediverted_from_id == upstream.id
    assert list(upstream.rediversions.all()) == [downstream]


def test_rediverted_from_defaults_none():
    pod = PointOfDiversionFactory()
    assert pod.rediverted_from is None
