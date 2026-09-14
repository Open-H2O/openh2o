# SPDX-License-Identifier: AGPL-3.0-or-later
"""Datasync honesty fixes.

P3-1  A sync that fetches records but stages NONE of them (e.g. an upstream
      date-format change makes every record fail in stage) must not report a
      green "success" with zero published.
P3-2  An inactive source is OFF — it must be skipped entirely, never served
      canned mock fixtures that make a dead source look freshly synced.
"""
from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command

from datasync.adapters.usgs import USGSAdapter
from datasync.models import DataSource, DataSyncLog, MonitoredStation


# ---------------------------------------------------------------------------
# P3-2 — mock is decoupled from inactive
# ---------------------------------------------------------------------------


def test_use_mock_ignores_inactive_source(settings):
    settings.DATASYNC_MOCK_MODE = False
    adapter = USGSAdapter()
    # An inactive source no longer silently flips to mock fixtures...
    assert adapter._use_mock(SimpleNamespace(is_active=False)) is False
    # ...only an explicit flag or the global setting enables mock.
    assert adapter._use_mock(SimpleNamespace(is_active=False), mock=True) is True
    settings.DATASYNC_MOCK_MODE = True
    assert adapter._use_mock(SimpleNamespace(is_active=True)) is True


@pytest.mark.django_db
def test_sync_source_skips_inactive_source():
    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=False)
    out = StringIO()
    call_command("sync_source", "usgs", stdout=out, stderr=StringIO())

    assert "inactive" in out.getvalue().lower()
    # No sync ran: no log, no fabricated freshness stamp.
    assert DataSyncLog.objects.filter(data_source=src).count() == 0
    src.refresh_from_db()
    assert src.last_sync_at is None


# ---------------------------------------------------------------------------
# P3-1 — fetched-but-staged-nothing is not a success
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fetched_but_zero_staged_is_not_success(monkeypatch):
    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)
    station = MonitoredStation.objects.create(
        data_source=src,
        external_station_id="X1",
        station_name="Test Station",
        location=Point(-119.5, 36.5),
    )
    adapter = USGSAdapter()
    # Fetch returns data; parse yields records that lack observation_date, so the
    # real stage() drops every one — the exact upstream-format-change scenario.
    monkeypatch.setattr(adapter, "fetch", lambda *a, **k: ["raw"])
    monkeypatch.setattr(adapter, "parse", lambda raw: [{"value": 1.0}, {"value": 2.0}])
    monkeypatch.setattr(adapter, "validate", lambda records: (records, []))

    log = adapter.sync(station, date(2024, 1, 1), date(2024, 1, 7))

    assert log.records_fetched == 2
    assert log.records_staged == 0
    assert log.status != "success"
    assert log.status == "partial"


