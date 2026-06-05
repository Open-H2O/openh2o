# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit-trail proof on a representative Merced parcel (Phase 53-02, the v1.9/v1.10
closing gate).

The credibility claim the demo is handed to the Water Data Consortium on is "every
number traces to its SOURCE and its FORMULA." The pieces of that claim are already
proven, but split across the suite and — for the formula/provenance half — only on
SYNTHETIC parcels:

  * ``test_calculation_run.py::test_run_reconstructs_the_billable_value`` walks the
    persisted ``breakdown`` waterfall (gross ET → precip → surface → clamp → final),
    but on a synthetic ``RUN-RECON`` parcel.
  * ``test_calculation_run.py::test_run_carries_methodology_provenance`` proves the
    ``config_hash`` + ``methodology_plan_name`` fingerprint, but on synthetic
    ``RUN-PROV``.
  * ``test_merced_balance_closure.py`` exercises the four dispositions on
    ``MER-APN-*`` parcels through the two-pass sequence, but asserts CLOSURE and
    ``residual_disposition`` — it never inspects the breakdown waterfall or the
    provenance fingerprint.

So no single test ties the gross→net waterfall replay AND the methodology
fingerprint together on a representative ``MER-APN-`` parcel that went through the
``refresh_merced_accounting`` two-pass sequence. That conjunction IS the audit-trail
guarantee. This test closes exactly that gap and nothing more.

It uses the CONJUNCTIVE archetype (well + short surface delivery), because that is
the disposition that mints a ``calculated`` groundwater row carrying a full
gross→net→surface→clamp breakdown — the richest waterfall to trace.

Reproducibility note: the live demo's audit layer is rebuilt by
``refresh_merced_accounting`` (run_calculations --force → seed_merced_ledgers →
run_calculations --force), NOT by ``make merced`` / ``seed_merced`` (which own only
the spatial substrate). This test mirrors that command's three steps hermetically,
the same way ``test_merced_balance_closure._two_pass_refresh`` does.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import CalculationPlan, CalculationRun, ReportingPeriod
from accounting.services import et_mm_to_acre_feet
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

PERIOD = "2024-01"  # inside the default ReportingPeriodFactory water year
Q = Decimal("0.0001")


# --- hermetic builders (mirror test_merced_balance_closure.py) --------------

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


def _pod_serving(parcel, *, volume_af, rp):
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp,
        month=dt.date(int(PERIOD[:4]), int(PERIOD[5:7]), 1),
        volume_acre_feet=Decimal(str(volume_af)))
    return pod


def _setup_period():
    rp = ReportingPeriodFactory(is_finalized=False)
    SiteConfig.objects.create(
        agency_name="Merced Subbasin GSA",
        default_irrigation_efficiency=Decimal("0.750"))
    call_command("seed_calculation_plan")
    return rp


def _two_pass_refresh(pods, rp):
    """The same sequence refresh_merced_accounting runs, scoped to the test:
    run_calculations -> allocate_district_delivery per POD -> run_calculations."""
    call_command("run_calculations", "--period", PERIOD)
    for pod in pods:
        allocate_district_delivery(pod, rp)
    call_command("run_calculations", "--period", PERIOD)


def test_merced_calculated_run_traces_to_source_and_formula():
    """A MER-APN- conjunctive parcel's CalculationRun, after the two-pass refresh,
    is fully traceable: its breakdown replays the gross→net→surface→clamp waterfall
    (formula) AND it carries the methodology fingerprint (provenance / source of the
    recipe). One parcel, both halves of the audit-trail claim — the conjunction the
    split coverage never asserts together on Merced data."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-016")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    _well(parcel)
    pod = _pod_serving(parcel, volume_af=2, rp=rp)  # short delivery -> conjunctive

    _two_pass_refresh([pod], rp)

    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    calc = ParcelLedger.objects.get(parcel=parcel, source_type="calculated")

    # --- SOURCE / provenance: the run names the recipe that made it ---------
    plan = CalculationPlan.active()
    assert run.config_hash and len(run.config_hash) == 12
    assert run.methodology_plan_name == plan.name
    assert run.methodology_plan_id == plan.id
    assert run.residual_disposition == "groundwater"  # a real pumped term

    # --- FORMULA: the breakdown replays the gross→net waterfall verbatim -----
    # gross ET is the et_gross step's output, at the ledger's 4dp.
    et_step = next(s for s in run.breakdown if s["step_type"] == "et_gross")
    assert run.gross_et_af == Decimal(et_step["output_af"]).quantize(Q)
    expected_gross = abs(et_mm_to_acre_feet(Decimal("140.0"), Decimal("40")))
    assert run.gross_et_af == expected_gross.quantize(Q)

    # The waterfall is internally consistent: each step consumes the prior
    # step's output — no hidden jumps between gross ET and the final bill.
    for prev, nxt in zip(run.breakdown, run.breakdown[1:]):
        assert nxt["input_af"] == prev["output_af"]

    # net consumptive use = gross ET − effective precip (the source-agnostic
    # spine), and the precip step actually ran on this parcel.
    assert run.effective_precip_af is not None
    assert run.net_consumptive_use_af == (
        run.gross_et_af - run.effective_precip_af
    ).quantize(Q)
    assert run.net_consumptive_use_af > 0

    # The final billable magnitude reconstructs the calculated groundwater row.
    assert run.final_af == -calc.amount_acre_feet
    assert calc.amount_acre_feet < 0  # groundwater usage, stored negative
