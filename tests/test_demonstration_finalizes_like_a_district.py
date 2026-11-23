# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demonstration's closed water year is finalized the way a district finalizes one (153.9-02).

The load creates WY 2024-2025 open, runs the steps, forgets the change history once, and then
calls ``accounting.finalize.finalize_year`` on it from the command line (no user, no note). The
year therefore holds a ``filed`` statement, a code with no upgrade marker, and the change
history the finalize wrote, and the removal leaves no change history behind. Facts only: a
state, a kind, a count, a name.
"""
import datetime as dt
import inspect
import re

import pytest
from django.core.management import get_commands
from django.db import connection

from accounting import fingerprints
from accounting.models import (
    PeriodStatement,
    PeriodStatementRowEvent,
    ReportingPeriod,
    ReportingPeriodEvent,
)

# The fixtures and helpers of the fingerprint tests: a signed-in administrator, the Check route.
from tests.test_fingerprint_04 import (  # noqa: F401  (fixtures are used by name)
    HX,
    _check_url,
    _client,
    _quiet,
    administrator,
)

pytestmark = pytest.mark.django_db

YEAR = "WY 2024-2025"


def _small_year_open(stdout=None):
    from core import demonstration as demo
    from core.models import SiteConfig
    from tests import factories as f

    f.BoundaryFactory(name=demo.DEMONSTRATION_BOUNDARY)
    SiteConfig.objects.create(agency_name=demo.DEMONSTRATION_NAME)
    ReportingPeriod.objects.create(name=YEAR, start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30))
    f.ParcelLedgerFactory(effective_date=dt.date(2025, 3, 1), transaction_date=dt.date(2025, 3, 1))


@pytest.fixture
def loaded(monkeypatch):
    from core import demonstration as demo

    monkeypatch.setattr(demo, "run_steps", _small_year_open)
    demo.load()
    return ReportingPeriod.objects.get(name=YEAR)


@pytest.fixture
def open_year():
    from tests import factories as f

    year = ReportingPeriod.objects.create(name=YEAR, start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30))
    f.ParcelLedgerFactory(effective_date=dt.date(2025, 3, 1), transaction_date=dt.date(2025, 3, 1))
    return year


# -- the load ------------------------------------------------------------------------------------


def test_the_load_leaves_the_year_finalized_from_the_command_line(loaded):
    assert loaded.is_finalized is True
    assert loaded.finalized_at is not None
    assert loaded.finalized_by is None


def test_the_load_writes_one_filed_statement_with_rows_and_no_words(loaded):
    statement = PeriodStatement.objects.get(period=loaded)
    assert statement.kind == "filed"
    assert statement.taken_by is None
    assert statement.note == ""
    assert statement.rows.exists()


def test_the_code_carries_no_upgrade_marker_and_no_first_code(loaded):
    assert loaded.fingerprint
    assert "at_upgrade" not in loaded.fingerprint_parts
    assert "first" not in loaded.fingerprint_parts


def test_check_matches_right_after_the_load_through_the_function_and_the_route(loaded, administrator):
    assert fingerprints.check_fingerprint(loaded).state == "matches"
    response = _client(administrator).post(_check_url(loaded), **HX)
    assert response.status_code == 200
    assert response.context["answer"].state == "matches"


def test_the_year_keeps_the_change_history_the_finalize_wrote(loaded):
    assert ReportingPeriodEvent.objects.filter(pgh_obj_id=loaded.pk).exists()
    row_ids = list(PeriodStatement.objects.get(period=loaded).rows.values_list("pk", flat=True))
    assert PeriodStatementRowEvent.objects.filter(pgh_obj_id__in=row_ids).exists()


def test_load_then_remove_leaves_every_change_history_table_as_it_was(monkeypatch):
    """Guards the build: the finalize's history is kept by the load and is gone after the removal."""
    from core import demonstration as demo
    from core.management.commands.clear_change_history import _event_tables

    tables = _event_tables() + ["pghistory_context"]

    def counts():
        found = {}
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f'SELECT count(*) FROM "{table}"')
                found[table] = cursor.fetchone()[0]
        return found

    before = counts()
    monkeypatch.setattr(demo, "run_steps", _small_year_open)
    demo.load()
    demo.remove()
    assert counts() == before


# -- what the build removes ----------------------------------------------------------------------


def test_the_upgrade_kind_of_statement_is_gone():
    assert "recorded_at_upgrade" not in [value for value, _ in PeriodStatement.KIND_CHOICES]


def test_the_two_upgrade_commands_are_gone():
    commands = get_commands()
    assert "record_filed_figures" not in commands
    assert "record_fingerprints" not in commands


def test_take_fingerprint_has_no_upgrade_parameter():
    assert "at_upgrade" not in inspect.signature(fingerprints.take_fingerprint).parameters


def test_the_upgrade_step_is_not_a_demonstration_step():
    from core import demonstration as demo

    assert "record_filed_figures" not in [name for name, _ in demo.STEPS]


# -- finalize_year -------------------------------------------------------------------------------


def test_finalize_year_finalizes_an_open_year_once(open_year):
    from accounting import finalize

    assert finalize.finalize_year(open_year, None)["outcome"] == "finalized"
    open_year.refresh_from_db()
    assert open_year.is_finalized is True
    assert open_year.finalized_at is not None
    assert list(PeriodStatement.objects.filter(period=open_year).values_list("kind", flat=True)) == ["filed"]

    assert finalize.finalize_year(open_year, None)["outcome"] == "already"
    assert PeriodStatement.objects.filter(period=open_year).count() == 1


# -- the whole demonstration: nothing waits for OpenET (153.1-02) ----------------------


@pytest.mark.release
def test_the_whole_demonstration_has_no_month_holding_finalize_back(monkeypatch, administrator):
    import io

    from django.core.management import call_command
    from django.test import Client
    from django.urls import reverse

    from accounting import finalize
    from datasync import crop_et

    monkeypatch.setattr(crop_et, "today", lambda: dt.date(2026, 11, 21), raising=False)
    call_command("load_demonstration", stdout=io.StringIO())

    closed = ReportingPeriod.objects.get(name="WY 2024-2025")
    open_year = ReportingPeriod.objects.get(name="WY 2025-2026")
    assert closed.is_finalized is True
    assert finalize.waiting(closed)["months"] == []
    assert finalize.waiting(open_year)["months"] == []
    client = Client()
    client.force_login(administrator)
    page = client.get(reverse("accounting:period_detail", args=[open_year.pk])).content.decode()
    assert re.search(r"<button[^>]*>\s*Finalize water year\s*</button>", page)
    assert "Finalize anyway" not in page
