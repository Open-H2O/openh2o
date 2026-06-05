# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the prune_dataless_stations management command (59-02 polish)."""

from datetime import datetime, timezone as dt_timezone
from io import StringIO

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command

from datasync.models import DataSource, DataRecordStaging, MonitoredStation

pytestmark = pytest.mark.django_db


def _station(source, ext_id, name):
    return MonitoredStation.objects.create(
        data_source=source,
        external_station_id=ext_id,
        station_name=name,
        location=Point(-120.5, 37.3, srid=4326),
        is_active=True,
    )


def _publish(station, n):
    for i in range(n):
        DataRecordStaging.objects.create(
            data_source=station.data_source,
            station=station,
            raw_data={},
            observation_date=datetime(2026, 1, i + 1, tzinfo=dt_timezone.utc),
            parameter_code="20",
            value=10 + i,
            unit="cfs",
            status="published",
        )


@pytest.fixture
def source():
    return DataSource.objects.create(
        name="CDEC", code="cdec", url="https://x", auth_type="none",
        sync_interval_hours=24, description="",
    )


def test_prunes_zero_and_one_record_stations(source):
    empty = _station(source, "EMPTY", "Empty Gauge")           # 0 records
    thin = _station(source, "THIN", "Thin Gauge"); _publish(thin, 1)   # 1 record
    rich = _station(source, "RICH", "Rich Gauge"); _publish(rich, 5)   # 5 records

    call_command("prune_dataless_stations", stdout=StringIO())

    empty.refresh_from_db(); thin.refresh_from_db(); rich.refresh_from_db()
    assert empty.is_active is False
    assert thin.is_active is False
    assert rich.is_active is True


def test_dry_run_changes_nothing(source):
    empty = _station(source, "EMPTY", "Empty Gauge")

    call_command("prune_dataless_stations", "--dry-run", stdout=StringIO())

    empty.refresh_from_db()
    assert empty.is_active is True


def test_min_records_threshold(source):
    two = _station(source, "TWO", "Two-record Gauge"); _publish(two, 2)

    # Default min=2 keeps it; raising to 3 prunes it.
    call_command("prune_dataless_stations", stdout=StringIO())
    two.refresh_from_db()
    assert two.is_active is True

    call_command("prune_dataless_stations", "--min-records", "3", stdout=StringIO())
    two.refresh_from_db()
    assert two.is_active is False


def test_only_published_records_count(source):
    # Staged-but-not-published rows do not count toward the threshold.
    s = _station(source, "STAGED", "Staged-only Gauge")
    DataRecordStaging.objects.create(
        data_source=source, station=s, raw_data={},
        observation_date=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        parameter_code="20", value=5, unit="cfs", status="staged",
    )

    call_command("prune_dataless_stations", stdout=StringIO())
    s.refresh_from_db()
    assert s.is_active is False
