# SPDX-License-Identifier: AGPL-3.0-or-later
"""148-04 Task 2: the engine follows `SiteConfig.over_delivery_treatment` (Q1).

Three values, Brent's ruling (2026-09-20): (a) "not_credited" — today's
148-02 behaviour, nothing written beyond the run's own `over_delivery_af`;
(b) "credited" — a has-well field's share becomes a personal `recharge` row
(ISS-053 routing), a no-well field's share joins its zone's shared basin
pool, and `over_delivery_leave_behind` stays in the basin either way; (c)
"named_line" — the engine writes nothing (the amount is shown elsewhere,
never here), identical to (a) on the engine side.

Every scenario shares one fixture: a 10-acre field, ET 10.0000 AF (et_mm
304.8 so the conversion is exact), a 20 AF canal delivery, and the agency's
own `default_irrigation_efficiency` set to 0.700 so the crop's consumed
share (20 x 0.700 = 14.0000 AF) is 4.0000 AF beyond the 10.0000 AF ET — the
plan's own hand numbers (ET 10.0000, over 4.0000, share 0.100 -> 3.6000
credited, 0.4000 left in the basin). Every assertion below is a VALUE
against that hand arithmetic, never a re-derivation of the formula under
test. Fixtures and helpers are reused from tests.test_calculation_run and
tests.test_basin_pool (the same building blocks those two files already
use for the same engine), not reinvented.

Runs in the web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounting.ledger_words import INCIDENTAL_RECHARGE_WORDS, over_delivery_credit_words
from accounting.models import CalculationRun, ReportingPeriod
from accounting.services import (
    INCIDENTAL_RECHARGE_POOL,
    _balance_dict,
    billable_ledger,
    deposit_to_basin_pool,
    parcel_mass_balance,
)
from accounting.carryover_math import water_year_of
from core.models import SiteConfig
from parcels.models import ParcelLedger
from tests.factories import WellIrrigatedParcelFactory
from tests.test_calculation_run import (
    _et_cache,
    _gross_af,
    _incidental_pool_total,
    _irrigate,
    _parcel,
    _run,
    _surface_row,
    _zone_for,
)

Q = Decimal("0.0001")
PERIOD = "2024-02"

# The fixture's hand numbers (plan 148-04 Task 2): ET 10.0000, over 4.0000,
# share 0.100 -> 3.6000 credited, 0.4000 left in the basin.
ACRES = "10"
ET_MM = 304.8  # -> exactly 10.0000 AF over 10 acres (et_mm_to_acre_feet)
DELIVERED = Decimal("20")  # AF, x 0.700 efficiency = 14.0000 consumed
EFFICIENCY = Decimal("0.700")
GROSS_ET = Decimal("10.0000")
OVER = Decimal("4.0000")
SHARE = Decimal("0.100")
CREDITED = Decimal("3.6000")
LEFT_BEHIND = Decimal("0.4000")


def _config(**kwargs):
    """Get-or-create the one SiteConfig row and set `kwargs` on it (only one
    row is ever allowed; this is the update path a test that switches the
    setting mid-scenario needs)."""
    config = SiteConfig.objects.first()
    if config is None:
        config = SiteConfig.objects.create(
            agency_name="148-04 Test Agency",
            default_irrigation_efficiency=EFFICIENCY,
            **kwargs,
        )
    else:
        config.default_irrigation_efficiency = EFFICIENCY
        for key, value in kwargs.items():
            setattr(config, key, value)
        config.save()
    return config


def _fixture(number, *, well):
    """A 10-acre irrigated parcel with the hand-number ET + surface delivery,
    optionally with a well (CONJUNCTIVE) or not (FLOOD_MAR)."""
    parcel = _parcel(number, acres=ACRES)
    _irrigate(parcel)
    if well:
        WellIrrigatedParcelFactory(parcel=parcel)
    zone = _zone_for(parcel)
    _et_cache(parcel, period=PERIOD, et_mm=ET_MM)
    _surface_row(parcel, PERIOD, af=DELIVERED)
    return parcel, zone


def _supply(parcel):
    return _balance_dict(
        billable_ledger(ParcelLedger.objects.filter(parcel=parcel))
    )["supply"]


def _recharge_rows(parcel):
    return list(
        ParcelLedger.objects.filter(
            parcel=parcel, source_type="recharge"
        ).order_by("id")
    )


def _state(parcel, zone):
    """A snapshot of everything the setting can move, for round-trip checks."""
    run = _run(parcel, PERIOD)
    return {
        "treatment": run.over_delivery_treatment,
        "leave_behind": run.over_delivery_leave_behind,
        "credited_af": run.over_delivery_credited_af,
        "pooled": run.over_delivery_credit_pooled,
        "recharge_amounts": [
            r.amount_acre_feet for r in _recharge_rows(parcel)
        ],
        "pool_total": _incidental_pool_total(zone),
    }


# --------------------------------------------------------------------------
# The fixture itself produces the hand numbers.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_fixture_produces_the_hand_numbers():
    parcel, _zone = _fixture("OD-FIXTURE", well=True)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="not_credited")

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.gross_et_af == GROSS_ET
    assert run.over_delivery_af == OVER
    assert _gross_af(et_mm=str(ET_MM), acres=ACRES).quantize(Q) == GROSS_ET


# --------------------------------------------------------------------------
# (a) not_credited — nothing written, stamped plainly.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_not_credited_writes_no_row_no_pool_stamps_treatment():
    parcel, zone = _fixture("OD-A", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="not_credited")

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_leave_behind is None
    assert run.over_delivery_credited_af is None
    assert run.over_delivery_credit_pooled is False
    assert not _recharge_rows(parcel)
    assert _incidental_pool_total(zone) == Decimal("0")


@pytest.mark.django_db
def test_a_is_the_default_with_no_site_config_row_at_all():
    """No SiteConfig row exists (the `SiteConfig.objects.first() or
    SiteConfig()` fallback) -- reads as "not_credited", exactly like an
    explicit (a)."""
    parcel, zone = _fixture("OD-A-NOROW", well=True)
    call_command("seed_calculation_plan")
    assert not SiteConfig.objects.exists()

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_credited_af is None
    assert not _recharge_rows(parcel)


# --------------------------------------------------------------------------
# (b) credited — has-well: a personal row; no-well: the zone's shared pool.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_b_has_well_writes_one_credited_row_with_the_words():
    parcel, zone = _fixture("OD-B-WELL", well=True)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)
    supply_a = _supply(parcel)

    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "credited"
    assert run.over_delivery_leave_behind == SHARE
    assert run.over_delivery_credited_af == CREDITED
    assert run.over_delivery_credit_pooled is False

    rows = _recharge_rows(parcel)
    assert len(rows) == 1
    assert rows[0].amount_acre_feet == CREDITED
    assert rows[0].description == over_delivery_credit_words(SHARE)
    assert rows[0].description.startswith(INCIDENTAL_RECHARGE_WORDS)
    assert rows[0].description == (
        f"{INCIDENTAL_RECHARGE_WORDS}, 90% credited and 10% left in the basin"
    )

    # The budget's remaining supply is up by EXACTLY the credited amount —
    # nothing else about the month's numbers moved.
    assert (_supply(parcel) - supply_a).quantize(Q) == CREDITED
    # A has-well field never feeds the pool.
    assert _incidental_pool_total(zone) == Decimal("0")


@pytest.mark.django_db
def test_b_no_well_pools_and_writes_no_personal_row():
    parcel, zone = _fixture("OD-B-NOWELL", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "credited"
    assert run.over_delivery_leave_behind == SHARE
    assert run.over_delivery_credited_af == CREDITED
    assert run.over_delivery_credit_pooled is True
    assert not _recharge_rows(parcel)
    assert _incidental_pool_total(zone) == CREDITED


@pytest.mark.django_db
def test_b_no_well_no_zone_credits_nothing():
    """No management-area zone to hold a no-well field's share: credited
    stays null, nothing is written anywhere, even though the setting is
    "credited" and there was a real over-delivery."""
    parcel = _parcel("OD-B-NOZONE", acres=ACRES)
    _irrigate(parcel)
    _et_cache(parcel, period=PERIOD, et_mm=ET_MM)
    _surface_row(parcel, PERIOD, af=DELIVERED)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "credited"
    assert run.over_delivery_leave_behind == SHARE
    assert run.over_delivery_credited_af is None
    assert run.over_delivery_credit_pooled is False
    assert not _recharge_rows(parcel)


# --------------------------------------------------------------------------
# (c) named_line — the engine writes nothing, same as (a).
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_c_named_line_writes_nothing_stamps_treatment():
    parcel, zone = _fixture("OD-C", well=True)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="named_line")

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "named_line"
    assert run.over_delivery_leave_behind is None
    assert run.over_delivery_credited_af is None
    assert run.over_delivery_credit_pooled is False
    assert not _recharge_rows(parcel)
    assert _incidental_pool_total(zone) == Decimal("0")
    # The whole-month figure is still on the run, for the field page to read.
    assert run.over_delivery_af == OVER


# --------------------------------------------------------------------------
# Re-run / switch safety.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_b_rerun_twice_leaves_one_row_and_the_pool_unchanged():
    parcel, zone = _fixture("OD-B-RERUN", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)

    call_command("run_calculations", "--period", PERIOD)
    call_command("run_calculations", "--period", PERIOD)

    assert CalculationRun.objects.filter(parcel=parcel, period=PERIOD).count() == 1
    assert _incidental_pool_total(zone) == CREDITED


@pytest.mark.django_db
def test_switch_b_to_a_removes_the_row_and_zeroes_the_pool():
    parcel, zone = _fixture("OD-BA", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)
    assert _incidental_pool_total(zone) == CREDITED

    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_credited_af is None
    assert not _recharge_rows(parcel)
    assert _incidental_pool_total(zone) == Decimal("0")
    # A row left standing at exactly 0 would be a phantom for the pool's
    # readers to explain — it must be gone, not merely zeroed.
    from accounting.models import AllocationCarryover

    assert not AllocationCarryover.objects.filter(
        zone=zone, origin=INCIDENTAL_RECHARGE_POOL
    ).exists()


@pytest.mark.django_db
def test_a_b_c_b_a_ends_where_it_started():
    parcel, zone = _fixture("OD-ABCBA", well=False)
    call_command("seed_calculation_plan")

    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)
    start = _state(parcel, zone)

    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)
    assert _state(parcel, zone) != start  # sanity: (b) really did move something

    _config(over_delivery_treatment="named_line")
    call_command("run_calculations", "--period", PERIOD)

    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)

    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)
    end = _state(parcel, zone)

    assert end == start


@pytest.mark.django_db
def test_no_well_field_that_gains_a_well_between_two_b_runs():
    parcel, zone = _fixture("OD-GAINSWELL", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)

    call_command("run_calculations", "--period", PERIOD)
    assert _incidental_pool_total(zone) == CREDITED
    assert not _recharge_rows(parcel)

    WellIrrigatedParcelFactory(parcel=parcel)  # gains a well -> CONJUNCTIVE
    call_command("run_calculations", "--period", PERIOD)

    assert _incidental_pool_total(zone) == Decimal("0")
    rows = _recharge_rows(parcel)
    assert len(rows) == 1
    assert rows[0].amount_acre_feet == CREDITED


@pytest.mark.django_db
def test_pre_148_02_prior_pool_deposit_under_b_nets_once_not_twice():
    """A legacy (pre-148-02) run left `incidental_recharge_af=5.4000` in its
    breakdown (no `over_delivery_af` key) and a matching 5.4000 AF pool
    deposit made outside this engine, as `test_no_well_incidental_pool_is_
    idempotent_across_reruns` also simulates it. A fresh (b) run must net a
    SINGLE delta against that legacy amount — the pool ends at 3.6000 (this
    fixture's own hand-computed credited share), NOT
    3.6000 - 5.4000 + 5.4000 (which would mean the one-time reversal and the
    new deposit both landed, doubling up)."""
    parcel, zone = _fixture("OD-LEGACY", well=False)
    call_command("seed_calculation_plan")

    from accounting.models import WaterType

    gw, _ = WaterType.objects.get_or_create(
        code="GW", defaults={"name": "Groundwater"}
    )
    legacy_incidental = Decimal("5.4000")
    CalculationRun.objects.create(
        parcel=parcel,
        period=PERIOD,
        gross_et_af=GROSS_ET,
        net_consumptive_use_af=Decimal("0"),
        final_af=Decimal("0"),
        breakdown=[
            {
                "step_type": "clamp_floor",
                "detail": {"incidental_recharge_af": str(legacy_incidental)},
            }
        ],
    )
    deposit_to_basin_pool(
        zone, gw, water_year_of(PERIOD), legacy_incidental,
        origin=INCIDENTAL_RECHARGE_POOL,
    )
    assert _incidental_pool_total(zone) == legacy_incidental

    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)

    assert _incidental_pool_total(zone) == CREDITED
    run = _run(parcel, PERIOD)
    assert run.over_delivery_credited_af == CREDITED
    assert run.over_delivery_credit_pooled is True


@pytest.mark.django_db
def test_switching_the_setting_without_a_rerun_moves_nothing():
    parcel, zone = _fixture("OD-NOTOUCH", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)
    before = _state(parcel, zone)

    _config(over_delivery_treatment="not_credited")  # setting changed, NOT re-run

    after = _state(parcel, zone)
    assert after == before


@pytest.mark.django_db
def test_finalized_period_refuses_without_force_under_credited_too():
    parcel, _zone = _fixture("OD-FINAL", well=True)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    year, month = int(PERIOD[:4]), int(PERIOD[5:7])
    ReportingPeriod.objects.create(
        name="WY2024 Feb",
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        is_finalized=True,
    )

    with pytest.raises(CommandError, match="finalized"):
        call_command("run_calculations", "--period", PERIOD)
    assert not CalculationRun.objects.filter(parcel=parcel, period=PERIOD).exists()

    call_command("run_calculations", "--period", PERIOD, "--force")
    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "credited"
    assert run.over_delivery_credited_af == CREDITED


# --------------------------------------------------------------------------
# Mass balance: the physical residual never moves with the credit policy.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mass_balance_residual_identical_under_a_b_c_for_has_well_field():
    parcel, _zone = _fixture("OD-MB", well=True)
    call_command("seed_calculation_plan")

    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)
    balance_a = parcel_mass_balance(parcel)
    assert balance_a["outputs"]["recharge"] == Decimal("0")

    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)
    balance_b = parcel_mass_balance(parcel)
    # A real `recharge` row now exists (the credited row), but the mass
    # balance's `recharge` output still excludes it by prefix.
    assert _recharge_rows(parcel)
    assert balance_b["outputs"]["recharge"] == Decimal("0")

    _config(over_delivery_treatment="named_line")
    call_command("run_calculations", "--period", PERIOD)
    balance_c = parcel_mass_balance(parcel)
    assert balance_c["outputs"]["recharge"] == Decimal("0")

    assert balance_a["residual_af"] == balance_b["residual_af"] == balance_c["residual_af"]
    assert balance_a["inputs_total"] == balance_b["inputs_total"] == balance_c["inputs_total"]
    assert balance_a["outputs_total"] == balance_b["outputs_total"] == balance_c["outputs_total"]


# --------------------------------------------------------------------------
# ledger_words.over_delivery_credit_words — the sentence itself.
# --------------------------------------------------------------------------


def test_over_delivery_credit_words_matches_the_hand_example():
    words = over_delivery_credit_words(SHARE)
    assert words == (
        f"{INCIDENTAL_RECHARGE_WORDS}, 90% credited and 10% left in the basin"
    )
    assert words.startswith(INCIDENTAL_RECHARGE_WORDS)


def test_over_delivery_credit_words_scans_clean_under_the_domain_gate():
    from tests.test_domain_vocabulary import scan

    offences = scan(over_delivery_credit_words(SHARE))
    assert offences == [], offences
