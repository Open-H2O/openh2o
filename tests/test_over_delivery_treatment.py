# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine follows `SiteConfig.over_delivery_treatment`.

Two values are offered: "not_credited" (the default) and "named_line". Both
write nothing beyond the run's own `over_delivery_af`; the amount is shown
elsewhere, never by the engine. "credited" was a third value until Brent ruled
it out (nothing credits water applied beyond crop need): a site that still
holds it runs as "not credited", and a month an older version credited loses
its recharge row and its pool deposit when it is run again.

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
# A site still stored as the removed "credited" choice: nothing is credited.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_site_stored_as_credited_credits_a_has_well_field_nothing():
    parcel, zone = _fixture("OD-B-WELL", well=True)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)
    supply_a = _supply(parcel)

    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)
    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_credited_af is None
    assert run.over_delivery_credit_pooled is False
    assert run.over_delivery_af == OVER
    assert not _recharge_rows(parcel)
    assert _supply(parcel) == supply_a
    assert _incidental_pool_total(zone) == Decimal("0")


@pytest.mark.django_db
def test_a_site_stored_as_credited_pools_nothing_for_a_no_well_field():
    parcel, zone = _fixture("OD-B-NOWELL", well=False)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="credited", over_delivery_leave_behind=SHARE)

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_credited_af is None
    assert run.over_delivery_credit_pooled is False
    assert not _recharge_rows(parcel)
    assert _incidental_pool_total(zone) == Decimal("0")


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


def _older_credit(parcel, zone, *, pooled):
    """What an older version wrote for this month: a run stamped credited and its credit."""
    from accounting.models import WaterType

    gw, _ = WaterType.objects.get_or_create(code="GW", defaults={"name": "Groundwater"})
    CalculationRun.objects.create(
        parcel=parcel,
        period=PERIOD,
        gross_et_af=GROSS_ET,
        net_consumptive_use_af=Decimal("0"),
        final_af=Decimal("0"),
        over_delivery_treatment="credited",
        over_delivery_leave_behind=SHARE,
        over_delivery_credited_af=CREDITED,
        over_delivery_credit_pooled=pooled,
        breakdown=[
            {
                "step_type": "clamp_floor",
                "detail": {
                    "incidental_recharge_af": str(OVER),
                    "over_delivery_af": str(OVER),
                },
            }
        ],
    )
    if pooled:
        deposit_to_basin_pool(
            zone, gw, water_year_of(PERIOD), CREDITED, origin=INCIDENTAL_RECHARGE_POOL
        )
    else:
        ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=dt.date(2024, 3, 1),
            effective_date=dt.date(2024, 2, 1),
            amount_acre_feet=CREDITED,
            source_type="recharge",
            description=over_delivery_credit_words(SHARE),
            water_type=gw,
        )


@pytest.mark.django_db
def test_running_a_month_again_takes_back_the_pool_deposit_an_older_version_made():
    parcel, zone = _fixture("OD-RERUN-POOL", well=False)
    call_command("seed_calculation_plan")
    _older_credit(parcel, zone, pooled=True)
    assert _incidental_pool_total(zone) == CREDITED
    _config(over_delivery_treatment="not_credited")

    call_command("run_calculations", "--period", PERIOD)

    run = _run(parcel, PERIOD)
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_credited_af is None
    assert _incidental_pool_total(zone) == Decimal("0")
    from accounting.models import AllocationCarryover

    assert not AllocationCarryover.objects.filter(
        zone=zone, origin=INCIDENTAL_RECHARGE_POOL
    ).exists()


@pytest.mark.django_db
def test_running_a_month_again_removes_the_recharge_row_an_older_version_wrote():
    parcel, zone = _fixture("OD-RERUN-ROW", well=True)
    call_command("seed_calculation_plan")
    _older_credit(parcel, zone, pooled=False)
    assert len(_recharge_rows(parcel)) == 1
    _config(over_delivery_treatment="not_credited")

    call_command("run_calculations", "--period", PERIOD)

    assert not _recharge_rows(parcel)
    assert _incidental_pool_total(zone) == Decimal("0")


@pytest.mark.django_db
def test_a_run_an_older_version_stamped_credited_stays_readable_until_it_is_run_again():
    parcel, zone = _fixture("OD-NOTOUCH", well=False)
    call_command("seed_calculation_plan")
    _older_credit(parcel, zone, pooled=True)
    before = _state(parcel, zone)

    _config(over_delivery_treatment="not_credited")  # setting changed, NOT re-run

    assert _state(parcel, zone) == before
    assert before["treatment"] == "credited"
    assert before["credited_af"] == CREDITED


@pytest.mark.django_db
def test_pre_148_02_prior_pool_deposit_is_taken_back_once_not_twice():
    """A legacy run left `incidental_recharge_af=5.4000` in its breakdown (no
    `over_delivery_af` key) and a matching 5.4000 AF pool deposit made outside
    this engine. The next run takes that deposit back exactly once: the pool
    ends at 0, not -5.4000."""
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

    _config(over_delivery_treatment="not_credited")
    call_command("run_calculations", "--period", PERIOD)
    call_command("run_calculations", "--period", PERIOD)

    assert _incidental_pool_total(zone) == Decimal("0")


@pytest.mark.django_db
def test_finalized_period_refuses_without_force_for_a_credited_site_too():
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
    assert run.over_delivery_treatment == "not_credited"
    assert run.over_delivery_credited_af is None


# --------------------------------------------------------------------------
# Mass balance: the physical residual never moves with the credit policy.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mass_balance_residual_identical_under_every_setting_for_has_well_field():
    parcel, _zone = _fixture("OD-MB", well=True)
    call_command("seed_calculation_plan")

    balances = []
    for treatment in ("not_credited", "credited", "named_line"):
        _config(over_delivery_treatment=treatment)
        call_command("run_calculations", "--period", PERIOD)
        balance = parcel_mass_balance(parcel)
        assert balance["outputs"]["recharge"] == Decimal("0")
        assert not _recharge_rows(parcel)
        balances.append(balance)

    first = balances[0]
    for other in balances[1:]:
        assert first["residual_af"] == other["residual_af"]
        assert first["inputs_total"] == other["inputs_total"]
        assert first["outputs_total"] == other["outputs_total"]


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
