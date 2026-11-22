# SPDX-License-Identifier: AGPL-3.0-or-later
"""The carry-over command waits while a month of the year waits for OpenET (ruling 220).

rollover_allocations stops while a month of the source water year waits for OpenET and the year
is not finalized: nothing is written, and it names the months and how many use areas wait. With
--anyway it writes as today and says what it left out. --dry-run writes nothing, so it does not
stop; it prints the waiting lines and the figures. A finalized year (one finalized anyway among
them, ruling 214) rolls over exactly as today. Ruling 222 approved the words: Finalize's approved words
(ruling 215) with the action swapped (rows draft 5).

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

# wording approved: ruling 222 (rows draft 5: Finalize's approved words, ruling 215, with the action swapped)
S1 = (
    "Nothing was written. Some use areas have a month of this water year waiting for OpenET. "
    "The carry-over can be written once OpenET sends those months."
)
R2_SEPTEMBER = "September 2026: WAIT-1 and WAIT-2."
S3 = (
    "--anyway writes the carry-over now. The months listed are left out of the figures. "
    "Their meter readings still count against the groundwater allocation."
)
W1 = (
    "Some use areas have a month of this water year waiting for OpenET. The months listed are left "
    "out of the figures. Their meter readings still count against the groundwater allocation."
)
H1 = "Write the carry-over while a month waits for OpenET. The waiting month is left out of the figures."
H2 = (
    "OpenH2O does not write the carry-over while a month of the water year is waiting for OpenET. "
    "The --anyway option writes it anyway. The waiting month is then left out of the figures."
)
WAITING_WORDS = ("waiting for OpenET", "Nothing was written.", "left out of the figures", "--anyway")


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


def test_the_stop_prints_alone_with_the_months_and_the_way_on(budgeted):
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(SystemExit):
        call_command("rollover_allocations", "--water-year", "2026", stdout=out, stderr=err)
    assert _lines(err.getvalue()) == [S1, R2_SEPTEMBER, S3]
    assert "is not finalized" not in out.getvalue() + err.getvalue()


# -- (b) --anyway writes as today and says what it left out ----------------------------------------


def test_anyway_writes_the_carry_over_and_says_what_it_left_out(budgeted):
    out, _err = _rollover(anyway=True)
    assert _next_year_rows() == (1, 1)
    lines = _lines(out)
    assert "is not finalized" in lines[0]
    assert lines[1:3] == [W1, R2_SEPTEMBER]
    assert lines[-1].startswith("Wrote the carry-over")


def test_the_anyway_option_says_what_it_costs_in_the_commands_help():
    parser = Command().create_parser("manage.py", "rollover_allocations")
    assert H1 in " ".join(parser.format_help().split())


# -- (c) a dry run while a month waits does not stop and writes nothing ----------------------------


def test_a_dry_run_while_a_month_waits_prints_the_lines_and_the_figures_and_writes_nothing(budgeted):
    out, _err = _rollover(dry_run=True)
    assert _next_year_rows() == (0, 0)
    lines = _lines(out)
    assert "is not finalized" in lines[0]
    assert lines[1:3] == [W1, R2_SEPTEMBER]
    assert lines[-1].startswith("Nothing was written (dry run).")


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
    assert "is not finalized" in lines[0]
    assert lines[-1].startswith("Wrote the carry-over")


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
    assert "is not finalized" not in out


# -- (f) the help page's Carry-over row ------------------------------------------------------------


def test_the_help_pages_carry_over_row_says_the_command_waits(client):
    client = Client()
    client.force_login(User.objects.create_user(
        username="help-reader", email="help-reader@example.org", password="a-good-passw0rd", agency_admin=True
    ))
    response = client.get(reverse("budgets_allocations"))
    assert response.status_code == 200
    text = " ".join(re.sub(r"<[^>]+>", " ", response.content.decode()).split()).replace("&rsquo;", "’")
    assert "Surface water is not carried forward. " + H2 in text  # at the end of the row
    assert "rollover_allocations command stops" not in text