# ---------------------------------------------------------------------------
# ISS-110 — one reading is "no trend yet", never "no data"
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_station_with_one_reading_is_not_labelled_no_data():
    """The trend slot must not contradict the dot and timestamp beside it.

    A sparkline needs two numeric readings (views.py refuses to draw one from
    fewer). A quarterly source like dwr_sgma gains a point every three months,
    so its stations sit on exactly one reading for a very long time. Calling
    that "No data" denies a reading the same page is displaying.
    """
    from datetime import datetime, timezone as dt_timezone

    from django.test import Client
    from django.urls import reverse

    from core.models import User
    from datasync.models import DataRecordStaging

    src = DataSource.objects.create(
        code="dwr_sgma", name="DWR SGMA Monitoring", is_active=True
    )
    observed = datetime(2026, 3, 23, 12, 0, tzinfo=dt_timezone.utc)
    station = MonitoredStation.objects.create(
        data_source=src,
        external_station_id="SGMA-1",
        station_name="Quarterly Groundwater Well",
        location=Point(-120.5, 37.3),
        is_active=True,
        last_data_at=observed,
    )
    DataRecordStaging.objects.create(
        data_source=src,
        station=station,
        raw_data={},
        observation_date=observed,
        parameter_code="gw_level",
        value="17.2300",
        unit="ft",
        status="published",
    )

    user = User.objects.create(
        username="evaluator-iss110",
        email="evaluator-iss110@example.com",
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    body = client.get(reverse("datasync:monitoring_dashboard")).content.decode()

    assert "Quarterly Groundwater Well" in body
    # The page holds a reading for this station, so it may not claim otherwise.
    assert ">No data<" not in body
    assert "No trend yet" in body

    # Template syntax must never reach the reader. Django's {# #} comment is
    # SINGLE-LINE ONLY; a multi-line one renders its own text onto the page.
    # That shipped to staging on 2026-08-01 and all four promotion gates passed
    # it, because gate 4 looks for 5xx and banned names, not for markup leaking
    # into prose. Only a rendered-body assertion catches this class.
    for leak in ("{#", "#}", "{%", "%}"):
        assert leak not in body, f"template syntax {leak!r} rendered to the page"


# ---------------------------------------------------------------------------
# 143-07: R-074, R-075, R-076: the Monitoring Stations LIST page (the
# freshness map's own list, `datasync:station_list`), not the dashboard
# above. R-074 is the map/list disagreement (does the map draw what the list
# is showing right now); R-075 extends ISS-110's "one reading is not no
# data" rule to the list's own Trend column, which used to print a bare
# `--` for both a one-reading station and a zero-reading one alike; R-076 is
# the list's unheaded, unworded freshness column.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stations_freshness_geojson_serves_every_located_station_active_or_not():
    """Before this plan the endpoint filtered ``is_active=True`` the same way
    the list's own default did, so the two agreed by coincidence (42 = 42 on
    the demonstration) rather than by design: switching the list's Syncing
    filter to "Not syncing" left the map still drawing only the active 42,
    with nothing on screen for the 293 the list was now showing. Every
    located station draws here, active or not, with ``is_active`` riding
    along in properties so the client-side follow helper (which filters by
    the list's own pks) is what actually decides what is on screen."""
    import json as json_module

    from django.test import Client
    from django.urls import reverse

    from core.models import User

    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)
    active = MonitoredStation.objects.create(
        data_source=src, external_station_id="R074-ACT", station_name="R074 Active",
        location=Point(-119.5, 36.5), is_active=True,
    )
    inactive = MonitoredStation.objects.create(
        data_source=src, external_station_id="R074-INA", station_name="R074 Inactive",
        location=Point(-119.6, 36.6), is_active=False,
    )

    user = User.objects.create(
        username="r074-geojson", email="r074-geojson@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)

    data = json_module.loads(
        client.get(reverse("datasync:stations_freshness_geojson")).content
    )
    by_pk = {f["properties"]["pk"]: f["properties"] for f in data["features"]}
    assert set(by_pk) == {active.pk, inactive.pk}, (
        "the geojson endpoint does not serve both the active and the inactive "
        "located station"
    )
    assert by_pk[active.pk]["is_active"] is True
    assert by_pk[inactive.pk]["is_active"] is False


@pytest.mark.django_db
def test_not_syncing_filter_shows_only_the_inactive_station_on_map_and_list():
    """R-074's class: the list's Syncing filter changes which pks the map is
    told to draw, and the head above the map says so in the same words."""
    import json
    import re

    from django.test import Client
    from django.urls import reverse

    from core.models import User

    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)
    MonitoredStation.objects.create(
        data_source=src, external_station_id="R074B-ACT", station_name="R074b Active",
        location=Point(-119.5, 36.5), is_active=True,
    )
    inactive = MonitoredStation.objects.create(
        data_source=src, external_station_id="R074B-INA", station_name="R074b Inactive",
        location=Point(-119.6, 36.6), is_active=False,
    )

    user = User.objects.create(
        username="r074-list", email="r074-list@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)

    body = client.get(
        reverse("datasync:station_list"), {"active": "0"}, HTTP_HX_REQUEST="true"
    ).content.decode()

    match = re.search(
        r'<script[^>]*id="results-map-pks"[^>]*>(.*?)</script>', body, re.DOTALL
    )
    assert match, "no results-map-pks script in the swapped results"
    assert json.loads(match.group(1)) == [inactive.pk], (
        "the map's pks under \"Not syncing\" are not exactly the inactive station"
    )
    assert "not syncing" in body


@pytest.mark.django_db
def test_the_trend_column_never_prints_a_bare_dash_for_one_or_zero_readings():
    """R-075's class on the LIST (ISS-110's fix was the dashboard only).

    A bare ``--`` reads the same for "nothing has ever been recorded" and
    "exactly one reading exists, too few to draw a trend line": the first
    is a real gap, the second denies a reading the row is already showing
    (the timestamp beside it). The two must read differently, and neither
    may be a dash.
    """
    from django.test import Client
    from django.urls import reverse

    from core.models import User
    from datasync.models import DataRecordStaging

    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)
    one_reading = MonitoredStation.objects.create(
        data_source=src, external_station_id="R075-ONE", station_name="R075 One Reading",
        location=Point(-119.5, 36.5), is_active=True,
        last_data_at=timezone_now_utc(),
    )
    DataRecordStaging.objects.create(
        data_source=src, station=one_reading, raw_data={},
        observation_date=timezone_now_utc(), parameter_code="flow",
        value="12.0000", unit="cfs", status="published",
    )
    no_readings = MonitoredStation.objects.create(
        data_source=src, external_station_id="R075-NONE", station_name="R075 No Readings",
        location=Point(-119.6, 36.6), is_active=True,
    )

    user = User.objects.create(
        username="r075", email="r075@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    body = client.get(reverse("datasync:station_list")).content.decode()

    assert "No trend yet" in body, "the one-reading station's Trend cell is not worded"
    assert "No readings" in body, "the zero-reading station's Trend cell is not worded"
    # The table's Trend column (never the syncing toggle switches or anything
    # else on the page) is what must carry no dash. Scoped to the data-table
    # body so an em dash used elsewhere on the page (there is none today, but
    # nothing here should assume so) cannot hide a real regression.
    table = body[body.index('<table class="data-table">') : body.index("</table>")]
    assert "&mdash;" not in table
    assert ">--<" not in table


def timezone_now_utc():
    """A timestamp fresh enough to classify "fresh" for every source's own
    cadence: real "now", not a fixed date, so this file never goes stale
    against `classify_freshness`'s multiplier of the source's expected
    interval."""
    from django.utils import timezone as dj_timezone

    return dj_timezone.now()


@pytest.mark.django_db
def test_the_reporting_column_is_headed_and_worded():
    """R-076: an unheaded coloured-dot column whose meaning lived only in the
    map's own legend box, gone now that the card head above the map is the
    key (a station's own row still needs to say which of the three states it
    is in, in the same word, not just the same colour)."""
    from django.test import Client
    from django.urls import reverse

    from core.models import User

    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)
    MonitoredStation.objects.create(
        data_source=src, external_station_id="R076-1", station_name="R076 Fresh Station",
        location=Point(-119.5, 36.5), is_active=True,
        last_data_at=timezone_now_utc(),
    )

    user = User.objects.create(
        username="r076", email="r076@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    body = client.get(reverse("datasync:station_list")).content.decode()

    table = body[body.index('<table class="data-table">') : body.index("</table>")]
    first_header = table[table.index("<thead>") : table.index("</thead>")]
    assert "<th>Reporting</th>" in first_header, (
        "the first column of the stations table is no longer headed Reporting"
    )
    assert "Up to date" in table
