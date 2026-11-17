# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine follows `SiteConfig.over_delivery_treatment`.

Two values are offered: "not_credited" (the default) and "named_line". Both
write nothing beyond the run's own `over_delivery_af`; the amount is shown
elsewhere, never by the engine.

Every scenario shares one fixture: a 10-acre field, ET 10.0000 AF (et_mm
304.8 so the conversion is exact), a 20 AF canal delivery, and the agency's
own `default_irrigation_efficiency` set to 0.700 so the crop's consumed
share (20 x 0.700 = 14.0000 AF) is 4.0000 AF beyond the 10.0000 AF ET — the
plan's own hand numbers (ET 10.0000, over 4.0000). Every assertion below is a VALUE
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

from accounting.models import CalculationRun, ReportingPeriod
from accounting.services import (
    _balance_dict,
    parcel_mass_balance,
)
from core.models import SiteConfig
from parcels.models import ParcelLedger
from tests.factories import WellIrrigatedParcelFactory
from tests.test_calculation_run import (
    _et_cache,
    _gross_af,
    _irrigate,
    _parcel,
    _run,
    _surface_row,
    _zone_for,
)

Q = Decimal("0.0001")
PERIOD = "2024-02"

# The fixture's hand numbers (plan 148-04 Task 2): ET 10.0000, over 4.0000.
ACRES = "10"
ET_MM = 304.8  # -> exactly 10.0000 AF over 10 acres (et_mm_to_acre_feet)
DELIVERED = Decimal("20")  # AF, x 0.700 efficiency = 14.0000 consumed
EFFICIENCY = Decimal("0.700")
GROSS_ET = Decimal("10.0000")
OVER = Decimal("4.0000")


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
        ParcelLedger.objects.filter(parcel=parcel).current()
    )["supply"]


def _recharge_rows(parcel):
    return list(
        ParcelLedger.objects.filter(
            parcel=parcel, source_type="recharge"
        ).order_by("id")
    )


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
    assert not _recharge_rows(parcel)


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
    assert not _recharge_rows(parcel)
    # The whole-month figure is still on the run, for the field page to read.
    assert run.over_delivery_af == OVER


@pytest.mark.django_db
def test_finalized_period_refuses_without_force_():
    parcel, _zone = _fixture("OD-FINAL", well=True)
    call_command("seed_calculation_plan")
    _config(over_delivery_treatment="not_credited")
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


# --------------------------------------------------------------------------
# Mass balance: the physical residual never moves with the credit policy.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mass_balance_residual_identical_under_every_setting_for_has_well_field():
    parcel, _zone = _fixture("OD-MB", well=True)
    call_command("seed_calculation_plan")

    balances = []
    for treatment in ("not_credited", "named_line"):
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
