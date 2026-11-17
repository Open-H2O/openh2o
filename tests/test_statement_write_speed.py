# SPDX-License-Identifier: AGPL-3.0-or-later
"""The filed figures are written with the foreign keys checked as each insert ends.

Django makes foreign keys ``DEFERRABLE INITIALLY DEFERRED``, so each statement row's two
checks waited in Postgres' deferred-trigger queue until the commit, and every caught
error in the row's triggers (they read ``pgtrigger.ignore``, which is unset) made
Postgres rescan that queue. At 433,228 rows the write took 482.5 s, growing with every
row; with ``SET CONSTRAINTS ALL IMMEDIATE`` first it took 20.5 s and kept every history
row. The time is measured at real size, not here: these tests hold the cause shut.
"""
import math

import pytest
from django.apps import apps
from django.db import connection

from accounting.models import PeriodStatementRow, ReportingPeriod
from accounting.statements import collect_figures, take_statement
from tests import year_reading_world as world

pytestmark = pytest.mark.django_db


@pytest.fixture
def year():
    world.build_world()
    return ReportingPeriod.objects.get(name=world.WY25)


def _statements_sent(year):
    sent = []

    def capture(execute, sql, params, many, context):
        sent.append(" ".join(sql.split()))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(capture):
        statement = take_statement(year, kind="filed")
    return statement, sent


def test_the_foreign_keys_are_checked_as_each_insert_ends(year):
    _, sent = _statements_sent(year)
    inserts = [i for i, sql in enumerate(sent) if "INSERT INTO \"accounting_periodstatementrow\"" in sql]
    immediate = [i for i, sql in enumerate(sent) if sql.upper() == "SET CONSTRAINTS ALL IMMEDIATE"]
    assert inserts, "the statement wrote no rows"
    assert immediate and immediate[0] < inserts[0]


def test_the_write_sends_one_insert_a_batch_of_500(year):
    figures = len(collect_figures(year))
    _, sent = _statements_sent(year)
    inserts = [sql for sql in sent if "INSERT INTO \"accounting_periodstatementrow\"" in sql]
    assert len(inserts) == math.ceil(figures / 500)


def test_every_figure_keeps_its_one_history_row(year):
    statement, _ = _statements_sent(year)
    rows = PeriodStatementRow.objects.filter(statement=statement).count()
    events = apps.get_model("accounting", "PeriodStatementRowEvent").objects.filter(
        statement=statement.pk, pgh_label="insert")
    assert rows == len(collect_figures(year))
    assert events.count() == rows
