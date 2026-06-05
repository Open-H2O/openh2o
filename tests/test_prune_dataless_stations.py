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


def test_delete_flag_removes_dataless_station(source):
    empty = _station(source, "EMPTY", "Empty Gauge")
    rich = _station(source, "RICH", "Rich Gauge"); _publish(rich, 5)

    call_command("prune_dataless_stations", "--delete", stdout=StringIO())

    assert not MonitoredStation.objects.filter(pk=empty.pk).exists()  # gone, not hidden
    assert MonitoredStation.objects.filter(pk=rich.pk, is_active=True).exists()


def test_purge_inactive_deletes_inactive_keeps_active(source):
    inactive = _station(source, "OLD", "Wide-net Gauge"); inactive.is_active = False; inactive.save()
    rich = _station(source, "RICH", "Rich Gauge"); _publish(rich, 5)

    call_command("prune_dataless_stations", "--purge-inactive", stdout=StringIO())

    assert not MonitoredStation.objects.filter(pk=inactive.pk).exists()
    assert MonitoredStation.objects.filter(pk=rich.pk, is_active=True).exists()


def test_chart_data_only_offers_measured_parameters(source):
    """The chart dropdown must not offer a declared sensor the site never reports."""
    from django.test import Client
    from core.models import User

    # Declared for two sensors, but only publishes one of them.
    s = _station(source, "SWA", "Reservoir Gauge")
    s.parameters = ["15", "76"]  # 15=storage (measured), 76=inflow (declared, never measured)
    s.save()
    _publish(s, 3)  # _publish writes parameter_code "20"... set to the declared 15 instead
    DataRecordStaging.objects.filter(station=s).update(parameter_code="15")

    user = User.objects.create_user("p", "p@example.com", "pw12345")
    c = Client(); c.force_login(user)
    resp = c.get(f"/datasync/stations/{s.pk}/chart-data/")
    codes = {p["code"] for p in resp.json()["parameters"]}
    assert "15" in codes
    assert "76" not in codes  # declared-but-unmeasured sensor is NOT offered
