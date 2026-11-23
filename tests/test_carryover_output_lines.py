# SPDX-License-Identifier: AGPL-3.0-or-later
"""The carry-over command's output lines, in wording the maintainer approved on 2026-11-22.

What the lines must get right, checked against the database rather than the printed words:
the closing line's counts are the zone rows and account rows a real run writes; a dry run's
counts are what the real run then writes; every year is named the way the screens name it
(``water_year_label``: "WY 2025-2026"), never "WY2026" or "water year 2026"; no line holds an
em dash. Then the approved lines themselves, word for word.

Two sites: ``tests/test_waiting_for_openet.py``'s (one zone over WAIT-1 and WAIT-2 and one
account holding both, WY 2025-2026 open, September waiting for OpenET, so a real run needs
--anyway), and ``tests/test_rollover_recovery_horizon.py``'s bare zones in a finalized
WY 2023-2024, for a surplus that expires and a remainder of exactly zero.
"""
import io
import re
from decimal import Decimal

import pytest
from django.core.management import call_command

from accounting.models import AccountCredit, AllocationCarryover
from tests.test_rollover_recovery_horizon import gw_type, make_zone, rollover, wy_period
from tests.test_waiting_for_openet import (  # noqa: F401  (world is a fixture, used by name)
    _budgeted_account,
    _run_year,
    world,
)

pytestmark = pytest.mark.django_db

COUNTS = re.compile(r"(\d+) zone rows? and (\d+) account rows?")


