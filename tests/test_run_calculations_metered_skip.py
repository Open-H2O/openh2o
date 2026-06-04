# SPDX-License-Identifier: AGPL-3.0-or-later
"""TDD spec for the run_calculations DEFAULT metered-skip selection (Phase 54-01).

The engine runs on ALL parcels by default. The only parcels it skips are those
that carry an authoritative ``meter_reading`` ledger row for the period — a
metered reading is the truth, and a `calculated` row would double-count it. This
replaces the 52.5-01 ``--unmetered-only`` framing crutch, which existed only to
hide the garbage the old groundwater-residual model produced for non-well
parcels. ``--unmetered-only`` is kept as a deprecated alias: it warns and runs the
default. No-well parcels now follow 54-01 (no calculated row; an unmet-demand run)
and never bank a personal WaterCredit they have no well to draw against.

Hermetic ORM fixtures, no network.
"""
import datetime as dt
import io
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import CalculationRun, CalculationStep, WaterCredit
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
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}])


def _precip_cache(parcel, period=PERIOD, precip_mm=200.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="precip", model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}])


def _irrigate(parcel):
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _well(parcel, method="unmetered_estimate", reg=None):
    wt, _ = WellType.objects.get_or_create(name="Agricultural")
    w = Well.objects.create(
        well_registration_id=reg or f"W-{parcel.parcel_number}",
        name=f"well {parcel.parcel_number}", well_type=wt,
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


def _surface(parcel, period=PERIOD, af="-2"):
    year, month = int(period[:4]), int(period[5:7])
    d = dt.date(year, month, 1)
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=d, effective_date=d,
        amount_acre_feet=Decimal(af), source_type="surface_diversion",
        description="Canal delivery")


@pytest.fixture
def mixed_parcels():
    """A metered parcel, an unmetered-well parcel, and a surface-only no-well one."""
    metered = _parcel("MTR-1")
    _et_cache(metered)
    _irrigate(metered)
    _well(metered, method="certified_meter", reg="W-MTR-1")
    _meter_reading(metered)

    unmetered = _parcel("UNM-1")
    _et_cache(unmetered)
    _irrigate(unmetered)
    _well(unmetered, method="unmetered_estimate", reg="W-UNM-1")

    surface_only = _parcel("SURF-1")
    _et_cache(surface_only)
    _irrigate(surface_only)
    _surface(surface_only)

    call_command("seed_calculation_plan")
    return metered, unmetered, surface_only


# --- (a) DEFAULT path skips a parcel with an authoritative meter reading -------

@pytest.mark.django_db
def test_default_skips_metered_parcel(mixed_parcels):
    metered, _, _ = mixed_parcels
    call_command("run_calculations", "--period", PERIOD)
    assert not ParcelLedger.objects.filter(
        parcel=metered, source_type="calculated").exists()
    # Its authoritative meter reading is untouched.
    assert ParcelLedger.objects.filter(
        parcel=metered, source_type="meter_reading").count() == 1


# --- (b) DEFAULT path computes the unmetered-well AND the surface-only parcels --

@pytest.mark.django_db
def test_default_computes_unmetered_well_and_surface_only(mixed_parcels):
    _, unmetered, surface_only = mixed_parcels
    call_command("run_calculations", "--period", PERIOD)

    # Unmetered well: a calculated groundwater row.
    assert ParcelLedger.objects.filter(
        parcel=unmetered, source_type="calculated").exists()
    # Surface-only no-well (ISS-054, formerly mis-billed then hidden): NO
    # calculated row, but an unmet-demand run exists.
    assert not ParcelLedger.objects.filter(
        parcel=surface_only, source_type="calculated").exists()
    run = CalculationRun.objects.get(parcel=surface_only, period=PERIOD)
    assert run.residual_disposition == "unmet_demand"
    assert run.net_consumptive_use_af > 0


# --- (c) --unmetered-only is a deprecated alias that matches the default --------

@pytest.mark.django_db
def test_unmetered_only_is_deprecated_alias_matching_default(mixed_parcels):
    call_command("run_calculations", "--period", PERIOD)
    default_calc = set(
        ParcelLedger.objects.filter(source_type="calculated")
        .values_list("parcel__parcel_number", flat=True))

    err = io.StringIO()
    call_command("run_calculations", "--period", PERIOD, "--unmetered-only", stderr=err)
    assert "deprecated" in err.getvalue().lower()

    alias_calc = set(
        ParcelLedger.objects.filter(source_type="calculated")
        .values_list("parcel__parcel_number", flat=True))
    assert alias_calc == default_calc


# --- (d) no-well parcel banks no WaterCredit; a well parcel still banks ---------

@pytest.mark.django_db
def test_no_well_rain_surplus_banks_no_credit_but_well_parcel_does():
    """A genuine rain surplus (method=raw so Pe can exceed ET) banks a WaterCredit
    on a well parcel, but NEVER on a no-well parcel (no well to draw it back)."""
    no_well = _parcel("CREDIT-NOWELL")
    _et_cache(no_well, et_mm=40.0)
    _precip_cache(no_well, precip_mm=200.0)  # rain > ET → genuine surplus
    _irrigate(no_well)

    well = _parcel("CREDIT-WELL")
    _et_cache(well, et_mm=40.0)
    _precip_cache(well, precip_mm=200.0)
    _irrigate(well)
    _well(well)

    call_command("seed_calculation_plan")
    # raw method lets effective precip exceed ET (usda_scs caps it at ET).
    CalculationStep.objects.filter(
        step_type="subtract_effective_precip").update(config={"method": "raw"})
    call_command("run_calculations", "--period", PERIOD)

    assert WaterCredit.objects.filter(parcel=no_well).count() == 0
    assert WaterCredit.objects.filter(parcel=well).count() == 1
