# SPDX-License-Identifier: AGPL-3.0-or-later
"""DB-bound tests of a month whose supplies exceed its crop ET.

The floor step records the month's rain surplus and the run records any canal
over-delivery; neither is written to the ledger as a credit.

Runs in the web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import (
    CalculationPlan,
    CalculationRun,
    CalculationStep,
)
from accounting.services import et_mm_to_acre_feet
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation
from tests.factories import (
    ParcelZoneFactory,
    WellIrrigatedParcelFactory,
    ZoneFactory,
)

Q = Decimal("0.0001")


def _zone_for(parcel):
    """Put the parcel in a management-area GSA zone (where its basin pool lives)."""
    zone = ZoneFactory(zone_type="management_area")
    ParcelZoneFactory(parcel=parcel, zone=zone)
    return zone


def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(parcel_number=number, area_acres=Decimal(acres))


def _irrigate(parcel):
    """Give the parcel a crop."""
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _et_cache(parcel, period="2024-06", et_mm=100.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    et_row = OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )
    from datasync.crop_et import months_of, record_fetched_months

    record_fetched_months(et_row.parcel, months_of(et_row.et_data), model=et_row.model_name)
    return et_row


def _precip_cache(parcel, period, precip_mm):
    """A GRIDMET precip cache row in the live shape (value keyed "precip")."""
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    row = OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="precip",
        model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}],
    )
    # Recorded the way the rain writers record a month they received (ruling 208).
    from datasync.crop_et import months_of, record_fetched_months

    record_fetched_months(parcel, months_of(row.et_data, "precip"), variable="precip", model="GRIDMET")
    return row


def _surface_row(parcel, period, af):
    """A surface_diversion ledger row (stored NEGATIVE, like the live data)."""
    year, month = int(period[:4]), int(period[5:7])
    return ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=dt.date(year, month, 1),
        effective_date=dt.date(year, month, 1),
        amount_acre_feet=Decimal(str(-abs(af))),
        source_type="surface_diversion",
    )


def _gross_af(et_mm="100", acres="10"):
    """The positive gross-ET magnitude the et_gross step produces."""
    return abs(et_mm_to_acre_feet(Decimal(et_mm), Decimal(acres)))


def _calc_row(parcel, period):
    year, month = int(period[:4]), int(period[5:7])
    return ParcelLedger.objects.get(
        parcel=parcel,
        effective_date=dt.date(year, month, 1),
        source_type="calculated",
    )


def _run(parcel, period):
    return CalculationRun.objects.get(parcel=parcel, period=period)


def _raw_precip_plan():
    """A plan with method='raw' so effective precip can exceed ET (genuine rain
    surplus), and the seeded clamp_floor."""
    call_command("seed_calculation_plan")
    CalculationStep.objects.filter(
        plan=CalculationPlan.active(), step_type="subtract_effective_precip"
    ).update(config={"method": "raw"})


@pytest.mark.django_db
def test_surface_over_delivery_is_recorded_on_the_run_only():
    """5 AF delivered lets the crop use 5 x 0.750 = 3.75 AF, above the month's
    gross ET, so the run records the over-delivery and no ledger row carries it."""
    parcel = _parcel("BANK-DEP", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=100.0)  # ~3.28 AF gross
    _irrigate(parcel)  # crop, no well
    _zone_for(parcel)
    _surface_row(parcel, "2024-02", af=5)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02")

    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge"
    ).exists()
    EFF = Decimal("0.750")
    consumed = (Decimal("5") * EFF).quantize(Q)
    over_delivery = (consumed - _gross_af()).quantize(Q)
    assert over_delivery > 0, "fixture must produce a real over-delivery"
    run = CalculationRun.objects.get(parcel=parcel, period="2024-02")
    assert run.over_delivery_af == over_delivery
    # A no-well parcel gets no `calculated` groundwater row.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated"
    ).exists()
    assert run.residual_disposition == "unmet_demand"
    assert run.unmet_demand_af == Decimal("0.0000")


@pytest.mark.django_db
def test_normal_extraction_month_writes_a_negative_calculated_row():
    parcel = _parcel("BANK-NONE", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)
    WellIrrigatedParcelFactory(parcel=parcel)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    assert _calc_row(parcel, "2024-06").amount_acre_feet < 0


@pytest.mark.django_db
def test_below_floor_rain_month_records_rain_surplus_af():
    """Pe > ET with method=raw. Acreage 30.48 and mm inputs divisible by 25.4
    make every conversion exact, so the expected value is a literal."""
    parcel = _parcel("BANK-RAIN", acres="30.48")
    _et_cache(parcel, period="2024-02", et_mm=100.0)  # -> 10.0000 AF gross ET
    _precip_cache(parcel, period="2024-02", precip_mm=254.0)  # -> 25.4000 AF rain
    _irrigate(parcel)
    WellIrrigatedParcelFactory(parcel=parcel)
    _raw_precip_plan()

    call_command("run_calculations", "--period", "2024-02")

    run = _run(parcel, "2024-02")
    clamp = next(s for s in run.breakdown if s["step_type"] == "clamp_floor")
    detail = clamp["detail"]
    # No surface delivery, so the whole below-floor amount is rain: 25.4 - 10.0.
    assert Decimal(detail["rain_surplus_af"]) == Decimal("15.4")
    assert Decimal(detail["incidental_recharge_af"]) == Decimal("0")
    assert Decimal(detail["surplus_af"]) == Decimal("15.4")
    assert not ParcelLedger.objects.filter(parcel=parcel, amount_acre_feet__gt=0).exists()


@pytest.mark.django_db
def test_dry_run_writes_no_calculated_row():
    parcel = _parcel("BANK-DRY", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=100.0)
    _irrigate(parcel)
    _surface_row(parcel, "2024-02", af=5)
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02", "--dry-run")

    assert not ParcelLedger.objects.filter(source_type="calculated").exists()
    assert not CalculationRun.objects.filter(parcel=parcel).exists()
