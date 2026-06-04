# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermetic proof that the per-parcel books close after the two-pass refresh.

This is the v1.10 capstone invariant (Phase 58-01, ISS-054): after the corrected
accounting refresh runs — ``run_calculations`` (populate net consumptive use) ->
``allocate_district_delivery`` (demand-weighted surface) -> ``run_calculations``
(recompute residual + recharge) — ``parcel_mass_balance(...).closes`` is True for
every archetype the Merced demo exercises:

  * **Surface-only** (POD, no well, ample delivery) — the ISS-054 / MER-APN-031
    case. The over-delivery percolates as incidental recharge; the books close
    with ZERO pumped groundwater and NO phantom ``calculated`` row (54-01).
  * **Conjunctive** (well + POD, short delivery) — the MER-APN-016 case. The
    surface shortfall is met by pumped groundwater; the books close on the
    ``calculated`` groundwater term.
  * **Basin / flood-MAR** (no well, ample delivery, in a GSA management zone) —
    the over-delivery's incidental recharge routes to the GSA basin POOL, with NO
    positive personal recharge credit the parcel could never pump (the ISS-053
    invariant); the books still close.

The closing identity (52.6-03) is
``surface + precip + gw_recovered = et + recharge + runoff + delta_storage``.
Closure is exercised on the engine's OWN output (not hand-seeded run rows), so a
non-zero residual here is a real calibration disagreement between the seed
envelope, the allocation efficiency, and the engine's recharge step — exactly
what this plan exists to lock down.

Hermetic ORM fixtures (no network): OpenETCache rows mirror the live GEE shape —
ET rows ``variable="ET"/model="Ensemble"`` keyed ``"et"``, precip rows
``variable="precip"/model="GRIDMET"`` keyed ``"precip"``. The fixture keeps
gross ET well above effective precip per month, so net consumptive use stays
positive and ``clamp_floor`` parks the whole surface over-delivery in
``incidental_recharge_af`` (a no-well parcel banks nothing, so any bankable
precip-surplus would otherwise vanish and break closure).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import AllocationCarryover, CalculationRun
from accounting.services import parcel_mass_balance
from core.models import SiteConfig
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
)
from wells.models import Well, WellIrrigatedParcel, WellType

pytestmark = pytest.mark.django_db

PERIOD = "2024-01"  # inside the default ReportingPeriodFactory span (WY 2023-2024)
EFF = Decimal("0.750")  # the demo's agency-wide irrigation efficiency (55-03)


# --- hermetic builders (mirrors tests/test_consumptive_use_spine.py) --------

def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="40"):
    return Parcel.objects.create(
        parcel_number=number, area_acres=Decimal(acres), geometry=_square()
    )


def _et_cache(parcel, et_mm, period=PERIOD):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="ET", model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}])


def _precip_cache(parcel, precip_mm, period=PERIOD):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="precip", model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}])


def _irrigate(parcel):
    """Give the parcel a crop so facility_only_zero does not zero its ET."""
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _well(parcel):
    wt, _ = WellType.objects.get_or_create(name="Agricultural")
    well = Well.objects.create(
        well_registration_id=f"W-{parcel.parcel_number}",
        name=f"well {parcel.parcel_number}", well_type=wt,
        location=parcel.geometry.centroid, status="active",
        measurement_method="unmetered_estimate")
    WellIrrigatedParcel.objects.create(
        well=well, parcel=parcel, fraction=Decimal("1.0000"))
    return well


def _pool_zone(name):
    """A GSA management-area zone the parcel sits in — where its basin pool lives."""
    from geography.models import Boundary, ParcelZone, Zone

    boundary = Boundary.objects.create(name=f"B-{name}", geometry=_square())
    return Zone.objects.create(
        name=name, boundary=boundary, geometry=_square(),
        zone_type="management_area"), ParcelZone


def _pod_serving(parcel, *, volume_af, rp):
    """A single-parcel POD + one recorded DiversionRecord of ``volume_af``.

    A single-parcel POD makes allocation deterministic: AMPLE hands the parcel its
    demand/efficiency cap, SHORT hands it the whole recorded delivery.
    """
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp,
        month=dt.date(int(PERIOD[:4]), int(PERIOD[5:7]), 1),
        volume_acre_feet=Decimal(str(volume_af)))
    return pod


