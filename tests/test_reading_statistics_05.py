# SPDX-License-Identifier: AGPL-3.0-or-later
"""151.6-05: a station keeps every daily statistic its source publishes.

USGS publishes water temperature as a daily high, low and average. The adapter
used to keep one of the three, so a station page showed one number and said
nothing about which. Now every statistic is stored on its own row, the page
names the statistic wherever a station holds more than one for a parameter, and
the chart draws one line per statistic.

The recorded answer is tests/fixtures/usgs_water_data/daily_five_stations.json.
On 11261500, 2026-10-28 the daily high is 17.3, the low 14.3 and the average
15.7. Every station here is a probe station of our own, never a seeded one.
"""

import importlib
import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from core.models import User
from datasync.adapters import get_adapter
from datasync.adapters.registry import get_parameter_label
from datasync.models import DataRecordStaging, DataSource, DataSyncLog, MonitoredStation

FIXTURES = Path(__file__).parent / "fixtures" / "usgs_water_data"
MIGRATION = "datasync.migrations.0008_datarecordstaging_statistic"

DAY = datetime(2026, 10, 28, 12, 0, tzinfo=dt_timezone.utc)


@pytest.fixture
def auth_client():
    user = User.objects.create(
        username="r05-reader", email="r05-reader@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    return client


def _source(code):
    source, _ = DataSource.objects.get_or_create(
        code=code, defaults={"name": f"Probe {code}", "is_active": True}
    )
    return source


def _station(code, external_id, name="Probe station"):
    return MonitoredStation.objects.create(
        data_source=_source(code),
        external_station_id=external_id,
        station_name=name,
        location=Point(-120.0, 37.0),
        is_active=True,
        last_data_at=DAY,
    )


def _row(station, parameter, statistic="", day=DAY, value="1.0000", **extra):
    return DataRecordStaging.objects.create(
        data_source=station.data_source,
        station=station,
        raw_data=extra.pop("raw_data", {}),
        observation_date=day,
        parameter_code=parameter,
        statistic=statistic,
        value=value,
        unit=extra.pop("unit", "deg C"),
        status=extra.pop("status", "published"),
    )


def _stage_recorded_answer(station):
    """Run the recorded USGS answer for 11261500 through parse, validate, stage and publish."""
    answer = json.loads((FIXTURES / "daily_five_stations.json").read_text())
    adapter = get_adapter("usgs")
    records = [r for r in adapter.parse(answer["features"]) if r["station_id"] == "11261500"]
    valid, rejected = adapter.validate(records)
    assert rejected == []
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")
    adapter.stage(valid, log, station)
    adapter.publish(log)


# (a) the recorded answer, end to end -----------------------------------------


def test_recorded_answer_stores_every_temperature_statistic():
    station = _station("usgs", "PROBE-R05-A1")
    _stage_recorded_answer(station)
    day = DataRecordStaging.objects.filter(
        station=station, parameter_code="00010", observation_date__date="2026-10-28"
    )
    assert {r.statistic: float(r.value) for r in day} == {
        "00001": 17.3,
        "00002": 14.3,
        "00003": 15.7,
    }
    flow = DataRecordStaging.objects.get(station=station, parameter_code="00060")
    assert flow.statistic == "00003"
    assert DataRecordStaging.objects.filter(station=station).count() == 6


def test_station_page_names_the_statistic_only_where_there_are_several(auth_client):
    station = _station("usgs", "PROBE-R05-A2")
    _stage_recorded_answer(station)
    body = auth_client.get(reverse("datasync:station_detail", args=[station.pk])).content.decode()

    # Parameters pills carry the unit.
    for words in ("daily high", "daily low", "daily average"):
        assert f'<span class="pill-tag">Water Temperature, {words} (deg C)</span>' in body
    assert '<span class="pill-tag">Discharge (cfs)</span>' in body

    # Current readings tiles carry no unit in the label.
    for words in ("daily high", "daily low", "daily average"):
        assert f">Water Temperature, {words}</div>" in body

    # The readings table names the statistic and carries the unit.
    for words in ("daily high", "daily low", "daily average"):
        assert f"Water Temperature, {words} (deg C)</td>" in body
    assert "Discharge (cfs)</td>" in body

    # Discharge holds one statistic here, so it never names it.
    assert "Discharge, daily" not in body

    # The chart's parameter selects list each parameter once.
    assert body.count('<option value="00010">Water Temperature (deg C)</option>') == 2
    assert body.count('<option value="00060">Discharge (cfs)</option>') == 2


def test_station_page_draws_the_lines_from_tokens(auth_client):
    station = _station("usgs", "PROBE-R05-A3")
    _stage_recorded_answer(station)
    body = auth_client.get(reverse("datasync:station_detail", args=[station.pk])).content.decode()
    assert "token('--color-accent'" in body
    assert "token('--color-deficit'" in body


def test_parameter_label_adds_the_statistic_in_plain_words():
    assert get_parameter_label("usgs", "00010", "00001") == "Water Temperature, daily high (deg C)"
    assert get_parameter_label("usgs", "00010", "00002") == "Water Temperature, daily low (deg C)"
    assert get_parameter_label("usgs", "00010", "00003") == "Water Temperature, daily average (deg C)"
    assert get_parameter_label("usgs", "00010", "00008") == "Water Temperature, daily median (deg C)"
    assert get_parameter_label("usgs", "00010", "00099") == "Water Temperature, statistic 00099 (deg C)"
    assert get_parameter_label("usgs", "00010", "") == "Water Temperature (deg C)"
    assert get_parameter_label("usgs", "00060") == "Discharge (cfs)"


def test_stage_writes_the_statistic_and_a_blank_for_a_source_without_one():
    station = _station("usgs", "PROBE-R05-A4")
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")
    adapter = get_adapter("usgs")
    day = "2026-10-28"
    adapter.stage(
        [
            {"station_id": "x", "observation_date": day, "parameter_code": "00010",
             "value": 1.0, "unit": "deg C", "statistic_id": "00001"},
            {"station_id": "x", "observation_date": day, "parameter_code": "00065",
             "value": 2.0, "unit": "ft"},
            {"station_id": "x", "observation_date": day, "parameter_code": "72019",
             "value": 3.0, "unit": "ft", "statistic_id": None},
        ],
        log,
        station,
    )
    stored = {r.parameter_code: r.statistic for r in DataRecordStaging.objects.filter(station=station)}
    assert stored == {"00010": "00001", "00065": "", "72019": ""}


# (b) the constraint ----------------------------------------------------------


def test_constraint_has_its_new_name():
    names = {c.name for c in DataRecordStaging._meta.constraints}
    assert names == {"uniq_staging_station_param_stat_obsdate"}


def test_constraint_allows_a_high_and_an_average_on_one_day_but_not_the_same_statistic_twice():
    station = _station("usgs", "PROBE-R05-B1")
    _row(station, "00010", "00001")
    _row(station, "00010", "00003")
    with pytest.raises(IntegrityError), transaction.atomic():
        _row(station, "00010", "00001")
    assert DataRecordStaging.objects.filter(station=station).count() == 2


# (c) the migration's rule on old rows ----------------------------------------


def test_migration_sets_the_statistic_on_old_rows_by_the_measured_rule():
    migration = importlib.import_module(MIGRATION)
    usgs = _station("usgs", "PROBE-R05-C1")
    cdec = _station("cdec", "PROBE-R05-C2")
    temp = _row(usgs, "00010")
    flow = _row(usgs, "00060")
    own = _row(usgs, "00010", day=datetime(2026, 10, 27, 12, 0, tzinfo=dt_timezone.utc),
               raw_data={"statistic_id": "00002"})
    stage = _row(usgs, "00065", unit="ft")
    storage = _row(cdec, "15", unit="AF")
    other = _row(cdec, "6", unit="ft", raw_data={"statistic_id": "00008"})

    migration.set_statistics_on_old_rows(django_apps, None)

    got = {r.pk: r.statistic for r in DataRecordStaging.objects.filter(
        pk__in=[temp.pk, flow.pk, own.pk, stage.pk, storage.pk, other.pk])}
    assert got == {
        temp.pk: "00001",
        flow.pk: "00003",
        own.pk: "00002",
        stage.pk: "",
        storage.pk: "",
        other.pk: "00008",
    }

    # Running it again changes nothing.
    migration.set_statistics_on_old_rows(django_apps, None)
    again = {r.pk: r.statistic for r in DataRecordStaging.objects.filter(pk__in=got)}
    assert again == got


def test_migration_leaves_a_statistic_already_set_alone():
    migration = importlib.import_module(MIGRATION)
    usgs = _station("usgs", "PROBE-R05-C3")
    row = _row(usgs, "00010", "00003")
    migration.set_statistics_on_old_rows(django_apps, None)
    row.refresh_from_db()
    assert row.statistic == "00003"


# (d) the reading fixture -----------------------------------------------------


def test_fixture_dump_and_load_round_trip_the_statistic(tmp_path):
    usgs = _station("usgs", "PROBE-R05-D1")
    cdec = _station("cdec", "PROBE-R05-D2")
    _row(usgs, "00010", "00001", value="17.3000")
    _row(usgs, "00010", "00003", value="15.7000")
    _row(cdec, "15", value="900.0000", unit="AF")
    # A second CDEC reading the same day: only the last one survives, as before.
    _row(cdec, "15", value="905.0000", unit="AF",
         day=datetime(2026, 10, 28, 18, 0, tzinfo=dt_timezone.utc))

    path = tmp_path / "readings.json"
    call_command("dump_reading_fixture", output=str(path), start="2026-10-01")
    rows = json.loads(path.read_text())

    mine_usgs = [r for r in rows if r["external_station_id"] == "PROBE-R05-D1"]
    mine_cdec = [r for r in rows if r["external_station_id"] == "PROBE-R05-D2"]
    assert {r["statistic"]: r["value"] for r in mine_usgs} == {"00001": "17.3000", "00003": "15.7000"}
    assert len(mine_cdec) == 1
    assert "statistic" not in mine_cdec[0]
    assert mine_cdec[0]["value"] == "905.0000"

    def held():
        return sorted(
            DataRecordStaging.objects.filter(station__in=[usgs, cdec]).values_list(
                "station__external_station_id", "parameter_code", "statistic",
                "observation_date", "value",
            )
        )

    expected = [t for t in held() if not (t[0] == "PROBE-R05-D2" and str(t[4]) == "900.0000")]
    DataRecordStaging.objects.all().delete()
    call_command("load_reading_fixture", fixture=str(path))
    assert held() == expected


# (e) the chart data ----------------------------------------------------------


def _chart(client, station, **query):
    url = reverse("datasync:station_chart_data", args=[station.pk])
    return client.get(url, query).json()


def test_chart_lists_a_parameter_once_and_draws_a_line_per_statistic(auth_client):
    station = _station("usgs", "PROBE-R05-E1")
    _row(station, "00010", "00001", value="29.5000")
    _row(station, "00010", "00003", value="25.0000")
    data = _chart(auth_client, station, parameter="00010")
    assert [p["code"] for p in data["parameters"]] == ["00010"]
    assert data["parameters"][0]["label"] == "Water Temperature (deg C)"
    assert [d["label"] for d in data["datasets"]] == ["Daily high", "Daily average"]
    assert [d["statistic"] for d in data["datasets"]] == ["00001", "00003"]
    assert [d["data"] for d in data["datasets"]] == [[29.5], [25.0]]
    assert all(d["unit"] == "deg C" for d in data["datasets"])


def test_chart_with_one_statistic_keeps_today_s_label(auth_client):
    station = _station("usgs", "PROBE-R05-E2")
    _row(station, "00060", "00003", value="119.0000", unit="ft3/s")
    data = _chart(auth_client, station, parameter="00060")
    assert [d["label"] for d in data["datasets"]] == ["Discharge (cfs)"]


def test_chart_for_a_source_without_statistics_has_one_line_labelled_as_before(auth_client):
    station = _station("cdec", "PROBE-R05-E3")
    _row(station, "15", value="900.0000", unit="AF")
    data = _chart(auth_client, station, parameter="15")
    assert [d["label"] for d in data["datasets"]] == ["Reservoir Storage (AF)"]
    assert len(data["datasets"]) == 1


def test_chart_compare_parameter_is_named_by_statistic_when_it_has_several(auth_client):
    station = _station("usgs", "PROBE-R05-E4")
    _stage_recorded_answer(station)

    data = _chart(auth_client, station, parameter="00060", parameter2="00010")
    assert [(d["label"], d["axis"]) for d in data["datasets"]] == [
        ("Discharge (cfs)", "y"),
        ("Water Temperature, daily high", "y1"),
        ("Water Temperature, daily low", "y1"),
        ("Water Temperature, daily average", "y1"),
    ]

    data = _chart(auth_client, station, parameter="00010", parameter2="00060")
    assert [(d["label"], d["axis"]) for d in data["datasets"]] == [
        ("Daily high", "y"),
        ("Daily low", "y"),
        ("Daily average", "y"),
        ("Discharge (cfs)", "y1"),
    ]
