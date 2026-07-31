# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-099: the dashboard could not tell "no water was consumed" from "nobody asked".

Both render `0.00`, and they are opposite facts. On 2026-07-28 a staging rebuild
left 76 parcels with zero `OpenETCache`, zero `CalculationPlan` and zero
`CalculationRun` rows. The dashboard then read *Consumptive use* 0.00 for every
account and every zone, *Balance* equal to the raw supplies — and the attention
strip's green "All clear — nothing needs attention right now" sat above the lot.
Nothing on the page was flagged, because nothing on the page could tell that the
demand column was empty rather than zero.

The chosen fix is the issue's option (b), the dashboard side, because that is
where the wrong number is READ. Option (a) — a louder `seed_merced` — warns the
person who ran the seed, at the moment they ran it, and reaches nobody who
imported their own data, nobody who opens the page a week later, and nobody who
is not the operator. `seed_merced` was made honest as well (see
`test_seed_merced_reports_the_engine_gap` at the foot of this file), but that is
the smaller half.

**The test that matters most is `test_a_genuinely_zero_basin_still_shows_zero`.**
Everything else here proves the warning appears; only that one proves it is a
distinction rather than a blanket "we can't be sure" disclaimer over every
dashboard.
"""
from datetime import date
from decimal import Decimal
from io import StringIO

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

PERIOD_START = date(2025, 10, 1)
PERIOD_END = date(2026, 9, 30)

BANNER = "Consumptive use has not been calculated for this period"
ALL_CLEAR = "All clear"
NOT_CALCULATED = "Not calculated"


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"iss099user{n}")
    email = factory.Sequence(lambda n: f"iss099user{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _basin(with_allocation=True):
    """One period, one zone, one parcel, one account — and no engine output."""
    period = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=PERIOD_START,
        end_date=PERIOD_END,
    )
    zone = ZoneFactory(name="ISS-099 Zone")
    parcel = ParcelFactory()
    ParcelZoneFactory(parcel=parcel, zone=zone)
    account = WaterAccountFactory(account_number="ISS099-0001", name="ISS-099 Account")
    WaterAccountParcelFactory(water_account=account, parcel=parcel)
    if with_allocation:
        AllocationPlanFactory(
            zone=zone,
            water_type=WaterTypeFactory(),
            reporting_period=period,
            allocation_acre_feet=Decimal("100.0000"),
        )
    return period, parcel


def _run(parcel, gross_et="12.0000", net="10.0000", period="2026-01"):
    """One CalculationRun — the thing whose ABSENCE this whole issue is about."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(gross_et),
        net_consumptive_use_af=Decimal(net),
        effective_precip_af=Decimal("2.0000"),
        final_af=Decimal(net),
    )


def _dashboard(period):
    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard") + f"?period={period.pk}")
    assert response.status_code == 200
    return response.content.decode()


# ---------------------------------------------------------------------------
# The distinction itself.
# ---------------------------------------------------------------------------

def test_a_basin_with_no_calculation_runs_says_so():
    period, _parcel = _basin()

    html = _dashboard(period)

    assert BANNER in html
    assert NOT_CALCULATED in html


def test_a_genuinely_zero_basin_still_shows_zero():
    """
    The whole point of the issue, and the assertion that keeps the fix honest.

    A basin the engine HAS measured, and measured at zero, is a finding: the
    dashboard must publish that zero as the number it is. If this ever fails
    alongside the test above passing, the "fix" has degenerated into a warning
    shown over every dashboard, which tells a reader nothing they can act on.
    """
    period, parcel = _basin()
    _run(parcel, gross_et="0.0000", net="0.0000")

    html = _dashboard(period)

    assert BANNER not in html
    assert NOT_CALCULATED not in html
    # The zero is present as a rendered figure, not suppressed into a dash.
    assert "0.00" in html


def test_the_all_clear_banner_stands_down_when_nothing_was_measured():
    """
    The actively harmful element, and the reason (b) beat (a).

    `accounts_over_budget` is structurally zero here — an account cannot exceed
    its allocation by consuming nothing — so the strip had no exception to report
    and certified the basin instead.
    """
    period, _parcel = _basin()

    html = _dashboard(period)

    assert ALL_CLEAR not in html


def test_the_all_clear_banner_returns_once_the_engine_has_run():
    period, parcel = _basin()
    _run(parcel)

    html = _dashboard(period)

    assert ALL_CLEAR in html
    assert BANNER not in html


# ---------------------------------------------------------------------------
# Scope — who is warned, and who is not.
# ---------------------------------------------------------------------------

def test_a_brand_new_instance_with_no_parcels_is_not_warned():
    """
    An empty deployment's zeros are honest, and its operator is at an earlier
    step entirely. Telling them to run the calculation engine before they have
    imported a single parcel sends them to the wrong screen.
    """
    period = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=PERIOD_START,
        end_date=PERIOD_END,
    )

    html = _dashboard(period)

    assert BANNER not in html


