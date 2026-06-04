# SPDX-License-Identifier: AGPL-3.0-or-later
"""TDD spec for the consumptive-use spine (Phase 54-01).

The v1.10 thesis fix: satellite-measured **net consumptive use**
(gross ET − effective precip) is the engine's primary, source-agnostic output —
recorded for every parcel with ET regardless of supply source or whether a well
exists. The ``ET − precip − surface`` leftover (the residual) resolves to a
``calculated`` groundwater row ONLY where the parcel has a well; a no-well
parcel's leftover is recorded as explicit *unmet demand*, never a phantom
``calculated`` groundwater row.

Hermetic ORM fixtures (no network): OpenETCache rows mirror the live shape the
GEE adapter writes — ET rows ``variable="ET"/model="Ensemble"`` keyed ``"et"``,
precip rows ``variable="precip"/model="GRIDMET"`` keyed ``"precip"``.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import CalculationRun, CalculationStep
from accounting.services import parcel_net_consumptive_use
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation
from wells.models import Well, WellIrrigatedParcel, WellType

PERIOD = "2024-06"


# --- hermetic factories -----------------------------------------------------

def _square(x=0.0):
    poly = Polygon(((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x)))
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(
        parcel_number=number, area_acres=Decimal(acres), geometry=_square())


def _et_cache(parcel, period=PERIOD, et_mm=140.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="ET", model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}])


def _precip_cache(parcel, period=PERIOD, precip_mm=130.0):
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


def _surface(parcel, period=PERIOD, af="-4"):
    """Surface delivery (stored NEGATIVE — production convention)."""
    year, month = int(period[:4]), int(period[5:7])
    d = dt.date(year, month, 1)
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=d, effective_date=d,
        amount_acre_feet=Decimal(af), source_type="surface_diversion",
        description="Canal delivery")


# --- Task 1: net consumptive use is the first-class, source-agnostic spine ---

@pytest.mark.django_db
def test_net_consumptive_use_is_gross_et_minus_effective_precip_with_well():
    """(a) A parcel WITH a well: net CU = gross ET − effective precip, recorded
    on the CalculationRun independent of surface delivery."""
    parcel = _parcel("CU-WELL")
    _et_cache(parcel)
    _precip_cache(parcel)
    _irrigate(parcel)
    _well(parcel)
    _surface(parcel)  # net CU must IGNORE surface
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", PERIOD, "--parcel", "CU-WELL")

    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    assert run.effective_precip_af is not None
    assert run.effective_precip_af > 0
    assert run.net_consumptive_use_af == (
        run.gross_et_af - run.effective_precip_af
    )
    # Source-agnostic: net CU does NOT subtract the 4 AF of surface delivery, so
    # it sits a full surface-delivery above the surface-netted final billable.
    assert run.net_consumptive_use_af > run.final_af


@pytest.mark.django_db
def test_net_consumptive_use_recorded_for_surface_only_parcel():
    """(b) A SURFACE-ONLY parcel (no well): net CU is recorded the same way — the
    spine does not require a well. Scoped via --parcel so selection can't hide it."""
    parcel = _parcel("CU-NOWELL")
    _et_cache(parcel)
    _precip_cache(parcel)
    _irrigate(parcel)
    _surface(parcel)
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", PERIOD, "--parcel", "CU-NOWELL")

    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    assert run.net_consumptive_use_af == (
        run.gross_et_af - (run.effective_precip_af or Decimal("0"))
    )
    assert run.net_consumptive_use_af > 0


@pytest.mark.django_db
def test_net_consumptive_use_equals_gross_when_no_precip_step():
    """(c) A plan WITHOUT subtract_effective_precip: net CU == gross ET (effective
    precip treated as 0). The field is never NULL for an ET-bearing run."""
    parcel = _parcel("CU-NOPRECIP")
    _et_cache(parcel)
    _irrigate(parcel)
    _well(parcel)
    call_command("seed_calculation_plan")
    CalculationStep.objects.filter(
        step_type="subtract_effective_precip"
    ).update(enabled=False)
    call_command("run_calculations", "--period", PERIOD, "--parcel", "CU-NOPRECIP")

    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    assert run.effective_precip_af is None
    assert run.net_consumptive_use_af == run.gross_et_af
    assert run.net_consumptive_use_af is not None


@pytest.mark.django_db
def test_parcel_net_consumptive_use_reader_sums_period_runs():
    """(d) parcel_net_consumptive_use sums net CU across a parcel's runs and
    returns Decimal — proven against a two-month fixture."""
    parcel = _parcel("CU-READER")
    _irrigate(parcel)
    _well(parcel)
    for period in ("2024-06", "2024-07"):
        _et_cache(parcel, period=period)
        _precip_cache(parcel, period=period)
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", "2024-06", "--parcel", "CU-READER")
    call_command("run_calculations", "--period", "2024-07", "--parcel", "CU-READER")

    runs = CalculationRun.objects.filter(parcel=parcel)
    expected = sum((r.net_consumptive_use_af for r in runs), Decimal("0"))
    total = parcel_net_consumptive_use(parcel)
    assert isinstance(total, Decimal)
    assert total == expected
    assert runs.count() == 2


@pytest.mark.django_db
def test_net_consumptive_use_idempotent_across_rerun():
    """Re-running a month yields an identical net CU (delete-then-insert held)."""
    parcel = _parcel("CU-IDEM")
    _et_cache(parcel)
    _precip_cache(parcel)
    _irrigate(parcel)
    _well(parcel)
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", PERIOD, "--parcel", "CU-IDEM")
    first = CalculationRun.objects.get(parcel=parcel, period=PERIOD).net_consumptive_use_af
    call_command("run_calculations", "--period", PERIOD, "--parcel", "CU-IDEM")
    assert CalculationRun.objects.filter(parcel=parcel, period=PERIOD).count() == 1
    second = CalculationRun.objects.get(parcel=parcel, period=PERIOD).net_consumptive_use_af
    assert first == second