def _setup_period():
    """A non-finalized ReportingPeriod + active calc plan + SiteConfig efficiency.

    is_finalized=False so run_calculations does not refuse without --force; the
    SiteConfig singleton supplies the efficiency allocate_district_delivery reads.
    """
    rp = ReportingPeriodFactory(is_finalized=False)
    SiteConfig.objects.create(
        agency_name="Merced Subbasin GSA", default_irrigation_efficiency=EFF)
    call_command("seed_calculation_plan")
    return rp


def _two_pass_refresh(pods, rp):
    """Run the same sequence refresh_merced_accounting runs, scoped to the test.

    run_calculations (net CU) -> allocate_district_delivery per POD (demand-weighted
    surface) -> run_calculations (recompute residual + recharge). Mirrors the
    Task-1 command's three steps without needing the full physical Merced demo.
    """
    call_command("run_calculations", "--period", PERIOD)
    for pod in pods:
        allocate_district_delivery(pod, rp)
    call_command("run_calculations", "--period", PERIOD)


# --- the three archetype closure proofs -------------------------------------

def test_surface_only_parcel_mass_balance_closes():
    """Surface-only (no well, ample delivery): closes via incidental recharge,
    with NO pumped groundwater and NO phantom `calculated` row (54-01 / ISS-054)."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-031")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    zone, ParcelZone = _pool_zone("surface-only-pool")
    ParcelZone.objects.create(parcel=parcel, zone=zone)
    pod = _pod_serving(parcel, volume_af=100, rp=rp)  # >> cap -> AMPLE

    _two_pass_refresh([pod], rp)

    balance = parcel_mass_balance(parcel, rp)
    assert balance["closes"] is True, balance
    assert balance["inputs"]["gw_recovered"] == Decimal("0")
    assert balance["outputs"]["recharge"] > 0  # over-delivery percolated
    # 54-01 invariant: a no-well parcel writes NO phantom groundwater row.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated").exists()


def test_conjunctive_parcel_mass_balance_closes():
    """Conjunctive (well + POD, short delivery): closes on pumped groundwater."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-016")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    _well(parcel)
    pod = _pod_serving(parcel, volume_af=2, rp=rp)  # << net demand -> SHORT

    _two_pass_refresh([pod], rp)

    balance = parcel_mass_balance(parcel, rp)
    assert balance["closes"] is True, balance
    assert balance["inputs"]["gw_recovered"] > 0  # shortfall pumped
    assert balance["outputs"]["recharge"] == Decimal("0")  # no over-delivery
    row = ParcelLedger.objects.get(parcel=parcel, source_type="calculated")
    assert row.amount_acre_feet < 0  # groundwater usage, stored negative
    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    assert run.residual_disposition == "groundwater"


def test_basin_parcel_mass_balance_closes_with_pooled_recharge():
    """Basin / flood-MAR (no well, ample delivery, in a GSA zone): closes, and the
    incidental recharge routes to the GSA basin POOL with NO personal credit
    (ISS-053)."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-BASIN")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    zone, ParcelZone = _pool_zone("basin-pool")
    ParcelZone.objects.create(parcel=parcel, zone=zone)
    pod = _pod_serving(parcel, volume_af=100, rp=rp)  # >> cap -> AMPLE

    _two_pass_refresh([pod], rp)

    balance = parcel_mass_balance(parcel, rp)
    assert balance["closes"] is True, balance
    assert balance["inputs"]["gw_recovered"] == Decimal("0")
    assert balance["outputs"]["recharge"] > 0
    # ISS-053: the over-delivery recharge pooled to the GSA basin, NOT a personal
    # credit; the parcel keeps no positive recharge ledger row it could not pump.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge", amount_acre_feet__gt=0).exists()
    pool = AllocationCarryover.objects.filter(
        zone=zone, origin="incidental_recharge_pool")
    assert pool.exists() and pool.first().amount_af > 0
    # And no phantom groundwater row (no well to pump it).
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated").exists()