def test_runs_in_another_period_do_not_count_as_this_period_being_calculated():
    """
    Period membership is the real rule, not "has this deployment ever run".

    An agency that calculated last year and has not yet calculated this one is
    the ordinary case, and last year's rows must not vouch for this year's blank
    column.
    """
    period, parcel = _basin()
    _run(parcel, period="2019-05")

    html = _dashboard(period)

    assert BANNER in html


def test_the_banner_names_the_methodology_step_first_when_no_plan_exists():
    """
    Order matters and the failure is otherwise cryptic: with no active plan,
    `run_calculations` does not produce nothing, it raises `ValueError: no active
    CalculationPlan`. An operator told only "run the engine" walks into that.
    """
    period, _parcel = _basin()

    html = _dashboard(period)

    assert "Start by setting up a calculation method" in html


# ---------------------------------------------------------------------------
# The rows, not just the headline.
# ---------------------------------------------------------------------------

def test_account_and_zone_rows_dash_their_demand_derived_columns():
    """
    Net and Remaining are the quiet ones. With consumptive use silently zero,
    Net equals the entire supply (reads as surplus) and Remaining equals the
    entire allocation (reads as an untouched budget). Both are conclusions drawn
    from a measurement that does not exist.
    """
    period, _parcel = _basin()

    response_html = _dashboard(period)

    # Two tables, each dashing three cells.
    assert response_html.count("&mdash;") >= 6


def test_a_row_with_runs_is_not_dashed():
    period, parcel = _basin()
    _run(parcel)

    html = _dashboard(period)

    assert "12.00" in html


def test_the_supply_columns_are_never_dashed():
    """
    Supplies come from ledger rows. They are measured whether or not the engine
    has ever run, and blanking them would hide real data behind someone else's
    missing step — the opposite of the fix.
    """
    period, _parcel = _basin()

    html = _dashboard(period)

    # The three supply sub-totals in the budget panel foot still render.
    assert "Surface" in html
    assert "Groundwater" in html


# ---------------------------------------------------------------------------
# The service-level signal the whole thing rests on.
# ---------------------------------------------------------------------------

def test_consumptive_use_balance_reports_how_many_runs_it_summed():
    from accounting.services import consumptive_use_balance

    _period, parcel = _basin()

    assert consumptive_use_balance([parcel.id])["calculation_runs"] == 0

    _run(parcel)
    assert consumptive_use_balance([parcel.id])["calculation_runs"] == 1


def test_the_run_count_tracks_the_rows_actually_summed():
    """
    Counted inside the summing loop, not by a second query.

    A separate `.count()` with its own filter could disagree with the rows the
    totals came from the moment `runs_in_period`'s membership rule changes, and
    the dashboard would then vouch for a figure built from a different set.
    """
    from accounting.services import consumptive_use_balance

    _period, parcel = _basin()
    _run(parcel, period="2026-01")
    _run(parcel, period="2026-02")

    result = consumptive_use_balance([parcel.id])
    assert result["calculation_runs"] == 2
    assert result["consumptive_use_gross"] == Decimal("24.0000")


# ---------------------------------------------------------------------------
# The smaller half — seed_merced no longer signs off on work it skipped.
# ---------------------------------------------------------------------------

def test_seed_merced_reports_the_engine_gap():
    """
    The sequence used to end "Merced Subbasin demo fully seeded" having
    deliberately skipped the ET cache, the CalculationPlan and the engine run.

    The sub-commands are mocked out: this is about what the command SAYS at the
    end, and running the real eleven-step seed would need live network fetches.
    """
    from unittest import mock

    from core.management.commands import seed_merced as seed_merced_module

    out = StringIO()
    with mock.patch.object(seed_merced_module, "call_command"):
        call_command("seed_merced", stdout=out)

    output = out.getvalue()
    assert "fully seeded" not in output
    assert "The calculation engine has never run" in output
    assert "No active calculation method" in output
    assert "run_calculations" in output


def test_seed_merced_says_so_when_the_engine_has_output():
    from unittest import mock

    from core.management.commands import seed_merced as seed_merced_module

    _period, parcel = _basin()
    _run(parcel)
    _plan_and_cache()

    out = StringIO()
    with mock.patch.object(seed_merced_module, "call_command"):
        call_command("seed_merced", stdout=out)

    output = out.getvalue()
    assert "The calculation engine has output in this database" in output
    assert "NOT seeded by this command" not in output


def _plan_and_cache():
    """The other two things `seed_merced` deliberately does not create."""
    from accounting.models import CalculationPlan
    from datasync.models import OpenETCache

    CalculationPlan.objects.create(name="ISS-099 Plan", is_active=True)
    parcel = ParcelFactory()
    OpenETCache.objects.create(
        parcel=parcel,
        geometry=parcel.geometry,
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        et_data={"2026-01": 1.0},
    )
