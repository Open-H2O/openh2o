# SPDX-License-Identifier: AGPL-3.0-or-later
"""DB-bound tests for WaterCredit banking ORCHESTRATION (38-04).

The pure depreciation/expiry math is proven Django-free in
tests/test_banking_math.py; this file proves run_calculations' banking flow: a
wet-month surplus is deposited as one WaterCredit, a later deficit draws available
non-expired credits oldest-first (depreciated) and folds the draw into the single
`calculated` row, expiry is respected, and re-runs / dry-runs never double-bank,
double-draw, or write phantom rows.

A bankable surplus requires the chain to net BELOW the floor. The usda_scs
effective-precip step caps its credit at ET, so netting alone bottoms out at 0;
the surplus in these tests therefore comes from surface-water delivery exceeding
net ET. Runs in the Butler web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.banking_math import depreciated_value
from accounting.models import WaterCredit, WaterCreditDraw
from accounting.services import et_mm_to_acre_feet
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation

Q = Decimal("0.0001")


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


# --------------------------------------------------------------------------
# Deposit
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_surplus_month_banks_one_watercredit():
    """Surface water exceeds gross ET -> chain nets below 0 -> banks the surplus."""
    parcel = _parcel("BANK-DEP", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=100.0)  # ~3.28 AF gross
    _irrigate(parcel)
    _surface_row(parcel, "2024-02", af=5)  # 5 AF delivered > 3.28 AF ET
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02")

    credits = WaterCredit.objects.filter(parcel=parcel)
    assert credits.count() == 1
    credit = credits.first()
    assert credit.origin == "precip_surplus"
    assert credit.origin_period == "2024-02"
    expected_surplus = (Decimal("5") - _gross_af()).quantize(Q)
    assert credit.amount_af == expected_surplus
    # The billable row is clamped to 0 (the surplus went to the bank, not the bill).
    assert _calc_row(parcel, "2024-02").amount_acre_feet == Decimal("0.0000")


@pytest.mark.django_db
def test_normal_extraction_month_banks_nothing():
    parcel = _parcel("BANK-NONE", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=100.0)
    _irrigate(parcel)  # ET present, no surface water -> positive net, no surplus
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-06")

    assert WaterCredit.objects.filter(parcel=parcel).count() == 0
    assert _calc_row(parcel, "2024-06").amount_acre_feet < 0


# --------------------------------------------------------------------------
# Draw (with depreciation)
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
def test_deficit_month_draws_depreciated_credit_and_reduces_bill():
    parcel = _parcel("BANK-DRAW", acres="10")
    _et_cache(parcel, period="2024-03", et_mm=100.0)  # ~3.28 AF deficit
    _irrigate(parcel)
    # Credit 2 AF @ 10%/mo from 2024-01; two months later it is worth 2*0.81=1.62.
    _seed_prior_credit(parcel, amount="2", rate="0.10", origin="2024-01")
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-03")

    draws = WaterCreditDraw.objects.filter(credit__parcel=parcel)
    assert draws.count() == 1
    drawn = depreciated_value(Decimal("2"), Decimal("0.10"), 2).quantize(Q)
    assert drawn == Decimal("1.6200")  # depreciation visibly shrank the 2 AF
    assert draws.first().amount_af == drawn
    assert draws.first().draw_period == "2024-03"
    # Bill reduced by the drawn amount (not zeroed — the credit was too small).
    net = _gross_af() - drawn
    assert _calc_row(parcel, "2024-03").amount_acre_feet == (-net).quantize(Q)


@pytest.mark.django_db
def test_expired_credit_is_not_drawn_and_deficit_bills_in_full():
    parcel = _parcel("BANK-EXP", acres="10")
    _et_cache(parcel, period="2024-03", et_mm=100.0)
    _irrigate(parcel)
    # Expires 2024-02, which is <= the 2024-03 draw period -> dead.
    _seed_prior_credit(parcel, amount="5", rate="0", origin="2024-01", expires="2024-02")
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-03")

    assert WaterCreditDraw.objects.filter(credit__parcel=parcel).count() == 0
    assert _calc_row(parcel, "2024-03").amount_acre_feet == (-_gross_af()).quantize(Q)


@pytest.mark.django_db
def test_oldest_credit_is_consumed_first():
    parcel = _parcel("BANK-FIFO", acres="10")
    _et_cache(parcel, period="2024-03", et_mm=100.0)  # ~3.28 AF deficit
    _irrigate(parcel)
    older = _seed_prior_credit(parcel, amount="5", rate="0", origin="2024-01")
    newer = _seed_prior_credit(parcel, amount="5", rate="0", origin="2024-02")
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-03")

    # The 3.28 AF deficit is fully covered by the older 5 AF credit; newer untouched.
    assert older.draws.count() == 1
    assert newer.draws.count() == 0
    assert older.draws.first().amount_af == _gross_af().quantize(Q)
    assert _calc_row(parcel, "2024-03").amount_acre_feet == Decimal("0.0000")


# --------------------------------------------------------------------------
# Idempotency + dry-run
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_rerunning_a_deficit_period_is_identical_no_drift():
    parcel = _parcel("BANK-IDEM", acres="10")
    _et_cache(parcel, period="2024-03", et_mm=100.0)
    _irrigate(parcel)
    _seed_prior_credit(parcel, amount="2", rate="0.10", origin="2024-01")
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-03")
    draws1 = list(
        WaterCreditDraw.objects.filter(credit__parcel=parcel)
        .order_by("id")
        .values_list("draw_period", "amount_af")
    )
    calc1 = _calc_row(parcel, "2024-03").amount_acre_feet

    call_command("run_calculations", "--period", "2024-03")  # second run
    draws2 = list(
        WaterCreditDraw.objects.filter(credit__parcel=parcel)
        .order_by("id")
        .values_list("draw_period", "amount_af")
    )
    calc2 = _calc_row(parcel, "2024-03").amount_acre_feet

    # Exactly one draw, identical amount, identical bill — no double-draw, no drift.
    assert len(draws1) == 1
    assert draws1 == draws2
    assert calc1 == calc2
    assert WaterCreditDraw.objects.filter(credit__parcel=parcel).count() == 1


@pytest.mark.django_db
def test_dry_run_writes_no_credits_or_draws():
    parcel = _parcel("BANK-DRY", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=100.0)
    _irrigate(parcel)
    _surface_row(parcel, "2024-02", af=5)  # would bank a surplus
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", "2024-02", "--dry-run")

    assert WaterCredit.objects.count() == 0
    assert WaterCreditDraw.objects.count() == 0
    # And no calculated ledger row was written either.
    assert not ParcelLedger.objects.filter(source_type="calculated").exists()
