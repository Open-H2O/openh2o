# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fetch readings now (151.6-05, design B).

A button beside the schedule sentence on a station's page fetches that one
station's readings in a detached process and shows what the run got. The suite
never spawns a process: ``OPENH2O_FETCH_INLINE`` (set in conftest.py) runs the
fetch in-process, and the tests that count processes turn it off and patch
``subprocess.Popen``. No test touches the network: the adapter's ``fetch`` is
replaced with a recorded answer.
"""

from datetime import date, timedelta
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.access import READ_ONLY_MESSAGE
from core.models import User
from datasync import fetch_now
from datasync.adapters import get_adapter
from datasync.adapters.usgs import USGSAdapter
from datasync.management.commands.sync_source import _pull_window
from datasync.models import DataRecordStaging, DataSource, DataSyncLog, MonitoredStation

pytestmark = pytest.mark.django_db


def _source(code="usgs", name="USGS NWIS", active=True):
    source, _ = DataSource.objects.get_or_create(code=code, defaults={"name": name})
    source.name = name
    source.is_active = active
    source.save()
    return source


def _station(source, external="11111111", **extra):
    return MonitoredStation.objects.create(
        data_source=source,
        external_station_id=external,
        station_name=f"Probe gauge {external}",
        location=Point(-120.0, 37.0, srid=4326),
        is_active=extra.pop("is_active", True),
        **extra,
    )


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        **flags,
    )


def _client(user=None):
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _record(external, day, value=12.5, parameter="00060", statistic="00003"):
    return {
        "station_id": external,
        "observation_date": day,
        "parameter_code": parameter,
        "value": value,
        "unit": "cfs",
        "statistic_id": statistic,
    }


@pytest.fixture
def usgs():
    return _source()


@pytest.fixture
def station(usgs):
    return _station(usgs)


@pytest.fixture
def operator():
    return _user("operator")


@pytest.fixture
def viewer():
    return _user("viewer", read_only=True)


@pytest.fixture
def answer(monkeypatch):
    """Replace the USGS fetch with a recorded answer; ``answer.rows`` is what it returns."""

    class Answer:
        rows = []
        error = None
        calls = []

    def fake_fetch(self, station, start_date, end_date):
        Answer.calls.append((station.pk, start_date, end_date))
        if Answer.error is not None:
            raise Answer.error
        return list(Answer.rows)

    Answer.rows, Answer.error, Answer.calls = [], None, []
    monkeypatch.setattr(USGSAdapter, "fetch", fake_fetch)
    return Answer


def _fetch_url(station):
    return reverse("datasync:station_fetch_now", args=[station.pk])


def _status_url(station, log):
    return reverse("datasync:station_fetch_status", args=[station.pk, log.pk])


def _page(client, station):
    response = client.get(reverse("datasync:station_detail", args=[station.pk]))
    assert response.status_code == 200
    return response.content.decode()


# -- The press ---------------------------------------------------------------------


@pytest.fixture
def detached(settings, monkeypatch, django_capture_on_commit_callbacks):
    """Turn the in-process shortcut off and catch every process the page would start."""
    settings.OPENH2O_FETCH_INLINE = False
    popen = mock.Mock()
    monkeypatch.setattr(fetch_now.subprocess, "Popen", popen)

    def press(client, station):
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(_fetch_url(station))

    press.popen = popen
    return press


def test_a_press_creates_one_log_for_the_station_and_starts_one_process(
    detached, station, operator
):
    response = detached(_client(operator), station)

    assert response.status_code == 200
    log = DataSyncLog.objects.get()
    assert log.station == station
    assert log.data_source == station.data_source
    assert log.status == "running"
    detached.popen.assert_called_once()
    argv = detached.popen.call_args.args[0]
    assert argv[1:] == [
        "manage.py", "sync_source", "usgs",
        "--station", str(station.pk), "--log", str(log.pk),
    ]
    body = response.content.decode()
    assert "Fetching readings…" in body
    assert 'class="spinner-sm"' in body
    assert "disabled" in body
    assert _status_url(station, log) in body
    assert 'hx-trigger="every 2s"' in body


def test_a_second_press_while_a_run_is_running_is_refused(detached, station, operator):
    client = _client(operator)
    detached(client, station)
    response = detached(client, station)

    body = response.content.decode()
    assert "A fetch is already running." in body
    assert "Fetching readings…" in body
    assert DataSyncLog.objects.count() == 1
    detached.popen.assert_called_once()


def test_a_run_older_than_ten_minutes_no_longer_blocks_the_button(detached, station, operator):
    client = _client(operator)
    detached(client, station)
    stuck = DataSyncLog.objects.get()
    DataSyncLog.objects.filter(pk=stuck.pk).update(
        started_at=timezone.now() - timedelta(minutes=10, seconds=5)
    )

    response = detached(client, station)

    assert "A fetch is already running." not in response.content.decode()
    assert DataSyncLog.objects.filter(station=station).count() == 2
    assert detached.popen.call_count == 2


def test_a_run_inside_ten_minutes_still_blocks_it(detached, station, operator):
    client = _client(operator)
    detached(client, station)
    DataSyncLog.objects.update(started_at=timezone.now() - timedelta(minutes=9))

    response = detached(client, station)

    assert "A fetch is already running." in response.content.decode()
    assert detached.popen.call_count == 1


def test_a_run_at_another_station_does_not_block_this_one(detached, station, operator):
    other = _station(station.data_source, "22222222")
    client = _client(operator)
    detached(client, other)
    response = detached(client, station)

    assert "A fetch is already running." not in response.content.decode()
    assert detached.popen.call_count == 2


def test_a_process_that_cannot_start_closes_its_log(detached, station, operator):
    detached.popen.side_effect = OSError("no fork")
    detached(_client(operator), station)

    log = DataSyncLog.objects.get()
    assert log.status == "failed"
    assert log.completed_at is not None
    assert log.error_message


def test_a_viewer_is_refused_and_nothing_starts(detached, station, viewer):
    response = detached(_client(viewer), station)

    assert response.status_code == 403
    assert READ_ONLY_MESSAGE in response.content.decode()
    assert DataSyncLog.objects.count() == 0
    detached.popen.assert_not_called()


def test_a_signed_out_visitor_is_sent_to_sign_in(detached, station):
    response = detached(_client(), station)

    assert response.status_code == 302
    assert "login" in response["Location"]
    assert DataSyncLog.objects.count() == 0
    detached.popen.assert_not_called()


def test_an_administrator_may_press(detached, station):
    admin = _user("admin-user", agency_admin=True)
    detached(_client(admin), station)
    assert DataSyncLog.objects.filter(station=station).count() == 1


def test_a_source_that_is_off_or_by_hand_is_refused(detached, usgs, operator):
    off = _source("cdec", "CDEC", active=False)
    hand = _source("manual", "Entered by hand")
    client = _client(operator)
    for source in (off, hand):
        station = _station(source, f"X-{source.code}")
        response = detached(client, station)
        assert response.status_code == 403
    assert DataSyncLog.objects.count() == 0
    detached.popen.assert_not_called()


def test_a_source_missing_its_key_is_refused(detached, monkeypatch, operator):
    monkeypatch.delenv("CIMIS_API_KEY", raising=False)
    station = _station(_source("cimis", "CIMIS"), "CIMIS-1")
    response = detached(_client(operator), station)

    assert response.status_code == 403
    assert DataSyncLog.objects.count() == 0


# -- What the page shows after the run -------------------------------------------------


def _press_inline(client, station):
    """With the in-process shortcut on (the suite's default) the press runs the fetch."""
    response = client.post(_fetch_url(station))
    assert response.status_code == 200
    return response


def test_the_status_route_reports_the_count_and_the_newest_date(
    station, operator, answer
):
    answer.rows = [
        _record(station.external_station_id, "2026-10-30"),
        _record(station.external_station_id, "2026-10-31"),
    ]
    client = _client(operator)
    _press_inline(client, station)
    log = DataSyncLog.objects.get()

    body = client.get(_status_url(station, log)).content.decode()

    assert "OpenH2O fetched 2 readings. The newest is from Oct 31, 2026." in body
    assert "hx-trigger" not in body
    assert "Fetch readings now" in body
    assert "disabled" not in body


def test_one_reading_is_singular(station, operator, answer):
    answer.rows = [_record(station.external_station_id, "2026-10-31")]
    client = _client(operator)
    _press_inline(client, station)
    body = client.get(_status_url(station, DataSyncLog.objects.get())).content.decode()
    assert "OpenH2O fetched 1 reading. The newest is from Oct 31, 2026." in body


def test_no_readings_says_so_in_the_sources_name(station, operator, answer):
    answer.rows = []
    client = _client(operator)
    _press_inline(client, station)
    log = DataSyncLog.objects.get()
    assert log.status == "success"

    body = client.get(_status_url(station, log)).content.decode()

    assert "USGS NWIS did not send any readings for this station." in body
    assert "text-error" not in body


def test_a_connection_error_says_the_source_did_not_answer(station, operator, answer):
    answer.error = requests.ConnectionError("Max retries exceeded: [Errno 111]")
    client = _client(operator)
    _press_inline(client, station)
    log = DataSyncLog.objects.get()
    assert log.status == "failed"

    body = client.get(_status_url(station, log)).content.decode()

    assert 'text-error' in body
    assert "USGS NWIS did not answer." in body
    assert "Max retries" not in body


def test_a_timeout_says_the_source_did_not_answer(station, operator, answer):
    answer.error = requests.ReadTimeout("read timed out")
    client = _client(operator)
    _press_inline(client, station)
    body = client.get(_status_url(station, DataSyncLog.objects.get())).content.decode()
    assert "USGS NWIS did not answer." in body


def test_any_other_failure_shows_the_logs_own_message(station, operator, answer):
    answer.error = ValueError("The provider changed its date format.")
    client = _client(operator)
    _press_inline(client, station)
    log = DataSyncLog.objects.get()

    body = client.get(_status_url(station, log)).content.decode()

    assert "The provider changed its date format." in body
    assert "did not answer" not in body
    assert "text-error" in body


def test_a_run_still_running_keeps_the_page_polling(station, operator):
    log = DataSyncLog.objects.create(
        data_source=station.data_source, station=station, status="running"
    )
    body = _client(operator).get(_status_url(station, log)).content.decode()

    assert "Fetching readings…" in body
    assert 'hx-trigger="every 2s"' in body
    assert _status_url(station, log) in body


def test_a_page_opened_during_a_run_shows_the_fetching_state(station, operator):
    DataSyncLog.objects.create(
        data_source=station.data_source, station=station, status="running"
    )
    body = _page(_client(operator), station)
    assert "Fetching readings…" in body
    assert 'hx-trigger="every 2s"' in body


def test_a_status_for_another_stations_log_is_not_found(station, operator):
    other = _station(station.data_source, "33333333")
    log = DataSyncLog.objects.create(
        data_source=other.data_source, station=other, status="running"
    )
    response = _client(operator).get(_status_url(station, log))
    assert response.status_code == 404


# -- The pipeline underneath ---------------------------------------------------------------


def _stage_for(station, log, day):
    adapter = get_adapter("usgs")
    adapter.stage([_record(station.external_station_id, day)], log, station)


def test_publish_with_a_station_leaves_the_other_stations_rows_staged(usgs):
    a = _station(usgs, "AAA")
    b = _station(usgs, "BBB")
    log = DataSyncLog.objects.create(data_source=usgs, status="running")
    _stage_for(a, log, "2026-10-30")
    _stage_for(b, log, "2026-10-30")

    published = get_adapter("usgs").publish(log, station=a)

    assert published == 1
    assert DataRecordStaging.objects.get(station=a).status == "published"
    assert DataRecordStaging.objects.get(station=b).status == "staged"
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.last_data_at is not None
    assert b.last_data_at is None


def test_publish_without_a_station_still_promotes_the_whole_source(usgs):
    a = _station(usgs, "AAA")
    b = _station(usgs, "BBB")
    log = DataSyncLog.objects.create(data_source=usgs, status="running")
    _stage_for(a, log, "2026-10-30")
    _stage_for(b, log, "2026-10-30")

    assert get_adapter("usgs").publish(log) == 2


def test_sync_source_with_a_station_touches_only_that_station_and_closes_the_log(
    usgs, answer
):
    a = _station(usgs, "AAA")
    b = _station(usgs, "BBB")
    answer.rows = [_record("AAA", "2026-10-30"), _record("AAA", "2026-10-31")]
    log = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")

    call_command("sync_source", "usgs", "--station", str(a.pk), "--log", str(log.pk))

    assert [pk for pk, *_ in answer.calls] == [a.pk]
    assert DataRecordStaging.objects.filter(station=b).count() == 0
    assert DataRecordStaging.objects.filter(station=a, status="published").count() == 2
    assert DataSyncLog.objects.count() == 1
    log.refresh_from_db()
    assert log.status == "success"
    assert log.records_fetched == 2
    assert log.records_staged == 2
    assert log.records_published == 2
    assert log.completed_at is not None
    assert log.duration_seconds is not None


def test_sync_source_with_a_station_uses_the_scheduled_default_window(usgs, answer):
    a = _station(usgs, "AAA")
    log = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")

    call_command("sync_source", "usgs", "--station", str(a.pk), "--log", str(log.pk))

    start, end = _pull_window("usgs", None, None)
    assert answer.calls == [(a.pk, start, end)]
    assert end == date.today()


def test_sync_source_with_a_station_fetches_it_even_when_syncing_is_off(usgs, answer):
    a = _station(usgs, "AAA", is_active=False)
    log = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")
    call_command("sync_source", "usgs", "--station", str(a.pk), "--log", str(log.pk))
    assert [pk for pk, *_ in answer.calls] == [a.pk]


def test_sync_source_with_a_station_does_not_move_the_sources_last_sync(usgs, answer):
    a = _station(usgs, "AAA")
    log = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")
    call_command("sync_source", "usgs", "--station", str(a.pk), "--log", str(log.pk))
    usgs.refresh_from_db()
    assert usgs.last_sync_at is None


def test_sync_source_with_a_station_of_another_source_is_an_error(usgs, answer):
    from django.core.management.base import CommandError

    other = _station(_source("cdec", "CDEC"), "CDEC-1")
    with pytest.raises(CommandError):
        call_command("sync_source", "usgs", "--station", str(other.pk))
    assert answer.calls == []


def test_a_failed_station_run_closes_the_log_as_failed(usgs, answer):
    a = _station(usgs, "AAA")
    answer.error = requests.ConnectionError("down")
    log = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")

    call_command("sync_source", "usgs", "--station", str(a.pk), "--log", str(log.pk))

    log.refresh_from_db()
    assert log.status == "failed"
    assert log.completed_at is not None
    assert log.error_message


def test_a_scheduled_run_does_not_reap_a_fetch_that_just_started(usgs, answer):
    a = _station(usgs, "AAA")
    b = _station(usgs, "BBB")
    young = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")
    old = DataSyncLog.objects.create(data_source=usgs, station=a, status="running")
    DataSyncLog.objects.filter(pk=old.pk).update(
        started_at=timezone.now() - timedelta(minutes=30)
    )
    answer.rows = []

    call_command("sync_source", "usgs")

    young.refresh_from_db()
    old.refresh_from_db()
    assert young.status == "running"
    assert old.status == "failed"
    assert b.pk in [pk for pk, *_ in answer.calls]


def test_deleting_a_station_keeps_its_logs(usgs):
    a = _station(usgs, "AAA")
    log = DataSyncLog.objects.create(data_source=usgs, station=a, status="success")
    a.delete()
    log.refresh_from_db()
    assert log.station is None


def test_a_one_station_run_does_not_count_as_the_sources_own_sync(usgs):
    """The source-level views read whole-source runs, not a single press."""
    a = _station(usgs, "AAA")
    DataSyncLog.objects.create(data_source=usgs, station=a, status="success")
    from health.checks import check_sync_freshness

    result = check_sync_freshness()
    assert result["details"]["usgs"]["last_sync"] is None


# -- Where the button shows ---------------------------------------------------------------------


def test_the_button_shows_for_a_writer_on_an_active_usgs_station(station, operator):
    body = _page(_client(operator), station)
    assert "Fetch readings now" in body
    assert 'class="btn-secondary btn-sm"' in body
    assert reverse("datasync:station_fetch_now", args=[station.pk]) in body


def test_the_button_shows_for_an_administrator(station):
    body = _page(_client(_user("admin-user", agency_admin=True)), station)
    assert "Fetch readings now" in body


def test_the_button_does_not_show_for_a_viewer(station, viewer):
    assert "Fetch readings now" not in _page(_client(viewer), station)


def test_the_button_does_not_show_when_the_source_is_off(operator):
    station = _station(_source("usgs", "USGS NWIS", active=False))
    assert "Fetch readings now" not in _page(_client(operator), station)


def test_the_button_does_not_show_when_the_sources_key_is_missing(monkeypatch, operator):
    monkeypatch.delenv("CIMIS_API_KEY", raising=False)
    station = _station(_source("cimis", "CIMIS"), "CIMIS-1")
    assert "Fetch readings now" not in _page(_client(operator), station)


def test_the_button_shows_once_the_key_is_set(monkeypatch, operator):
    monkeypatch.setenv("CIMIS_API_KEY", "probe-not-a-real-key")
    station = _station(_source("cimis", "CIMIS"), "CIMIS-1")
    assert "Fetch readings now" in _page(_client(operator), station)


def test_the_button_does_not_show_on_a_station_entered_by_hand(operator):
    station = _station(_source("manual", "Entered by hand"), "HAND-1")
    assert "Fetch readings now" not in _page(_client(operator), station)


def test_the_button_does_not_show_for_a_source_without_an_adapter(operator):
    station = _station(_source("probe_none", "Probe network"), "P-1")
    assert "Fetch readings now" not in _page(_client(operator), station)


def test_the_button_stands_beside_the_schedule_sentence(station, operator, tmp_path, settings):
    (tmp_path / "crontab.txt").write_text("0 * * * * /x/scripts/run-sync.sh usgs\n")
    settings.BASE_DIR = tmp_path
    body = _page(_client(operator), station)

    assert 'id="fetch-schedule"' in body
    assert body.index('id="fetch-schedule"') < body.index("Fetch readings now")
    assert "flex-direction: column; gap: var(--space-xs)" in body


def test_with_no_schedule_sentence_the_button_stands_alone(station, operator, tmp_path, settings):
    settings.BASE_DIR = tmp_path  # no crontab.txt there, so no sentence
    body = _page(_client(operator), station)

    assert 'id="fetch-schedule"' not in body
    assert "Fetch readings now" in body
