# SPDX-License-Identifier: AGPL-3.0-or-later
"""The carry-over command waits while a month of the year waits for OpenET (ruling 220).

rollover_allocations stops while a month of the source water year waits for OpenET and the year
is not finalized: nothing is written, and it names the months and how many use areas wait. With
--anyway it writes as today and says what it left out. --dry-run writes nothing, so it does not
stop; it prints the waiting lines and the figures. A finalized year (one finalized anyway among
them, ruling 214) rolls over exactly as today. Ruling 221 approved the words (rows R1 to R7); the
month lines are ruling 215's row A2.

The site is ``tests/test_waiting_for_openet.py``'s: WY 2025-2026 read on October 3, 2026, WAIT-1
and WAIT-2 in OpenET fields with no crop ET for September 2026, WAIT-4 in no field, and a zone
with a groundwater allocation over WAIT-1 and WAIT-2.
"""
import io
import re
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounting import finalize
from accounting.management.commands.rollover_allocations import Command
from accounting.models import AccountCredit, AllocationCarryover
from core.models import User
from datasync import crop_et
from datasync.models import OpenETFieldMonth, OpenETFieldShare
from tests.test_waiting_for_openet import (  # noqa: F401  (world is a fixture, used by name)
    ET_MM,
    SEP,
    _budgeted_account,
    _run_year,
    world,
)

pytestmark = pytest.mark.django_db

# wording approved: ruling 221 (rows R1 to R7); the month line is ruling 215 row A2
R1 = "Stopped. Nothing was written. 2 use areas are waiting for OpenET in WY 2025-2026."
R2_SEPTEMBER = "September 2026: WAIT-1 and WAIT-2."
R3 = (
    "To wait, run the command again once OpenET sends these months. To write the carry-over now, "
    "run it again with --anyway. Use areas with no meter then have no pumping counted for these "
    "months. Their remainders carry over too high. A later run after OpenET sends the months "
    "replaces the figures."
)
R4 = (
    "Writing the carry-over while 2 use areas are waiting for OpenET in WY 2025-2026. Use areas "
    "with no meter have no pumping counted for the months listed below. A later run after OpenET "
    "sends the months replaces the figures."
)
R5_FIRST = "Dry run. 2 use areas are waiting for OpenET in WY 2025-2026."
R5_REST = (
    "A run without --dry-run stops here. The figures below count no pumping for these months on "
    "use areas with no meter."
)
R6 = (
    "Write the carry-over while months wait for OpenET. Use areas with no meter then have no "
    "pumping counted for those months."
)
R7 = (
    "The rollover_allocations command stops while a month of the year waits for OpenET. It lists "
    "the months. Its --anyway option writes the carry-over now. Use areas with no meter then have "
    "no pumping counted for those months."
)
WAITING_WORDS = ("waiting for OpenET", "Stopped.", "Dry run.", "--anyway")


def _rollover(**options):
    out, err = io.StringIO(), io.StringIO()
    call_command("rollover_allocations", "--water-year", "2026", stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def _lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def _next_year_rows():
    return (
        AllocationCarryover.objects.filter(water_year=2027, origin="allocation_carryover").count(),
        AccountCredit.objects.filter(water_year=2027, origin="carried_forward").count(),
    )


@pytest.fixture
def budgeted(world):
    _budgeted_account(world)
    _run_year(world)
    return world


# -- (a) a month waits and the year is open: it stops and writes nothing ---------------------------


def test_while_september_waits_the_command_stops_names_the_month_and_writes_nothing(budgeted):
    with pytest.raises(SystemExit) as stopped:
        _rollover()
    assert stopped.value.code == 1
    assert _next_year_rows() == (0, 0)


def test_the_stop_prints_alone_with_the_count_the_month_and_both_ways_forward(budgeted):
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(SystemExit):
        call_command("rollover_allocations", "--water-year", "2026", stdout=out, stderr=err)
    assert _lines(err.getvalue()) == [R1, R2_SEPTEMBER, R3]
    assert "PROVISIONAL" not in out.getvalue() + err.getvalue()


# -- (b) --anyway writes as today and says what it left out ----------------------------------------


def test_anyway_writes_the_carry_over_and_says_what_it_left_out(budgeted):
    out, _err = _rollover(anyway=True)
    assert _next_year_rows() == (1, 1)
    lines = _lines(out)
    assert "PROVISIONAL" in lines[0]
    assert lines[1:3] == [R4, R2_SEPTEMBER]
    assert lines[-1].startswith("Wrote 1 carry-over row(s)")


def test_the_anyway_option_says_what_it_costs_in_the_commands_help():
    parser = Command().create_parser("manage.py", "rollover_allocations")
    assert R6 in " ".join(parser.format_help().split())


# -- (c) a dry run while a month waits does not stop and writes nothing ----------------------------


def test_a_dry_run_while_a_month_waits_prints_the_lines_and_the_figures_and_writes_nothing(budgeted):
    out, _err = _rollover(dry_run=True)
    assert _next_year_rows() == (0, 0)
    lines = _lines(out)
    assert "PROVISIONAL" in lines[0]
    assert lines[1:4] == [R5_FIRST, R2_SEPTEMBER, R5_REST]
    assert lines[-1].startswith("Would write 1 carry-over row(s)")


# -- (d) nothing waiting: as today -----------------------------------------------------------------


def test_with_nothing_waiting_the_command_writes_as_today_with_no_waiting_words(budgeted):
    for parcel in (budgeted.u1, budgeted.u2):
        field = OpenETFieldShare.objects.get(parcel=parcel).field
        OpenETFieldMonth.objects.create(
            field=field, month=SEP, et_mm=ET_MM, pr_mm=Decimal("0"), received_on=date(2026, 10, 2)
        )
        crop_et.record_received_months(parcel, [crop_et.month_text(SEP)])
    _run_year(budgeted)

    out, err = _rollover()

    assert _next_year_rows() == (1, 1)
    assert err == ""
    assert not any(words in out for words in WAITING_WORDS)
    lines = _lines(out)
    assert "PROVISIONAL" in lines[0]
    assert lines[-1].startswith("Wrote 1 carry-over row(s)")


# -- (e) a year finalized anyway rolls over as today -----------------------------------------------


def test_a_year_finalized_anyway_rolls_over_as_today(budgeted):
    closer = User.objects.create_user(
        username="closer", email="closer@example.org", password="a-good-passw0rd", agency_admin=True
    )
    found = finalize.waiting(budgeted.period)
    assert found["use_areas"] == 2
    finalize.finalize_year(budgeted.period, closer, finalize.note_for(found))

    out, err = _rollover()

    assert _next_year_rows() == (1, 1)
    assert err == ""
    assert not any(words in out for words in WAITING_WORDS)
    assert "PROVISIONAL" not in out


# -- (f) the help page's Carry-over row ------------------------------------------------------------


def test_the_help_pages_carry_over_row_says_the_command_waits(client):
    client = Client()
    client.force_login(User.objects.create_user(
        username="help-reader", email="help-reader@example.org", password="a-good-passw0rd", agency_admin=True
    ))
    response = client.get(reverse("budgets_allocations"))
    assert response.status_code == 200
    text = " ".join(re.sub(r"<[^>]+>", " ", response.content.decode()).split()).replace("&rsquo;", "’")
    assert R7 in text
