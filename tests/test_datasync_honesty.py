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
