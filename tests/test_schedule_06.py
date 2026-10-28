# SPDX-License-Identifier: AGPL-3.0-or-later
"""When OpenH2O fetches readings, and what sync_source says when it cannot.

Three things a person setting up a site could not tell from the screen:

* a station's page said nothing about when its readings are fetched;
* the shipped schedule never fetched CIMIS, and its comment called CIMIS off;
* ``sync_source`` told a person to run discovery when the stations were found
  and only switched off.

Every source, station and file here is made up for the test.
"""
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from core.models import SiteConfig, User
from datasync import schedule
from datasync.models import DataSource, DataSyncLog, MonitoredStation

pytestmark = pytest.mark.django_db

PACIFIC = ZoneInfo("America/Los_Angeles")

CRONTAB = """\
# a comment line that mentions run-sync.sh alpha and must be ignored
OPENH2O_DIR=/opt/openh2o
0 * * * * $OPENH2O_DIR/scripts/run-sync.sh alpha beta
# 5 4 * * * $OPENH2O_DIR/scripts/run-sync.sh switchedoff
0 2 * * * $OPENH2O_DIR/scripts/run-sync.sh gamma delta
30 3 * * * cd $OPENH2O_DIR && docker compose exec -T web python manage.py run_accounting
"""


@pytest.fixture
def crontab(settings, tmp_path):
    """Point the schedule reader at a crontab text written by the test."""
    settings.BASE_DIR = tmp_path

    def write(text):
        (tmp_path / "crontab.txt").write_text(text)

    write(CRONTAB)
    return write


def _at(hour, minute=0, day=14):
    return datetime(2031, 3, day, hour, minute, tzinfo=PACIFIC)


class TestReadingTheCrontab:
    def test_an_hourly_line_is_said_in_words(self, crontab):
        assert schedule.describe("alpha") == "every hour, on the hour"
        assert schedule.describe("beta") == "every hour, on the hour"

    def test_a_daily_line_is_said_in_words(self, crontab):
        assert schedule.describe("gamma") == "every day at 2:00 AM"

    def test_a_commented_line_does_not_count(self, crontab):
        assert schedule.describe("switchedoff") is None
        assert schedule.is_scheduled("switchedoff") is False

    def test_a_source_absent_from_the_file_is_not_scheduled(self, crontab):
        assert schedule.is_scheduled("epsilon") is False
        assert schedule.describe("epsilon") is None
        assert schedule.next_run("epsilon", _at(9)) is None

    def test_other_jobs_are_not_sources(self, crontab):
        assert schedule.is_scheduled("run_accounting") is False

    def test_an_unreadable_file_says_nothing(self, settings, tmp_path):
        settings.BASE_DIR = tmp_path  # no crontab.txt in it
        assert schedule.is_scheduled("alpha") is None
        assert schedule.describe("alpha") is None
        assert schedule.next_run("alpha", _at(9)) is None

    def test_a_field_the_reader_does_not_know_is_not_guessed(self, crontab):
        crontab("15,45 1-5 * * 1 /x/scripts/run-sync.sh alpha\n")
        assert schedule.describe("alpha") is None
        assert schedule.next_run("alpha", _at(9)) is None
        # and a source named only on a line it cannot read is not "absent"
        assert schedule.is_scheduled("alpha") is None

    def test_every_n_hours(self, crontab):
        crontab("0 */6 * * * /x/scripts/run-sync.sh alpha\n")
        assert schedule.describe("alpha") == "every 6 hours, on the hour"
        assert schedule.next_run("alpha", _at(7, 30)) == _at(12)


class TestTheNextRun:
    def test_hourly_is_the_top_of_the_next_hour(self, crontab):
        assert schedule.next_run("alpha", _at(4, 20)) == _at(5)

    def test_a_run_exactly_now_is_not_next(self, crontab):
        assert schedule.next_run("alpha", _at(4, 0)) == _at(5)

    def test_daily_later_today(self, crontab):
        assert schedule.next_run("gamma", _at(1, 10)) == _at(2)

    def test_daily_after_the_hour_is_tomorrow(self, crontab):
        assert schedule.next_run("gamma", _at(2, 1)) == _at(2, day=15)

    def test_across_midnight_in_the_sites_own_zone(self, crontab):
        # 23:30 on the 14th in Pacific time is 06:30 UTC on the 15th. The next
        # 2:00 AM is the 15th in Pacific time, not UTC's 2:00 AM.
        now = datetime(2031, 3, 14, 23, 30, tzinfo=PACIFIC)
        assert schedule.next_run("gamma", now) == _at(2, day=15)
        assert schedule.next_run("alpha", now) == datetime(
            2031, 3, 15, 0, 0, tzinfo=PACIFIC
        )

    def test_the_answer_is_in_the_site_zone_whatever_zone_now_arrives_in(self, crontab):
        SiteConfig.objects.all().delete()
        SiteConfig.objects.create(agency_name="Probe Agency", timezone="America/New_York")
        eastern = ZoneInfo("America/New_York")
        now_utc = datetime(2031, 3, 14, 10, 20, tzinfo=ZoneInfo("UTC"))  # 6:20 AM Eastern (EDT)
        result = schedule.next_run("alpha", now_utc)
        assert result == datetime(2031, 3, 14, 7, 0, tzinfo=eastern)
        assert result.tzinfo.key == "America/New_York"


