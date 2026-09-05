# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the multi-period accounting refresh.

The property under test is not "does it run 24 months" — a month count is easy
to get right and would pass even if the command had been split into two
invocations. It is that **``seed_merced_ledgers`` runs exactly ONCE** across
both water years.

That command self-flushes and rebuilds every row it owns, across every period.
So a second invocation aimed at the open water year would run pass 2 again and
destroy the closed year's supply rows — and a wiped ledger reads on screen as an
empty year, not as an error. Nothing else in the suite would catch it, which is
why the call count is asserted directly rather than inferred from the result.
"""

import datetime as dt
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounting.models import ReportingPeriod

CLOSED_YEAR = "WY 2024-2025"
OPEN_YEAR = "WY 2025-2026"

# Patch the name as the command module bound it, not as Django exports it.
CALL_COMMAND = (
    "accounting.management.commands.refresh_merced_accounting.call_command"
)


@pytest.fixture
def both_water_years(db):
    ReportingPeriod.objects.create(
        name=CLOSED_YEAR,
        start_date=dt.date(2024, 10, 1),
        end_date=dt.date(2025, 9, 30),
        is_finalized=True,
    )
    ReportingPeriod.objects.create(
        name=OPEN_YEAR,
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )


def _calls(mocked):
    """(command_name, kwargs) for every call_command the refresh made."""
    return [(call.args[0], call.kwargs) for call in mocked.call_args_list]


@pytest.mark.django_db
def test_both_water_years_run_around_a_single_ledger_pass(both_water_years):
    with mock.patch(CALL_COMMAND) as mocked:
        call_command(
            "refresh_merced_accounting", period=[CLOSED_YEAR, OPEN_YEAR]
        )

    calls = _calls(mocked)
    ledger_calls = [name for name, _ in calls if name == "seed_merced_ledgers"]
    assert len(ledger_calls) == 1, (
        "seed_merced_ledgers self-flushes every row it owns — running it twice "
        "would wipe the closed year's supply rows"
    )

    engine_months = [
        kwargs["period"] for name, kwargs in calls if name == "run_calculations"
    ]
    # Two passes over the union: 24 distinct months, run once each side.
    assert len(set(engine_months)) == 24
    assert len(engine_months) == 48
    assert min(engine_months) == "2024-10"
    assert max(engine_months) == "2026-09"

    # And the ledger pass sits BETWEEN the two engine passes, not before or
    # after both — that ordering is the whole reason the command exists.
    names = [name for name, _ in calls]
    ledger_index = names.index("seed_merced_ledgers")
    assert set(names[:ledger_index]) == {"run_calculations"}
    assert set(names[ledger_index + 1 :]) == {"run_calculations"}


@pytest.mark.django_db
def test_the_single_period_default_is_unchanged(both_water_years):
    """Every existing caller passes one period, or none. Both still work."""
    with mock.patch(CALL_COMMAND) as mocked:
        call_command("refresh_merced_accounting")

    months = {
        kwargs["period"]
        for name, kwargs in _calls(mocked)
        if name == "run_calculations"
    }
    assert len(months) == 12
    assert min(months) == "2024-10"
    assert max(months) == "2025-09"


@pytest.mark.django_db
def test_a_bare_string_period_still_works(both_water_years):
    """``call_command(period="X")`` bypasses argparse and hands back a string."""
    with mock.patch(CALL_COMMAND) as mocked:
        call_command("refresh_merced_accounting", period=OPEN_YEAR)

    months = {
        kwargs["period"]
        for name, kwargs in _calls(mocked)
        if name == "run_calculations"
    }
    assert len(months) == 12
    assert min(months) == "2025-10"
    assert max(months) == "2026-09"


@pytest.mark.django_db
def test_an_unknown_period_is_refused_before_anything_runs(both_water_years):
    """Naming one real and one missing period writes nothing at all."""
    with mock.patch(CALL_COMMAND) as mocked:
        with pytest.raises(CommandError, match="WY 1999-2000"):
            call_command(
                "refresh_merced_accounting",
                period=[CLOSED_YEAR, "WY 1999-2000"],
            )
    assert mocked.call_args_list == []


@pytest.mark.django_db
def test_dry_run_reports_the_union_and_one_ledger_step(both_water_years, capsys):
    call_command(
        "refresh_merced_accounting",
        period=[CLOSED_YEAR, OPEN_YEAR],
        dry_run=True,
    )
    out = capsys.readouterr().out

    assert "24 months" in out
    assert "2024-10..2026-09" in out
    assert out.count("seed_merced_ledgers") == 1
