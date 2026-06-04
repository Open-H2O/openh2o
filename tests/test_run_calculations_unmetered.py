# SPDX-License-Identifier: AGPL-3.0-or-later
"""TDD spec for ``run_calculations --unmetered-only`` (Phase 52.5-01, Task 3).

A real GSA meters some wells and ET-estimates the rest. A metered well's reading
is authoritative (a ``meter_reading`` ledger row); the engine must NOT write a
``calculated`` row for that parcel or it would double-count against the meter.
The ``--unmetered-only`` flag restricts the engine to parcels served by an
UNMETERED well that carry no ``meter_reading`` row for the period — so one run can
fill in the unmetered side without ever touching the metered side. This is what
makes a real engine pass over a fully-populated ET cache (Plan 02) safe.

Hermetic ORM fixture: a metered parcel (``meter_reading`` row + certified_meter
well) and an unmetered parcel (unmetered_estimate well, no meter), both with an
``OpenETCache`` row so ``et_gross`` > 0 and a crop so ``facility_only_zero`` passes
them through.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation
from wells.models import Well, WellIrrigatedParcel, WellType

PERIOD = "2024-06"


def _square(x=0.0):
    poly = Polygon(((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x)))
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(
        parcel_number=number, area_acres=Decimal(acres), geometry=_square())


def _et_cache(parcel, period=PERIOD, et_mm=100.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="ET", model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )


def _irrigate(parcel):
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _well(parcel, method, reg):
    wt, _ = WellType.objects.get_or_create(name="Agricultural")
    w = Well.objects.create(
        well_registration_id=reg, name=f"well {reg}", well_type=wt,
        location=parcel.geometry.centroid, status="active",
        measurement_method=method)
    WellIrrigatedParcel.objects.create(
        well=w, parcel=parcel, fraction=Decimal("1.0000"))
    return w


def _meter_reading(parcel, period=PERIOD, af="-3"):
    year, month = int(period[:4]), int(period[5:7])
    d = dt.date(year, month, 15)
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=d, effective_date=d,
        amount_acre_feet=Decimal(af), source_type="meter_reading",
        description="Monthly metered groundwater extraction")


@pytest.fixture
def metered_and_unmetered():
    metered = _parcel("MTR-1")
    _et_cache(metered)
    _irrigate(metered)
    _well(metered, "certified_meter", "W-MTR-1")
    reading = _meter_reading(metered)

    unmetered = _parcel("UNM-1")
    _et_cache(unmetered)
    _irrigate(unmetered)
    _well(unmetered, "unmetered_estimate", "W-UNM-1")

    call_command("seed_calculation_plan")
    return metered, unmetered, reading


@pytest.mark.django_db
def test_unmetered_only_writes_calculated_for_unmetered_parcel_only(metered_and_unmetered):
    metered, unmetered, _ = metered_and_unmetered
    call_command("run_calculations", "--period", PERIOD, "--unmetered-only")

    # The unmetered parcel gets a calculated row with a non-zero (negative) net.
    row = ParcelLedger.objects.get(parcel=unmetered, source_type="calculated")
    assert row.amount_acre_feet < 0
    # The metered parcel gets NO calculated row (its meter is authoritative).
    assert not ParcelLedger.objects.filter(
        parcel=metered, source_type="calculated").exists()


@pytest.mark.django_db
def test_unmetered_only_leaves_meter_reading_untouched(metered_and_unmetered):
    metered, _, reading = metered_and_unmetered
    call_command("run_calculations", "--period", PERIOD, "--unmetered-only")
    reading.refresh_from_db()
    assert reading.amount_acre_feet == Decimal("-3")
    assert ParcelLedger.objects.filter(
        parcel=metered, source_type="meter_reading").count() == 1


@pytest.mark.django_db
def test_default_behavior_unchanged_computes_both(metered_and_unmetered):
    """Without the flag, the engine computes every ET-bearing parcel (the metered
    one included) — the flag is opt-in and the default path is untouched."""
    metered, unmetered, _ = metered_and_unmetered
    call_command("run_calculations", "--period", PERIOD)
    assert ParcelLedger.objects.filter(
        parcel=metered, source_type="calculated").exists()
    assert ParcelLedger.objects.filter(
        parcel=unmetered, source_type="calculated").exists()


@pytest.mark.django_db
def test_unmetered_only_intersects_with_parcel_filter(metered_and_unmetered):
    """--unmetered-only composes with --parcel (intersect): naming the metered
    parcel yields no calculated row (it is excluded by the metering filter)."""
    metered, _, _ = metered_and_unmetered
    call_command(
        "run_calculations", "--period", PERIOD, "--unmetered-only",
        "--parcel", metered.parcel_number)
    assert not ParcelLedger.objects.filter(
        parcel=metered, source_type="calculated").exists()
