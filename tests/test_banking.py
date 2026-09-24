# SPDX-License-Identifier: AGPL-3.0-or-later
"""DB-bound tests for the retired rain bank (148-02).

Before 148-02, `run_calculations` deposited a wet-month's genuine rain surplus
as a `precip_surplus`-origin WaterCredit and drew it back down in a later
deficit month. 148-02 retires that: a below-floor month's rain surplus is
still computed and recorded on the run (`clamp_floor`'s detail carries it as
`rain_surplus_af`), but it is information about the month, not a credit: no
WaterCredit is deposited and none is drawn, for any origin. What
`_resolve_leftover` still does is CLEAR whatever a pre-148-02 run of the
engine wrote for a parcel-period, so a re-run on a database an older engine
banked into removes its stale WaterCredit / WaterCreditDraw rows.

The over-delivery (surface water beyond what the field's efficiency lets the
crop use) story is Task 3's, not this task's: Q1 (an over-delivery is
nobody's credit) retires the personal recharge row AND the basin-pool deposit
ISS-052/053 used to write, so test_surface_overdelivery_pools_recharge_not_a_watercredit
is retargeted there to prove neither is written any more and the amount lands
only on `CalculationRun.over_delivery_af`.

Runs in the web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import (
    AllocationCarryover,
    CalculationPlan,
    CalculationRun,
    CalculationStep,
    WaterCredit,
    WaterCreditDraw,
)
from accounting.services import INCIDENTAL_RECHARGE_POOL, et_mm_to_acre_feet
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


def _incidental_pool_total(zone):
    return sum(
        (
            r.amount_af
            for r in AllocationCarryover.objects.filter(
                zone=zone, origin=INCIDENTAL_RECHARGE_POOL
            )
        ),
        Decimal("0"),
    )


def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(parcel_number=number, area_acres=Decimal(acres))


def _irrigate(parcel):
    """Give the parcel a crop so facility_only_zero does NOT zero it out."""
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _et_cache(parcel, period="2024-06", et_mm=100.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )


def _precip_cache(parcel, period, precip_mm):
    """A GRIDMET precip cache row in the live shape (value keyed "precip")."""
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="precip",
        model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}],
    )


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
    surplus), and the seeded clamp_floor (148-02: floor only, no bank lever)."""
    call_command("seed_calculation_plan")
    CalculationStep.objects.filter(
        plan=CalculationPlan.active(), step_type="subtract_effective_precip"
    ).update(config={"method": "raw"})


# --------------------------------------------------------------------------
# Deposit: nothing is ever banked
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_surface_overdelivery_pools_recharge_not_a_watercredit():
    """148-02 Task 3 (Q1, an over-delivery is nobody's credit): surface delivered
    beyond what the field's own efficiency lets the crop use is neither a
    bankable precip WaterCredit NOR a recharge credit of any kind — personal or
    pooled. The amount is recorded only on the run, as `over_delivery_af`.

    RETARGETED from the pre-Task-3 expectation that a no-well parcel's
    over-delivery deposited to the GSA basin pool (ISS-052/053): that pool
    deposit is gone too, not just the personal row. `EFF` is the agency-wide
    default `field_efficiency` falls back to when no SiteConfig row exists
    (surface/services.py); the 5 AF delivered here only lets the crop use
    5 x EFF = 3.75 AF, so the over-delivery is smaller than the pre-Task-1
    ~1.72 AF figure (delivered minus ET) this test used to assert."""
    parcel = _parcel("BANK-DEP", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=100.0)  # ~3.28 AF gross
    _irrigate(parcel)  # crop, no well -> FLOOD_MAR -> pool
    zone = _zone_for(parcel)
    _surface_row(parcel, "2024-02", af=5)  # 5 AF delivered > 3.28 AF ET
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02")

    # Nothing banked — the over-delivery is not a conservation credit.
    assert WaterCredit.objects.filter(parcel=parcel).count() == 0
    # No personal recharge ledger row (the ISS-053 phantom is gone).
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge"
    ).exists()
    # No pooled recharge either — Q1 retires that deposit too.
    assert _incidental_pool_total(zone) == Decimal("0")
    # The amount is recorded on the run instead.
    EFF = Decimal("0.750")
    consumed = (Decimal("5") * EFF).quantize(Q)
    over_delivery = (consumed - _gross_af()).quantize(Q)
    assert over_delivery > 0, "fixture must produce a real over-delivery"
    run = CalculationRun.objects.get(parcel=parcel, period="2024-02")
    assert run.over_delivery_af == over_delivery
    # 54-01: a no-well parcel gets NO `calculated` groundwater row — over-delivered,
    # so the run records unmet demand of 0 (the residual was fully covered).
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated"
    ).exists()

    run = CalculationRun.objects.get(parcel=parcel, period="2024-02")
    assert run.residual_disposition == "unmet_demand"
    assert run.unmet_demand_af == Decimal("0.0000")