def _rollover(**options):
    out, err = io.StringIO(), io.StringIO()
    call_command("rollover_allocations", "--water-year", "2026", stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def _lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def _rows_written(next_year):
    return (
        AllocationCarryover.objects.filter(water_year=next_year, origin="allocation_carryover").count(),
        AccountCredit.objects.filter(water_year=next_year, origin="carried_forward").count(),
    )


def _counts(line):
    found = COUNTS.search(line)
    assert found, line
    return int(found.group(1)), int(found.group(2))


@pytest.fixture
def budgeted(world):
    world.account = _budgeted_account(world)
    _run_year(world)
    return world


# -- (a) the closing line counts the rows a real run writes ----------------------------------------


def test_the_closing_line_counts_the_zone_rows_and_the_account_rows_the_run_wrote(budgeted):
    out, _err = _rollover(anyway=True)
    assert _counts(_lines(out)[-1]) == _rows_written(2027) == (1, 1)


def test_the_closing_line_counts_only_the_rows_written_when_a_surplus_expires():
    gw = gw_type()
    period = wy_period()
    make_zone(gw, period, alloc=100, usage=30)
    make_zone(gw, period, alloc=100, usage=30, recovery_horizon="same_water_year")
    out = io.StringIO()
    rollover(stdout=out)
    assert _counts(_lines(out.getvalue())[-1]) == _rows_written(2025) == (1, 0)


# -- (b) a dry run's counts are what the real run then writes ---------------------------------------


def test_a_dry_runs_counts_equal_what_the_real_run_then_writes(budgeted):
    dry, _err = _rollover(dry_run=True)
    assert _rows_written(2027) == (0, 0)
    _rollover(anyway=True)
    assert _counts(_lines(dry)[-1]) == _rows_written(2027)


# -- (c) one name for the year ---------------------------------------------------------------------


@pytest.mark.parametrize("options", [{"dry_run": True}, {"anyway": True}])
def test_every_line_names_the_year_the_way_the_screens_do(budgeted, options):
    out, err = _rollover(**options)
    text = out + err
    assert not re.search(r"WY\d{4}", text)
    assert not re.search(r"water year \d{4}", text, re.IGNORECASE)
    assert "WY 2025-2026" in _lines(out)[0]
    assert "from WY 2025-2026 into WY 2026-2027" in _lines(out)[-1]


# -- (d) no em dash --------------------------------------------------------------------------------


def test_no_output_line_holds_an_em_dash():
    gw = gw_type()
    period = wy_period()
    make_zone(gw, period, alloc=100, usage=30, recovery_horizon="same_water_year")
    make_zone(gw, period, alloc=100, usage=130)
    out = io.StringIO()
    rollover(stdout=out)
    assert "—" not in out.getvalue()


# -- (e) the approved lines, word for word ---------------------------------------------------------


# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.
def test_an_open_year_says_its_carry_over_is_provisional(budgeted):
    out, _err = _rollover(dry_run=True)
    assert _lines(out)[0] == (
        "WY 2025-2026 is not finalized, so this carry-over is provisional. Running the command again "
        "later replaces it, using the meter readings, OpenET's crop ET and corrections then on file."
    )


# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.
def test_the_closing_lines_of_a_dry_run_and_a_real_run(budgeted):
    dry, _err = _rollover(dry_run=True)
    assert _lines(dry)[-1] == (
        "Nothing was written (dry run). A real run would write the carry-over from WY 2025-2026 into "
        "WY 2026-2027: 1 zone row and 1 account row."
    )
    real, _err = _rollover(anyway=True)
    assert _lines(real)[-1] == (
        "Wrote the carry-over from WY 2025-2026 into WY 2026-2027: 1 zone row and 1 account row, "
        "after deleting any rows an earlier run wrote for WY 2026-2027."
    )


# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.
def test_the_zone_line_and_the_account_line_state_their_sum(budgeted):
    out, _err = _rollover(anyway=True)
    zone_row = AllocationCarryover.objects.get(water_year=2027, origin="allocation_carryover")
    credit = AccountCredit.objects.get(water_year=2027, origin="carried_forward")
    kind = {1: "a surplus", -1: "a debt"}
    zone_used = Decimal("50.0000") - zone_row.amount_af
    assert (
        f"Zone Waiting GSA Zone: allocation 50.0000 + added 0.0000 - used {zone_used} = remaining "
        f"{zone_row.amount_af} AF, {kind[(zone_row.amount_af > 0) - (zone_row.amount_af < 0)]} "
        "carried into WY 2026-2027."
    ) in _lines(out)
    account_line = next(line for line in _lines(out) if line.startswith("Account "))
    assert re.fullmatch(
        rf"Account {re.escape(budgeted.account.account_number)}: allocation \d+\.\d{{4}} \+ credits "
        rf"0\.0000 - used \d+\.\d{{4}} = remaining {re.escape(str(credit.amount_af))} AF, "
        rf"{kind[(credit.amount_af > 0) - (credit.amount_af < 0)]} carried into WY 2026-2027\.",
        account_line,
    )


# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.
def test_a_surplus_that_expires_says_so_and_the_closing_line_counts_it():
    gw = gw_type()
    period = wy_period()
    zone = make_zone(gw, period, alloc=100, usage=30, recovery_horizon="same_water_year")
    out = io.StringIO()
    rollover(stdout=out)
    lines = _lines(out.getvalue())
    assert (
        f"Zone {zone.name}: allocation 100.0000 + added 0.0000 - used 30.0000 = remaining 70.0000 AF, "
        "a surplus that expires and is not carried into WY 2024-2025."
    ) in lines
    assert lines[-1] == (
        "Wrote the carry-over from WY 2023-2024 into WY 2024-2025: 0 zone rows and 0 account rows, "
        "after deleting any rows an earlier run wrote for WY 2024-2025. 1 surplus expired and was not carried."
    )


# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.
def test_a_remainder_of_exactly_zero_is_neither_surplus_nor_debt():
    gw = gw_type()
    period = wy_period()
    zone = make_zone(gw, period, alloc=100, usage=100)
    out = io.StringIO()
    rollover(stdout=out)
    assert (
        f"Zone {zone.name}: allocation 100.0000 + added 0.0000 - used 100.0000 = remaining 0.0000 AF, "
        "neither surplus nor debt; 0.0000 AF is carried into WY 2024-2025."
    ) in _lines(out.getvalue())