@pytest.fixture
def station_page():
    user = User.objects.create(
        username="sched-reader", email="sched-reader@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)

    def make(code, name, *, syncing=True, source_on=True):
        src, _ = DataSource.objects.get_or_create(
            code=code, defaults={"name": name, "is_active": source_on}
        )
        station = MonitoredStation.objects.create(
            data_source=src, external_station_id=f"{code}-1",
            station_name=f"Probe {code} station",
            location=Point(-120.0, 37.0), is_active=syncing,
        )
        resp = client.get(reverse("datasync:station_detail", args=[station.pk]))
        assert resp.status_code == 200
        import html as _html
        return _html.unescape(resp.content.decode())

    return make


class TestTheStationPage:
    def test_syncing_on_and_on_the_schedule(self, crontab, station_page, monkeypatch):
        monkeypatch.setattr(
            schedule, "_now", lambda: datetime(2031, 3, 14, 4, 20, tzinfo=PACIFIC)
        )
        body = station_page("alpha", "Probe Alpha Network")
        assert (
            "OpenH2O fetches readings from Probe Alpha Network every hour, on the hour. "
            "The next fetch is at 5:00 AM." in body
        )

    def test_the_day_is_named_when_it_is_not_today(self, crontab, station_page, monkeypatch):
        monkeypatch.setattr(
            schedule, "_now", lambda: datetime(2031, 3, 14, 4, 20, tzinfo=PACIFIC)
        )
        body = station_page("gamma", "Probe Gamma Network")
        assert (
            "OpenH2O fetches readings from Probe Gamma Network every day at 2:00 AM. "
            "The next fetch is at 2:00 AM tomorrow." in body
        )

    def test_syncing_on_and_the_source_not_on_the_schedule(self, crontab, station_page):
        body = station_page("epsilon", "Probe Epsilon Network")
        assert (
            "OpenH2O's schedule does not fetch readings from Probe Epsilon Network." in body
        )

    def test_the_source_is_switched_off(self, crontab, station_page):
        body = station_page("alpha", "Probe Alpha Network", source_on=False)
        assert (
            "OpenH2O's schedule skips Probe Alpha Network: the source is switched "
            "off in OpenH2O's list of data sources." in body
        )
        assert "OpenH2O fetches readings from" not in body

    def test_the_source_needs_a_key_that_is_not_set(
        self, crontab, station_page, monkeypatch
    ):
        monkeypatch.delenv("CIMIS_API_KEY", raising=False)
        crontab("0 2 * * * /x/scripts/run-sync.sh cimis\n")
        body = station_page("cimis", "Probe CIMIS Network")
        assert (
            "OpenH2O's schedule fetches readings from Probe CIMIS Network every day "
            "at 2:00 AM once its key is set. The key is not set on this server." in body
        )
        assert "OpenH2O fetches readings from" not in body

    def test_the_same_source_with_its_key_set_gets_the_plain_sentence(
        self, crontab, station_page, monkeypatch
    ):
        monkeypatch.setenv("CIMIS_API_KEY", "probe-not-a-real-key")
        crontab("0 2 * * * /x/scripts/run-sync.sh cimis\n")
        body = station_page("cimis", "Probe CIMIS Network")
        assert "OpenH2O fetches readings from Probe CIMIS Network every day at 2:00 AM." in body
        assert "key is not set" not in body

    def test_syncing_off(self, crontab, station_page):
        body = station_page("alpha", "Probe Alpha Network", syncing=False)
        assert "Syncing is off, so OpenH2O's schedule skips this station." in body
        assert "The next fetch is at" not in body

    def test_an_unreadable_file_leaves_the_page_without_a_sentence(
        self, settings, tmp_path, station_page
    ):
        settings.BASE_DIR = tmp_path
        body = station_page("alpha", "Probe Alpha Network")
        assert "OpenH2O fetches readings from" not in body
        assert "schedule does not fetch" not in body


def test_the_shipped_crontab_fetches_cimis_and_says_why_not_cnrfc(settings):
    """The shipped file, read by the same reader the page uses."""
    from pathlib import Path

    settings.BASE_DIR = Path(__file__).resolve().parent.parent
    assert schedule.describe("cimis") == "every day at 2:00 AM"
    assert schedule.describe("cdec") == "every hour, on the hour"
    assert schedule.is_scheduled("cnrfc") is False
    text = (settings.BASE_DIR / "crontab.txt").read_text()
    assert "deactivated" not in text
    assert "Merced" not in text
    assert (
        "CNRFC is switched off in OpenH2O's list of data sources (it publishes "
        "forecasts, not readings), so the schedule does not fetch it." in " ".join(
            line.lstrip("# ").rstrip() for line in text.splitlines()
        )
    )


# ── sync_source ────────────────────────────────────────────────────────


def _source(code, name, *, active=True):
    return DataSource.objects.get_or_create(
        code=code, defaults={"name": name, "is_active": active}
    )[0]


def _station(src, n, *, on):
    return MonitoredStation.objects.create(
        data_source=src, external_station_id=f"{src.code}-{n}",
        station_name=f"Probe station {n}", location=Point(-120.0, 37.0), is_active=on,
    )


def _run(code):
    out = StringIO()
    call_command("sync_source", code, stdout=out, stderr=StringIO())
    return out.getvalue()


class TestAKeylessSourceIsSkippedInOneLine:
    def test_cimis_without_its_key(self, monkeypatch, settings):
        monkeypatch.delenv("CIMIS_API_KEY", raising=False)
        settings.DATASYNC_MOCK_MODE = False
        src = _source("cimis", "CIMIS")
        src.is_active = True
        src.save()
        _station(src, 1, on=True)
        logs_before = DataSyncLog.objects.count()
        text = _run("cimis")  # raises on a traceback or a non-zero exit
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 1
        assert lines[0] == (
            "CIMIS is skipped because its key is not set: CIMIS appKey (set CIMIS_API_KEY)."
        )
        assert "Traceback" not in text
        assert DataSyncLog.objects.count() == logs_before
        # nothing was fetched, so no failure was recorded against the source
        assert not DataSyncLog.objects.filter(data_source=src, status="failed").exists()

    def test_noaa_without_its_token(self, monkeypatch, settings):
        monkeypatch.delenv("NOAA_CDO_TOKEN", raising=False)
        settings.DATASYNC_MOCK_MODE = False
        src = _source("noaa", "NOAA")
        src.is_active = True
        src.save()
        _station(src, 1, on=True)
        text = _run("noaa")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert lines == [
            "NOAA is skipped because its key is not set: "
            "NOAA CDO token (set NOAA_CDO_TOKEN)."
        ]
        assert DataSyncLog.objects.count() == 0

    def test_cimis_with_its_key_goes_on_to_the_stations(self, monkeypatch, settings):
        monkeypatch.setenv("CIMIS_API_KEY", "probe-not-a-real-key")
        src = _source("cimis", "CIMIS")
        src.is_active = True
        src.save()
        _station(src, 1, on=True)
        # With a key set the skip line must not appear; the command reaches
        # the station count. (Mock mode keeps the test off the network.)
        out = StringIO()
        call_command("sync_source", "cimis", "--mock", stdout=out, stderr=StringIO())
        assert "not set" not in out.getvalue()
        assert "Syncing 1 station(s) for CIMIS" in out.getvalue()


class TestTheMessageWhenNothingIsOn:
    def test_no_stations_at_all(self):
        src = _source("usgs", "USGS NWIS")
        text = _run("usgs")
        assert "No stations for USGS NWIS. Run discover_stations usgs first." in text
        assert "No active stations" not in text
        assert src.monitoredstation_set.count() == 0

    def test_stations_found_but_all_switched_off(self):
        src = _source("usgs", "USGS NWIS")
        for n in (1, 2, 3):
            _station(src, n, on=False)
        text = _run("usgs")
        assert "discover_stations" not in text
        assert "3 stations for USGS NWIS are switched off" in text
        assert "activate_stations --source usgs" in text
        assert "Enable all" in text
        assert "Setup Wizard" in text

    def test_some_on_is_unchanged(self):
        src = _source("usgs", "USGS NWIS")
        _station(src, 1, on=True)
        _station(src, 2, on=False)
        out = StringIO()
        call_command("sync_source", "usgs", "--mock", stdout=out, stderr=StringIO())
        text = out.getvalue()
        assert "Syncing 1 station(s) for USGS NWIS" in text
        assert "switched off" not in text
        assert "discover_stations" not in text
