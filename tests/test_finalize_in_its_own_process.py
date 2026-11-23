# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finalize water year starts its own process; the page answers at once and shows where it stands.

At 8,906 use areas finalizing held one web request for 1,217 s, and after the statement
write was fixed it still takes about 77 s, past the web server's 60-second limit. Now the
button saves a ``finalize`` pending import and starts ``run_pending_import``; that process
writes the statement, marks the year finalized and writes the fingerprint in one
transaction, under the same change-history context a request gave. The page shows the run
while it waits or runs, and the stopped words when it failed or its process is gone.
"""
import datetime
import re
from unittest.mock import patch

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import PeriodStatement, PeriodStatementRow, ReportingPeriod
from accounting.statements import collect_figures, statement_figures, take_statement
from core import pending_imports
from core.models import PendingImport
from tests import year_reading_world as world

pytestmark = pytest.mark.django_db
User = get_user_model()

RUNNING_LEAVE = "You can leave this page. When finalizing ends, the result appears here."
STOPPED = "Finalizing stopped. This water year is still open. Press Finalize water year to start again."


@pytest.fixture
def administrator():
    return User.objects.create_user(
        username="finalize-process-admin", email="finalize-process-admin@example.org",
        password="a-good-passw0rd", is_active=True, agency_admin=True)


@pytest.fixture
def client(administrator):
    c = Client()
    c.force_login(administrator)
    return c


@pytest.fixture
def year():
    world.build_world()
    return ReportingPeriod.objects.get(name=world.WY25)


def _words(response):
    text = re.sub(r"<[^>]+>", "", response.content.decode())
    return " ".join(text.split()).replace("&#x27;", "'")


def _press(client, period, captured, **data):
    with patch("core.pending_imports.subprocess.Popen") as popen:
        with captured(execute=True):
            response = client.post(reverse("accounting:period_finalize", args=[period.pk]), data)
    return response, popen


def _page(client, period):
    return client.get(reverse("accounting:period_detail", args=[period.pk]))


# -- Pressing Finalize -----------------------------------------------------------------------


def test_pressing_finalize_answers_at_once_and_starts_one_process(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    response, popen = _press(client, year, django_capture_on_commit_callbacks)

    assert response.status_code == 302
    assert response.url == reverse("accounting:period_detail", args=[year.pk])
    assert popen.call_count == 1
    assert popen.call_args.args[0][-3:-1] == ["run_pending_import", "--token"]
    pending = PendingImport.objects.get(kind="finalize")
    assert pending.status == "waiting"
    assert pending.settings["period"] == year.pk
    year.refresh_from_db()
    assert year.is_finalized is False
    assert not PeriodStatement.objects.filter(period=year).exists()


def test_a_second_press_while_it_runs_starts_nothing(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    response, popen = _press(client, year, django_capture_on_commit_callbacks)

    assert response.status_code == 302
    assert popen.call_count == 0
    assert PendingImport.objects.filter(kind="finalize").count() == 1


# Default wording, approved by the maintainer on 2026-11-16. To change the wording, update this test in the same commit.
def test_the_page_shows_the_run_and_no_button_while_it_runs(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="finalize")

    response = _page(client, year)
    html = response.content.decode()
    words = _words(response)
    since = timezone.localtime(pending.created_at).strftime("%-I:%M %p")
    assert f"Finalizing since {since}." in words
    assert RUNNING_LEAVE in words
    assert "Finalize water year</button>" not in html
    # A calculation now would change the records the statement is written from.
    assert reverse("accounting:period_calculate", args=[year.pk]) not in html
    assert reverse("accounting:period_finalizing", args=[year.pk]) in html


def test_the_status_poll_asks_for_a_reload_once_the_year_is_finalized(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    status_url = reverse("accounting:period_finalizing", args=[year.pk])
    assert client.get(status_url).get("HX-Refresh") is None

    pending_imports.run(str(PendingImport.objects.get(kind="finalize").token))

    assert client.get(status_url)["HX-Refresh"] == "true"


# -- What the process writes -----------------------------------------------------------------


def test_the_process_finalizes_the_year_exactly_as_the_request_did(
        client, administrator, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    expected = collect_figures(year)
    _press(client, year, django_capture_on_commit_callbacks, note="Board approved the close")
    pending_imports.run(str(PendingImport.objects.get(kind="finalize").token))

    year.refresh_from_db()
    assert year.is_finalized is True
    assert year.finalized_by_id == administrator.pk
    assert year.fingerprint
    statement = PeriodStatement.objects.get(period=year)
    assert statement.kind == "filed"
    assert statement.taken_by_id == administrator.pk
    assert statement_figures(statement) == expected
    # The change history names the person, the button's own address and the note, as the
    # request's context did.
    event = year.events.get(pgh_label="update")
    assert event.pgh_context.metadata["user"] == administrator.pk
    assert event.pgh_context.metadata["url"] == reverse("accounting:period_finalize", args=[year.pk])
    assert event.pgh_context.metadata["note"] == "Board approved the close"
    row_events = apps.get_model("accounting", "PeriodStatementRowEvent").objects
    assert row_events.filter(statement=statement.pk, pgh_label="insert").count() == len(expected)
    assert not row_events.filter(statement=statement.pk, pgh_context__isnull=True).exists()
    assert not PendingImport.objects.filter(kind="finalize").exclude(status="finished").exists()


def test_the_finished_statement_equals_one_written_the_old_way(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    pending_imports.run(str(PendingImport.objects.get(kind="finalize").token))
    year.refresh_from_db()
    new_way = statement_figures(PeriodStatement.objects.get(period=year))

    # Reopen and write a statement the way the request wrote it before.
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=False)
    old_way = statement_figures(take_statement(year, kind="restated"))
    assert new_way == old_way


def test_the_finalized_year_lock_refuses_an_edit_after_the_process_ends(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    pending_imports.run(str(PendingImport.objects.get(kind="finalize").token))
    statement = PeriodStatement.objects.get(period=year)

    from django.db import DatabaseError, transaction
    with pytest.raises(DatabaseError), transaction.atomic():
        PeriodStatementRow.objects.create(
            statement=statement, period=year, scope="site", scope_id=1, scope_name="x",
            figure="crop_et", value=1)


def test_a_failure_keeps_nothing_and_leaves_the_year_open(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    with patch("accounting.fingerprints.take_fingerprint", side_effect=RuntimeError("boom")):
        pending_imports.run(str(PendingImport.objects.get(kind="finalize").token))

    year.refresh_from_db()
    assert year.is_finalized is False
    assert not year.fingerprint
    assert not PeriodStatement.objects.filter(period=year).exists()
    assert PendingImport.objects.get(kind="finalize").status == "failed"


# Default wording, approved by the maintainer on 2026-11-16. To change the wording, update this test in the same commit.
def test_the_stopped_words_show_with_the_button_until_the_next_press(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    with patch("accounting.fingerprints.take_fingerprint", side_effect=RuntimeError("boom")):
        pending_imports.run(str(PendingImport.objects.get(kind="finalize").token))

    for _ in range(2):  # shown on every visit, not once
        response = _page(client, year)
        assert STOPPED in _words(response)
        assert "Finalize water year</button>" in response.content.decode()

    _, popen = _press(client, year, django_capture_on_commit_callbacks)
    assert popen.call_count == 1
    assert STOPPED not in _words(_page(client, year))
    assert PendingImport.objects.filter(kind="finalize").count() == 1


def test_a_run_whose_process_is_gone_is_shown_stopped(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="finalize")
    pending.status = "running"
    pending.started_at = timezone.now() - datetime.timedelta(minutes=2)
    pending.save()

    assert STOPPED in _words(_page(client, year))
    pending.refresh_from_db()
    assert pending.status == "failed"


def test_a_run_that_just_started_is_not_called_stopped(
        client, year, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _press(client, year, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="finalize")
    pending.status = "running"
    pending.started_at = timezone.now() - datetime.timedelta(seconds=10)
    pending.save()

    words = _words(_page(client, year))
    assert STOPPED not in words
    assert RUNNING_LEAVE in words


def test_a_run_holding_the_years_row_is_not_called_stopped(year):
    """The process holds the year's row for the whole write; the page reads that as alive."""
    from accounting import finalize

    pending = PendingImport.objects.create(
        kind="finalize", user=User.objects.create_user(username="holder", password="x"),
        original_name="", stored_path="", status="running",
        started_at=timezone.now() - datetime.timedelta(minutes=5), settings={"period": year.pk})
    with patch.object(finalize, "_year_is_held", return_value=True):
        assert finalize.state(year)["state"] == "running"
    pending.refresh_from_db()
    assert pending.status == "running"


def test_a_row_left_running_on_a_finalized_year_is_cleared(year):
    from accounting import finalize

    PendingImport.objects.create(
        kind="finalize", user=User.objects.create_user(username="leftover", password="x"),
        original_name="", stored_path="", status="running",
        started_at=timezone.now() - datetime.timedelta(minutes=5), settings={"period": year.pk})
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    year.refresh_from_db()
    assert finalize.state(year) == {"state": None}
    assert not PendingImport.objects.filter(kind="finalize").exists()


def test_the_year_lock_test_really_takes_no_wait(year):
    """``_year_is_held`` must not block: it is asked on every page view."""
    from accounting import finalize

    seen = []

    def capture(execute, sql, params, many, context):
        seen.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(capture):
        assert finalize._year_is_held(year) is False
    assert any("NOWAIT" in sql.upper() for sql in seen)


def test_reopening_still_happens_in_the_request(client, year):
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    response = client.post(
        reverse("accounting:period_finalize", args=[year.pk]),
        {"note": "Reopened to add a late meter reading"})
    assert response.status_code == 302
    year.refresh_from_db()
    assert year.is_finalized is False
    assert not PendingImport.objects.filter(kind="finalize").exists()