@pytest.mark.django_db
def test_normal_extraction_month_banks_nothing():
    parcel = _parcel("BANK-NONE", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)  # ET present, no surface water -> positive net, no surplus
    WellIrrigatedParcelFactory(parcel=parcel)  # 54-01: banking is well-gated
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    assert WaterCredit.objects.filter(parcel=parcel).count() == 0
    assert _calc_row(parcel, "2024-06").amount_acre_feet < 0


@pytest.mark.django_db
def test_below_floor_rain_month_deposits_nothing_and_records_rain_surplus_af():
    """148-02: a below-floor month driven by genuine rain (Pe > ET, method=raw)
    deposits NO WaterCredit (the rain bank is retired), but the rain figure is
    still computed and recorded on the run as `rain_surplus_af`. Acreage 30.48
    (area_acres is a 2-decimal-place field, so it must round-trip exactly) and
    mm inputs divisible by 25.4 are chosen so every conversion in the chain
    (mm -> AF, mm -> in -> mm) is an EXACT decimal, so the expected value below
    is a literal, not a recomputation of the chain's own arithmetic."""
    parcel = _parcel("BANK-RAIN", acres="30.48")
    _et_cache(parcel, period="2024-02", et_mm=100.0)  # -> 10.0000 AF gross ET
    _precip_cache(parcel, period="2024-02", precip_mm=254.0)  # -> 25.4000 AF rain
    _irrigate(parcel)  # crop, well: banking (if it existed) would be well-gated
    WellIrrigatedParcelFactory(parcel=parcel)
    _raw_precip_plan()

    call_command("run_calculations", "--period", "2024-02")

    assert WaterCredit.objects.count() == 0
    assert WaterCreditDraw.objects.count() == 0

    run = _run(parcel, "2024-02")
    assert run.banked_af == Decimal("0.0000")
    clamp = next(s for s in run.breakdown if s["step_type"] == "clamp_floor")
    detail = clamp["detail"]
    assert "bank" not in detail
    assert "depreciation_rate" not in detail
    assert "expiry_months" not in detail
    # No surface delivery this month, so the WHOLE below-floor amount is rain,
    # none of it incidental (surface) recharge: 25.4 rain - 10.0 ET = 15.4.
    assert Decimal(detail["rain_surplus_af"]) == Decimal("15.4")
    assert Decimal(detail["incidental_recharge_af"]) == Decimal("0")
    assert Decimal(detail["surplus_af"]) == Decimal("15.4")


@pytest.mark.django_db
def test_dry_run_writes_no_credits_or_draws():
    parcel = _parcel("BANK-DRY", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=100.0)
    _irrigate(parcel)
    _surface_row(parcel, "2024-02", af=5)  # over-delivery, never a credit anyway
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02", "--dry-run")

    assert WaterCredit.objects.count() == 0
    assert WaterCreditDraw.objects.count() == 0
    # And no calculated ledger row was written either.
    assert not ParcelLedger.objects.filter(source_type="calculated").exists()


# --------------------------------------------------------------------------
# Draw: nothing is ever drawn, even against a pre-existing (legacy) credit
# --------------------------------------------------------------------------


def _seed_prior_credit(parcel, amount, rate, origin="2024-01", expires=None):
    return WaterCredit.objects.create(
        parcel=parcel,
        origin_period=origin,
        amount_af=Decimal(amount),
        origin="precip_surplus",
        depreciation_rate=Decimal(rate),
        expires_period=expires,
    )


@pytest.mark.django_db
def test_deficit_month_draws_nothing_and_bills_in_full_even_with_a_legacy_credit():
    """A pre-148-02 database can carry a real, still-live precip_surplus
    WaterCredit from an earlier period. The retired engine never draws it: the
    deficit bills in full (no draw folded in), and the untouched older-period
    credit is left exactly as it was (only THIS period's own WaterCredit /
    WaterCreditDraw rows are ever cleared, per _resolve_leftover)."""
    parcel = _parcel("BANK-NODRAW", acres="10")
    _et_cache(parcel, period="2024-03", et_mm=100.0)  # ~3.28 AF deficit
    _irrigate(parcel)
    WellIrrigatedParcelFactory(parcel=parcel)
    credit = _seed_prior_credit(parcel, amount="2", rate="0.10", origin="2024-01")
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-03")

    assert WaterCreditDraw.objects.filter(credit__parcel=parcel).count() == 0
    # Billed at the FULL gross ET: nothing came off it.
    assert _calc_row(parcel, "2024-03").amount_acre_feet == (-_gross_af()).quantize(Q)
    run = _run(parcel, "2024-03")
    assert run.drawn_af == Decimal("0.0000")
    assert run.final_af == _gross_af().quantize(Q)
    # The older-period credit is untouched; it belongs to 2024-01, not this run.
    assert WaterCredit.objects.filter(pk=credit.pk).exists()


@pytest.mark.django_db
def test_rerun_removes_a_legacy_precip_surplus_credit_and_its_draw_for_that_period():
    """A database an older engine wrote can carry, for the SAME period being
    re-run, both a `precip_surplus` WaterCredit it deposited and a
    WaterCreditDraw against some other credit it drew in that period.
    148-02: `_resolve_leftover` clears both on commit, so a re-run leaves no
    stale rain-bank rows behind."""
    parcel = _parcel("BANK-LEGACY", acres="10")
    _et_cache(parcel, period="2024-04", et_mm=100.0)
    _irrigate(parcel)
    WellIrrigatedParcelFactory(parcel=parcel)
    call_command("seed_calculation_plan")

    # As if a pre-148-02 run had deposited a credit THIS period and drawn one
    # down THIS period too (against some other, older credit).
    legacy_deposit = WaterCredit.objects.create(
        parcel=parcel,
        origin_period="2024-04",
        amount_af=Decimal("1.5000"),
        origin="precip_surplus",
    )
    older_credit = WaterCredit.objects.create(
        parcel=parcel,
        origin_period="2024-01",
        amount_af=Decimal("2.0000"),
        origin="precip_surplus",
    )
    legacy_draw = WaterCreditDraw.objects.create(
        credit=older_credit, draw_period="2024-04", amount_af=Decimal("1.0000")
    )

    call_command("run_calculations", "--period", "2024-04")

    # This period's own deposit and this period's own draw are both gone.
    assert not WaterCredit.objects.filter(pk=legacy_deposit.pk).exists()
    assert not WaterCreditDraw.objects.filter(pk=legacy_draw.pk).exists()
    # The older credit itself (origin_period 2024-01, a different period) is
    # not this period's deposit, so it is left alone.
    assert WaterCredit.objects.filter(pk=older_credit.pk).exists()
    # And the re-run drew nothing new in its place.
    assert WaterCreditDraw.objects.filter(credit__parcel=parcel).count() == 0
