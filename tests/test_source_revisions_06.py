# SPDX-License-Identifier: AGPL-3.0-or-later
"""Revisions from the source (151.7-06).

When a gauge, weather station or well-level operator revises a reading it
published, OpenH2O keeps the first reading, marks it replaced, and records the
revised one beside it. The station page shows both; the chart, the lists, the
map and the totals read only the current one.

These tests drive real code: the adapters' own ``fetch``, ``parse`` and
``validate`` run, with the HTTP layer (``_request``) replaced by a recorded
answer, and ``sync_source`` and ``load_reading_fixture`` run as commands. Nothing
here touches the network. Module-level imports are limited to code that exists
on the base commit, so the file collects there and fails on the missing feature.
"""

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from html import unescape
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import IntegrityError, models, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from core.models import User
from datasync.adapters import get_adapter
from datasync.adapters.base import BaseAdapter
from datasync.adapters.cdec import CDECAdapter
from datasync.adapters.usgs import USGSAdapter
from datasync.models import DataRecordStaging, DataSource, DataSyncLog, MonitoredStation

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent

#: USGS puts these on a value it changed. 03:30 UTC on Nov 4 is Nov 3 in the site's zone.
MOD1 = "2026-11-04T03:30:00.512749+00:00"
MOD1_WORDS = "Nov 3, 2026"
MOD2 = "2026-11-05T20:00:00+00:00"
MOD2_WORDS = "Nov 5, 2026"


# -- Helpers -------------------------------------------------------------------------------


def _words(day):
    """A date as the revised-readings list prints it: Nov 3, 2026."""
    return f"{day:%b} {day.day}, {day.year}"


def _card_date(day):
    """A date as the readings card prints it (its existing "M d, Y" format): Nov 03, 2026."""
    return f"{day:%b %d, %Y}"


def _midnight(day):
    return timezone.make_aware(datetime(day.year, day.month, day.day))


def _text(markup):
    """The visible words of some markup, one space between words."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _source(code="usgs", name=None, active=True):
    names = {"usgs": "USGS NWIS", "cdec": "CDEC", "manual": "Entered by hand"}
    source, _ = DataSource.objects.get_or_create(code=code, defaults={"name": name or names.get(code, code)})
    source.is_active = active
    source.save()
    return source


def _station(source=None, external="11261100", name="SALT SLOUGH TEST GAUGE", **extra):
    source = source or _source()
    return MonitoredStation.objects.create(
        data_source=source,
        external_station_id=external,
        station_name=name,
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


@pytest.fixture
def operator():
    return _user("operator")


@pytest.fixture
def viewer():
    return _user("viewer", read_only=True)


@pytest.fixture
def admin():
    return _user("admin-user", agency_admin=True)


@pytest.fixture
def ref():
    ld.seed_reference()


class _Response:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


@pytest.fixture
def usgs_api(monkeypatch):
    """Replace the USGS HTTP layer with a recorded answer.

    ``usgs_api.features`` is what every request returns; ``usgs_api.calls`` holds
    the query of each request, so a test can read what was asked.
    """

    class Api:
        features = []
        calls = []

    def fake_request(self, method, url, **kwargs):
        Api.calls.append(dict(kwargs.get("params") or {}))
        return _Response({"features": list(Api.features), "links": []})

    Api.features, Api.calls = [], []
    monkeypatch.setattr(USGSAdapter, "_request", fake_request)
    return Api


@pytest.fixture
def cdec_api(monkeypatch):
    class Api:
        items = []
        calls = []

    def fake_request(self, method, url, **kwargs):
        Api.calls.append(dict(kwargs.get("params") or {}))
        return _Response(list(Api.items))

    Api.items, Api.calls = [], []
    monkeypatch.setattr(CDECAdapter, "_request", fake_request)
    return Api


def _feature(site, day, value, *, code="00060", statistic="00003", unit="ft^3/s", modified=None):
    props = {
        "monitoring_location_id": f"USGS-{site}",
        "time": str(day),
        "value": None if value is None else str(value),
        "parameter_code": code,
        "statistic_id": statistic,
        "unit_of_measure": unit,
        "approval_status": "Provisional",
    }
    if modified is not None:
        props["last_modified"] = modified
    return {"type": "Feature", "properties": props}


def _cdec_item(site, day, value, sensor=15, units="AF"):
    return {
        "stationId": site,
        "SENSOR_NUM": sensor,
        "obsDate": f"{day} 00:00",
        "value": value,
        "units": units,
    }


def _record(external, day, value=12.5, *, code="00060", statistic="00003", unit="ft3/s", **extra):
    """A validated record in the shape ``stage`` takes."""
    return {
        "station_id": external,
        "observation_date": str(day),
        "parameter_code": code,
        "value": value,
        "unit": unit,
        "statistic_id": statistic,
        **extra,
    }


def _usgs_sync(api, station, features):
    api.features = features
    return get_adapter("usgs").sync(station, date(2026, 1, 1), date(2026, 11, 5))


def _cdec_sync(api, station, items):
    api.items = items
    return get_adapter("cdec").sync(station, date(2026, 10, 1), date(2026, 11, 5))


def _store(station, day, value, *, code="00060", statistic="00003", unit="ft3/s", status="published", raw=None):
    """One reading stored the way a first fetch stores it, written straight to the table."""
    return DataRecordStaging.objects.create(
        data_source=station.data_source,
        station=station,
        raw_data=raw or {},
        observation_date=_midnight(day),
        parameter_code=code,
        statistic=statistic,
        value=None if value is None else D(str(value)),
        unit=unit,
        status=status,
        published_at=timezone.now() if status == "published" else None,
    )


def _revised_chains(
    station, count, *, first_day=date(2026, 1, 1), code="00060", statistic="00003",
    unit="ft3/s", modified=MOD1, old_base=10, new_base=20, word="USGS",
):
    """``count`` readings that each have a replaced first row and a current revised one."""
    source = station.data_source
    olds = DataRecordStaging.objects.bulk_create([
        DataRecordStaging(
            data_source=source, station=station, raw_data={},
            observation_date=_midnight(first_day + timedelta(days=i)),
            parameter_code=code, statistic=statistic, value=D(old_base + i), unit=unit,
            status="published", published_at=timezone.now(),
        )
        for i in range(count)
    ])
    DataRecordStaging.objects.filter(pk__in=[o.pk for o in olds]).update(replaced_at=timezone.now())
    news = DataRecordStaging.objects.bulk_create([
        DataRecordStaging(
            data_source=source, station=station,
            raw_data={"last_modified": modified} if modified else {},
            observation_date=_midnight(first_day + timedelta(days=i)),
            parameter_code=code, statistic=statistic, value=D(new_base + i), unit=unit,
            status="published", published_at=timezone.now(), replaces=old,
            change_reason=f"Revised by {word} Nov 3, 2026",
        )
        for i, old in enumerate(olds)
    ])
    return olds, news


def _rows(station):
    return list(DataRecordStaging.objects.filter(station=station).order_by("pk"))


def _at(station, day, **extra):
    return list(
        DataRecordStaging.objects.filter(station=station, observation_date=_midnight(day), **extra).order_by("pk")
    )


def _station_url(station):
    return reverse("datasync:station_detail", args=[station.pk])


def _revised_url(station):
    return reverse("datasync:station_revised", args=[station.pk])


def _get(client, url):
    response = client.get(url)
    assert response.status_code == 200, response.status_code
    return response.content.decode()


def _card_rows(body):
    """The ``<tr>`` of the Readings card's tbody, as markup."""
    start = body.index('id="station-readings-card"')
    end = body.index("</table>", start)
    segment = body[start:end]
    return re.findall(r"<tr\b.*?</tr>", segment[segment.index("<tbody"):], re.S)


def _main_rows(body):
    """The ``<tr>`` of the first table inside ``<main>``'s tbody."""
    main = body[body.index("<main"):]
    start = main.index("<table")
    end = main.index("</table>", start)
    segment = main[start:end]
    return re.findall(r"<tr\b.*?</tr>", segment[segment.index("<tbody"):], re.S)


def _cells(row):
    return [_text(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S)]


def _headers(body):
    main = body[body.index("<main"):]
    head = main[main.index("<thead"):main.index("</thead>")]
    return [_text(cell) for cell in re.findall(r"<th\b[^>]*>(.*?)</th>", head, re.S)]


def _press(client, station):
    """Press Fetch readings now (the suite runs the fetch in-process); return the status paragraph's markup."""
    client.post(reverse("datasync:station_fetch_now", args=[station.pk]))
    log = DataSyncLog.objects.filter(station=station).order_by("-pk").first()
    body = client.get(reverse("datasync:station_fetch_status", args=[station.pk, log.pk])).content.decode()
    found = re.search(r'<p[^>]*id="fetch-status"[^>]*>(.*?)</p>', body, re.S)
    assert found, "the fetch block carries no status line"
    return found.group(1)


def _run_sync(*args, code="usgs"):
    out = StringIO()
    call_command("sync_source", code, *args, stdout=out)
    return out.getvalue()


def _last_log():
    return DataSyncLog.objects.filter(station__isnull=True).order_by("-pk").first()


# -- The registry: a source's reading is not a record a person voids or corrects ------------------


def test_published_reading_is_not_a_kind_in_the_correction_registry():
    from core import correction_forms, corrections

    assert "published_reading" not in corrections.KINDS
    assert "datasync.DataRecordStaging" not in {k["model"] for k in corrections.KINDS.values()}
    assert correction_forms.has_screen("published_reading") is False


@pytest.mark.parametrize("route", ["record_void", "record_correct"])
def test_a_press_to_void_or_correct_a_source_reading_gets_the_404_any_unknown_kind_gets(route, operator):
    station = _station()
    olds, news = _revised_chains(station, 1)
    before = list(DataRecordStaging.objects.order_by("pk").values())
    url = reverse(f"core:{route}", args=["published_reading", news[0].pk])
    data = {"void_reason": "typed on the wrong record", "reason": "typed on the wrong record"}

    response = _client(operator).post(url, data, HTTP_HX_REQUEST="true")
    unknown = _client(operator).post(
        reverse(f"core:{route}", args=["no_such_kind", news[0].pk]), data, HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 404 == unknown.status_code
    assert list(DataRecordStaging.objects.order_by("pk").values()) == before


def test_a_revised_reading_is_not_in_the_year_s_corrections_or_in_change_history(admin):
    from accounting.statements import corrections_since
    from tests.factories import ReportingPeriodFactory

    station = _station()
    _revised_chains(station, 2, first_day=date(2026, 10, 1))
    period = ReportingPeriodFactory(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    since = timezone.now() - timedelta(days=30)

    assert corrections_since(period, since, all_records=True) == []

    body = _get(_client(admin), reverse("change_history"))
    assert "published reading" not in _text(body).lower()


def test_published_readings_are_not_a_part_of_the_year_s_stored_code():
    from core import fingerprint as year_code

    assert "datasync.DataRecordStaging" not in year_code.COVERED_MODELS


# -- (a) a changed value is a replacement ------------------------------------------------------


def test_a_second_answer_with_one_changed_value_writes_a_replacement_and_leaves_the_old_row(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5, modified="2026-10-31T01:00:00+00:00")])
    (first,) = _rows(station)
    snapshot = {k: v for k, v in DataRecordStaging.objects.filter(pk=first.pk).values().get().items()}

    log = _usgs_sync(usgs_api, station, [_feature("11261100", day, 14.0, modified=MOD1)])

    old, new = _rows(station)
    assert old.pk == first.pk
    # The old row's figures and everything else are untouched; only the marking column moved.
    after = DataRecordStaging.objects.filter(pk=old.pk).values().get()
    assert after.pop("replaced_at") is not None
    assert snapshot.pop("replaced_at") is None
    assert after == snapshot
    assert old.value == D("12.5000")
    assert old.status == "published"
    assert old.raw_data["value"] == 12.5
    assert new.replaces_id == old.pk
    assert new.value == D("14.0000")
    assert new.status == "published"
    assert new.replaced_at is None
    assert new.change_reason == "Revised by USGS Nov 3, 2026"
    assert list(DataRecordStaging.objects.current()) == [new]
    assert (log.records_new, log.records_revised) == (0, 1)
    assert log.records_staged == 1
    assert log.records_published == 1


def test_a_revision_the_source_did_not_date_says_when_it_was_fetched(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 14.0)])

    new = _rows(station)[1]

    assert new.change_reason == f"Revised by USGS, fetched {_words(timezone.localdate())}"


def test_the_sources_date_reaches_raw_data_and_is_read_in_the_sites_zone(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    adapter = get_adapter("usgs")
    parsed = adapter.parse([_feature("11261100", day, 12.5, modified=MOD1)])
    assert parsed[0]["last_modified"] == MOD1

    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5, modified=MOD1)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 14.0, modified=MOD1)])

    old, new = _rows(station)
    assert old.raw_data["last_modified"] == MOD1
    assert new.raw_data["last_modified"] == MOD1
    # 03:30 UTC on Nov 4 is the evening of Nov 3 in the site's zone, not Nov 4.
    assert new.change_reason == "Revised by USGS Nov 3, 2026"
    assert "Nov 4" not in new.change_reason


def test_the_reason_names_the_source_by_its_display_name_where_the_source_has_no_date(cdec_api):
    station = _station(_source("cdec"), "BUR", "BULLARDS TEST")
    station.parameters = ["15"]
    station.save()
    _cdec_sync(cdec_api, station, [_cdec_item("BUR", "2026-10-30", 100.0)])
    _cdec_sync(cdec_api, station, [_cdec_item("BUR", "2026-10-30", 105.0)])

    old, new = _rows(station)

    assert new.replaces_id == old.pk
    assert new.change_reason == f"Revised by CDEC, fetched {_words(timezone.localdate())}"


def test_stage_alone_marks_the_old_row_and_leaves_the_revision_staged_until_publish(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5)])
    adapter = get_adapter("usgs")
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")

    processed = adapter.stage([_record("11261100", day, 14.0)], log, station)

    old, new = _rows(station)
    assert processed == 1
    assert old.replaced_at is not None
    assert new.status == "staged"
    assert new.replaces_id == old.pk
    assert (log.records_new, log.records_revised) == (0, 1)
    adapter.publish(log, station=station)
    assert list(DataRecordStaging.objects.current()) == [DataRecordStaging.objects.get(pk=new.pk)]
    assert DataRecordStaging.objects.get(pk=new.pk).status == "published"


def test_the_same_changed_answer_twice_replaces_once(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 14.0, modified=MOD1)])
    log = _usgs_sync(usgs_api, station, [_feature("11261100", day, 14.0, modified=MOD1)])

    assert len(_rows(station)) == 2
    assert (log.records_new, log.records_revised) == (0, 0)


def test_three_values_in_turn_make_a_chain_with_one_current_row(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 10.0)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 11.0, modified=MOD1)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.0, modified=MOD2)])

    first, second, third = _rows(station)

    assert (first.value, second.value, third.value) == (D("10.0000"), D("11.0000"), D("12.0000"))
    assert second.replaces_id == first.pk
    assert third.replaces_id == second.pk
    assert first.replaced_at is not None and second.replaced_at is not None
    assert third.replaced_at is None
    assert list(DataRecordStaging.objects.current()) == [third]


# -- (b) the same value writes nothing ---------------------------------------------------------


def test_the_same_value_writes_nothing_and_still_counts_as_staged(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5)])
    before = list(DataRecordStaging.objects.order_by("pk").values())

    log = _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5, modified=MOD1)])

    assert list(DataRecordStaging.objects.order_by("pk").values()) == before
    # An all-duplicates run is a run that staged what it was given, not a run that staged none.
    assert log.records_staged == 1
    assert (log.records_new, log.records_revised) == (0, 0)
    assert log.error_message == ""


def test_a_run_of_only_known_readings_is_a_success_not_a_partial(usgs_api):
    _station()
    today = date.today()
    usgs_api.features = [_feature("11261100", today - timedelta(days=2), 12.5)]
    _run_sync()
    _run_sync()

    log = _last_log()

    assert log.status == "success"
    assert log.records_fetched == 1
    assert log.records_staged == 1
    assert (log.records_new, log.records_revised) == (0, 0)


def test_a_new_day_beside_a_known_one_is_new(usgs_api):
    station = _station()
    _usgs_sync(usgs_api, station, [_feature("11261100", date(2026, 10, 29), 8.0)])

    log = _usgs_sync(usgs_api, station, [
        _feature("11261100", date(2026, 10, 29), 8.0),
        _feature("11261100", date(2026, 10, 30), 9.0),
    ])

    assert len(_rows(station)) == 2
    assert (log.records_new, log.records_revised) == (1, 0)
    assert log.records_staged == 2


@pytest.mark.parametrize("figure", [26.12345, 26.12355, -26.12345, -26.12355, 0.00005, 100.0])
def test_a_value_that_rounds_to_the_stored_figure_is_not_a_revision(usgs_api, figure):
    """The comparison goes through the column's own rounding, so a tie cannot disagree with what was stored."""
    station = _station()
    day = date(2026, 10, 30)
    adapter = get_adapter("usgs")
    first = DataSyncLog.objects.create(data_source=station.data_source, status="running")
    second = DataSyncLog.objects.create(data_source=station.data_source, status="running")

    adapter.stage([_record("11261100", day, figure)], first, station)
    adapter.stage([_record("11261100", day, figure)], second, station)

    assert len(_rows(station)) == 1
    assert (first.records_new, first.records_revised) == (1, 0)
    assert (second.records_new, second.records_revised) == (0, 0)
    assert _rows(station)[0].replaced_at is None


def test_a_value_that_differs_at_the_fourth_place_is_a_revision(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    adapter = get_adapter("usgs")
    adapter.stage([_record("11261100", day, 26.1235)], DataSyncLog.objects.create(
        data_source=station.data_source, status="running"), station)
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")

    adapter.stage([_record("11261100", day, 26.1236)], log, station)

    assert len(_rows(station)) == 2
    assert log.records_revised == 1


def test_the_same_value_under_another_unit_label_is_not_a_revision(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5, unit="ft^3/s")])

    log = _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5, unit="cfs", modified=MOD1)])

    (only,) = _rows(station)
    assert only.unit == "ft3/s"
    assert only.replaced_at is None
    assert log.records_revised == 0


def test_a_blank_never_replaces_a_figure(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5)])
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")

    get_adapter("usgs").stage([_record("11261100", day, None)], log, station)

    (only,) = _rows(station)
    assert only.value == D("12.5000")
    assert only.replaced_at is None
    assert (log.records_new, log.records_revised) == (0, 0)


def test_a_figure_replaces_a_stored_blank(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _store(station, day, None)

    log = _usgs_sync(usgs_api, station, [_feature("11261100", day, 5.0, modified=MOD1)])

    blank, figure = _rows(station)
    assert blank.value is None and blank.replaced_at is not None
    assert figure.value == D("5.0000") and figure.replaces_id == blank.pk
    assert log.records_revised == 1


def test_duplicate_keys_inside_one_batch_keep_the_first(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")

    processed = get_adapter("usgs").stage(
        [
            _record("11261100", day, 10.0),
            _record("11261100", day, 11.0),
            _record("11261100", date(2026, 10, 31), 12.0),
        ],
        log,
        station,
    )

    assert processed == 3
    rows = _rows(station)
    assert [r.value for r in rows] == [D("10.0000"), D("12.0000")]
    assert (log.records_new, log.records_revised) == (2, 0)


def test_duplicate_keys_inside_one_batch_make_one_revision_not_two(usgs_api):
    station = _station()
    day = date(2026, 10, 30)
    _store(station, day, 5.0)
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")

    get_adapter("usgs").stage(
        [_record("11261100", day, 6.0), _record("11261100", day, 7.0)], log, station
    )

    old, new = _rows(station)
    assert new.value == D("6.0000")
    assert log.records_revised == 1


def _stage_query_count(count):
    station = _station(external=f"Q{count}", name=f"Station {count}")
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(count)]
    DataRecordStaging.objects.bulk_create([
        DataRecordStaging(
            data_source=station.data_source, station=station, raw_data={},
            observation_date=_midnight(day), parameter_code="00060", statistic="00003",
            value=D("1"), unit="ft3/s", status="published", published_at=timezone.now(),
        )
        for day in days
    ])
    records = []
    for i, day in enumerate(days):
        records.append(_record(station.external_station_id, day, 1.0 if i % 3 == 0 else 2.0))
    for i in range(count // 3):
        records.append(_record(station.external_station_id, date(2027, 1, 1) + timedelta(days=i), 3.0))
    log = DataSyncLog.objects.create(data_source=station.data_source, status="running")
    with CaptureQueriesContext(connection) as queries:
        get_adapter("usgs").stage(records, log, station)
    assert log.records_revised == count - (count + 2) // 3
    assert log.records_new == count // 3
    return len(queries)


def test_staging_asks_the_database_the_same_number_of_questions_for_6_rows_or_300():
    assert _stage_query_count(6) == _stage_query_count(300)


def test_two_current_rows_for_one_key_cannot_both_be_stored():
    station = _station()
    day = date(2026, 10, 30)
    first = _store(station, day, 1.0)
    with pytest.raises(IntegrityError), transaction.atomic():
        _store(station, day, 2.0)
    # Once the first is marked replaced, a second row for the key is the revision.
    DataRecordStaging.objects.filter(pk=first.pk).update(replaced_at=timezone.now())
    _store(station, day, 2.0)
    assert DataRecordStaging.objects.filter(station=station).count() == 2


def test_stage_and_publish_roll_back_together_when_publish_fails(usgs_api, monkeypatch):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5)])
    before = list(DataRecordStaging.objects.order_by("pk").values())
    real_publish = BaseAdapter.publish

    def publish_then_fail(self, sync_log, station=None):
        real_publish(self, sync_log, station=station)
        raise RuntimeError("publish stopped")

    monkeypatch.setattr(BaseAdapter, "publish", publish_then_fail)
    usgs_api.features = [
        _feature("11261100", day, 14.0, modified=MOD1),
        _feature("11261100", date(2026, 10, 31), 9.0),
    ]
    log = get_adapter("usgs").sync(station, date(2026, 1, 1), date(2026, 11, 5))

    # A reader never sees a replaced row whose replacement is missing or still staged.
    assert list(DataRecordStaging.objects.order_by("pk").values()) == before
    assert "publish stopped" in log.error_message
    monkeypatch.setattr(BaseAdapter, "publish", real_publish)

    again = get_adapter("usgs").sync(station, date(2026, 1, 1), date(2026, 11, 5))

    assert again.error_message == ""
    assert (again.records_new, again.records_revised) == (1, 1)
    assert DataRecordStaging.objects.current().count() == 2


# -- USGS asks what changed ----------------------------------------------------------------------


def test_usgs_declares_that_it_asks_what_changed_and_no_other_adapter_does():
    from datasync.adapters import ADAPTER_REGISTRY

    assert USGSAdapter.asks_what_changed is True
    others = {code: cls for code, cls in ADAPTER_REGISTRY.items() if code != "usgs"}
    assert others
    assert not [code for code, cls in others.items() if getattr(cls, "asks_what_changed", False)]


def test_a_default_run_asks_usgs_for_what_changed_in_seven_days_and_sends_no_dates(usgs_api):
    _station()
    usgs_api.features = []

    _run_sync()

    (query,) = usgs_api.calls
    assert query["last_modified"] == "P7D"
    assert "datetime" not in query


def test_a_run_with_a_start_date_stays_a_date_range(usgs_api):
    _station()

    _run_sync("--start", "2026-10-01", "--end", "2026-11-05")

    (query,) = usgs_api.calls
    assert query["datetime"] == "2026-10-01/2026-11-05"
    assert "last_modified" not in query


@pytest.mark.parametrize("args", [("--end", "2026-11-05"), ("--start", "2026-10-01")])
def test_a_run_with_either_date_is_a_date_range(usgs_api, args):
    _station()

    _run_sync(*args)

    (query,) = usgs_api.calls
    assert "datetime" in query
    assert "last_modified" not in query


def test_a_one_station_run_from_the_page_takes_the_scheduled_path(usgs_api, operator):
    station = _station()

    _client(operator).post(reverse("datasync:station_fetch_now", args=[station.pk]))

    (query,) = usgs_api.calls
    assert query["last_modified"] == "P7D"
    assert "datetime" not in query


def test_another_source_sends_the_request_it_always_sent(cdec_api):
    station = _station(_source("cdec"), "BUR", "BULLARDS TEST")
    station.parameters = ["15"]
    station.save()

    _run_sync(code="cdec")

    # CDEC asks once per duration code; every ask is the request it always sent.
    assert cdec_api.calls
    assert all(set(query) == {"Stations", "SensorNums", "dur_code", "Start", "End"} for query in cdec_api.calls)


def test_a_reading_dated_before_the_window_that_is_not_stored_is_not_added_on_a_default_run(usgs_api):
    station = _station()
    today = date.today()
    usgs_api.features = [_feature("11261100", today - timedelta(days=30), 5.0, modified=MOD1)]

    _run_sync()

    assert _rows(station) == []
    log = _last_log()
    assert (log.records_new, log.records_revised) == (0, 0)


def test_the_same_reading_is_added_when_the_run_names_a_start_date(usgs_api):
    station = _station()
    today = date.today()
    usgs_api.features = [_feature("11261100", today - timedelta(days=30), 5.0, modified=MOD1)]

    _run_sync("--start", str(today - timedelta(days=60)))

    assert len(_rows(station)) == 1
    assert _last_log().records_new == 1


def test_a_reading_inside_the_window_is_new(usgs_api):
    station = _station()
    today = date.today()
    usgs_api.features = [_feature("11261100", today - timedelta(days=2), 5.0, modified=MOD1)]

    _run_sync()

    assert len(_rows(station)) == 1
    assert _last_log().records_new == 1


def test_a_stored_reading_older_than_the_window_can_still_be_revised(usgs_api):
    station = _station()
    old_day = date.today() - timedelta(days=30)
    _store(station, old_day, 4.0)
    usgs_api.features = [_feature("11261100", old_day, 5.0, modified=MOD1)]

    _run_sync()

    old, new = _rows(station)
    assert new.replaces_id == old.pk
    log = _last_log()
    assert (log.records_new, log.records_revised) == (0, 1)


def test_the_printed_line_adds_the_revised_count(usgs_api):
    station = _station()
    old_day = date.today() - timedelta(days=30)
    _store(station, old_day, 4.0)
    usgs_api.features = [_feature("11261100", old_day, 5.0, modified=MOD1)]

    printed = _run_sync()

    assert re.search(r"\b1 revised\b", printed), printed


def test_mock_mode_is_not_filtered_by_the_window(usgs_api):
    station = _station()

    _run_sync("--mock")

    assert usgs_api.calls == []
    # The offline fixture is dated 2024; a default run still stages every reading that
    # validates and has its own key, however old.
    keys = {
        (r["parameter_code"], r.get("statistic_id", ""), r["observation_date"])
        for r in json.loads((ROOT / "datasync/fixtures/usgs.json").read_text())["records"]
        if r["value"] is not None and r["value"] >= -999
    }
    assert len(keys) > 1
    assert len(_rows(station)) == len(keys)
    assert _last_log().records_new == len(keys)


# -- (c) the station page --------------------------------------------------------------------------


def _revised_station_page(usgs_api, operator):
    """A USGS station with one revised day (Oct 30) and one unrevised day (Oct 29)."""
    station = _station()
    first = [_feature("11261100", date(2026, 10, 30), 12.5), _feature("11261100", date(2026, 10, 29), 8.0)]
    _usgs_sync(usgs_api, station, first)
    second = [
        _feature("11261100", date(2026, 10, 30), 14.0, modified=MOD1),
        _feature("11261100", date(2026, 10, 29), 8.0, modified=MOD1),
    ]
    _usgs_sync(usgs_api, station, second)
    return station, _get(_client(operator), _station_url(station))


def test_the_station_page_shows_the_new_value_the_struck_first_one_a_revised_status_and_the_foot(
    usgs_api, operator
):
    station, body = _revised_station_page(usgs_api, operator)

    rows = _card_rows(body)
    assert len(rows) == 2
    revised, plain = rows
    assert _card_date(date(2026, 10, 30)) in _text(revised)
    cells = _cells(revised)
    assert cells[2].startswith("14.00 ft3/s")
    assert "record-void-text text-xs" in revised
    struck = re.search(r'<div class="record-void-text text-xs">(.*?)</div>', revised, re.S).group(1)
    assert _text(struck) == "12.50 ft3/s"
    assert cells[3] == "Revised"
    assert "background: var(--color-elevated)" in revised
    assert "record-void-text" not in plain
    assert _cells(plain)[3] == "Published"
    assert "rgba(34,197,94,0.1)" in plain
    # No row menu on a reading a source sent.
    assert "row-actions" not in body[body.index('id="station-readings-card"'):]

    text = _text(body)
    assert "USGS revised 1 reading after OpenH2O first fetched it." in text
    link = re.search(r'<a [^>]*href="([^"]+)"[^>]*>1 reading</a>', body)
    assert link and link.group(1) == _revised_url(station)


def test_a_station_with_no_revision_shows_no_struck_figure_and_no_foot_line(usgs_api, operator):
    station = _station()
    _usgs_sync(usgs_api, station, [_feature("11261100", date(2026, 10, 30), 12.5)])

    body = _get(_client(operator), _station_url(station))

    assert "record-void-text" not in body[body.index('id="station-readings-card"'):]
    assert "after OpenH2O first fetched" not in _text(body)
    assert "Revised" not in _text(body[body.index('id="station-readings-card"'):])


def test_the_foot_counts_every_revised_reading_of_the_station_not_only_the_ten_shown(operator):
    station = _station()
    _revised_chains(station, 94)

    body = _get(_client(operator), _station_url(station))

    assert "USGS revised 94 readings after OpenH2O first fetched them." in _text(body)
    assert re.search(r'<a [^>]*href="%s"[^>]*>94 readings</a>' % re.escape(_revised_url(station)), body)
    assert len(_card_rows(body)) == 10


def test_the_ten_newest_are_current_rows_so_a_revised_day_takes_one_line(operator):
    station = _station()
    _revised_chains(station, 12)

    rows = _card_rows(_get(_client(operator), _station_url(station)))

    dates = [_cells(row)[0] for row in rows]
    assert len(rows) == 10
    assert len(set(dates)) == 10
    newest = date(2026, 1, 1) + timedelta(days=11)
    assert dates[0] == _card_date(newest)
    # The newest day's current value is the revised one (new_base 20 + 11).
    assert _cells(rows[0])[2].startswith("31.00")


def test_a_chain_of_three_shows_the_first_value_struck_not_the_second(usgs_api, operator):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 10.0)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 11.0, modified=MOD1)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.0, modified=MOD2)])

    body = _get(_client(operator), _station_url(station))

    (row,) = _card_rows(body)
    assert _cells(row)[2].startswith("12.00")
    struck = re.search(r'<div class="record-void-text text-xs">(.*?)</div>', row, re.S).group(1)
    assert _text(struck) == "10.00 ft3/s"
    assert "11.00" not in row
    # One reading has a replaced predecessor, however long its chain.
    assert "USGS revised 1 reading after OpenH2O first fetched it." in _text(body)


def test_a_stored_blank_that_was_revised_shows_not_recorded_struck(usgs_api, operator):
    station = _station()
    day = date(2026, 10, 30)
    _store(station, day, None)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 5.0, modified=MOD1)])

    (row,) = _card_rows(_get(_client(operator), _station_url(station)))

    struck = re.search(r'<div class="record-void-text text-xs">(.*?)</div>', row, re.S).group(1)
    assert _text(struck) == "Not recorded"
    assert _cells(row)[2].startswith("5.00")


def test_a_source_that_dates_nothing_names_itself_in_the_foot(cdec_api, operator):
    station = _station(_source("cdec"), "BUR", "BULLARDS TEST")
    station.parameters = ["15"]
    station.save()
    _cdec_sync(cdec_api, station, [_cdec_item("BUR", "2026-10-30", 100.0)])
    _cdec_sync(cdec_api, station, [_cdec_item("BUR", "2026-10-30", 105.0)])

    body = _get(_client(operator), _station_url(station))

    assert "CDEC revised 1 reading after OpenH2O first fetched it." in _text(body)


def test_a_station_entered_by_hand_keeps_its_card(operator):
    station = _station(_source("manual"), "HAND-1", "HAND GAUGE")
    _store(station, date(2026, 10, 30), 3.5, code="00065", statistic="", unit="ft")

    body = _get(_client(operator), _station_url(station))

    card = body[body.index('id="station-readings-card"'):]
    assert "record-void-text" not in card
    assert "after OpenH2O first fetched" not in _text(body)
    assert "Revised" not in _text(card)


def test_the_station_page_asks_the_database_the_same_questions_whatever_the_revisions(operator):
    few = _station(external="A1", name="A few")
    many = _station(external="A2", name="Many")
    _revised_chains(few, 2, first_day=date(2026, 2, 1))
    _revised_chains(many, 30, first_day=date(2026, 2, 1))
    client = _client(operator)
    client.get(_station_url(few))

    with CaptureQueriesContext(connection) as small:
        client.get(_station_url(few))
    with CaptureQueriesContext(connection) as large:
        client.get(_station_url(many))

    assert len(large) <= len(small) + 1


# -- (d) the chart and the other readers carry the current value only -----------------------------------


def test_the_chart_series_carries_the_current_value_only(usgs_api, operator):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 10.0), _feature("11261100", date(2026, 10, 29), 8.0)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 11.0, modified=MOD1)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.0, modified=MOD2)])

    url = reverse("datasync:station_chart_data", args=[station.pk])
    data = _client(operator).get(url, {"parameter": "00060"}).json()

    assert data["labels"] == ["2026-10-29", "2026-10-30"]
    assert [d["data"] for d in data["datasets"]] == [[8.0, 12.0]]


def test_the_chart_takes_its_unit_from_the_current_row(operator):
    station = _station()
    day = date(2026, 10, 30)
    old = _store(station, day, 10.0, unit="cfs")
    DataRecordStaging.objects.filter(pk=old.pk).update(replaced_at=timezone.now())
    DataRecordStaging.objects.create(
        data_source=station.data_source, station=station, raw_data={}, observation_date=_midnight(day),
        parameter_code="00060", statistic="00003", value=D("11"), unit="ft3/s", status="published",
        published_at=timezone.now(), replaces=old, change_reason="Revised by USGS Nov 3, 2026",
    )

    url = reverse("datasync:station_chart_data", args=[station.pk])
    data = _client(operator).get(url, {"parameter": "00060"}).json()

    assert [d["unit"] for d in data["datasets"]] == ["ft3/s"]


def test_the_map_the_list_and_the_dashboard_read_the_current_value(operator):
    station = _station()
    _revised_chains(station, 2, first_day=date(2026, 10, 29), old_base=40, new_base=20)
    client = _client(operator)

    geojson = client.get(reverse("datasync:stations_freshness_geojson")).json()
    (feature,) = [f for f in geojson["features"] if f["properties"]["pk"] == station.pk]
    assert feature["properties"]["latest_value"] == 21.0

    response = client.get(reverse("datasync:station_list"))
    (row,) = [r for r in response.context["enriched_stations"] if r["station"].pk == station.pk]
    assert row["latest_tooltip"] == "Latest: 21.00 ft3/s"
    # Two days, one current reading each: the trend is drawn from two values, not four.
    assert row["reading_count"] == 2
    assert len(row["sparkline_points"].split()) == 2

    response = client.get(reverse("datasync:monitoring_dashboard"))
    (item,) = [r for r in response.context["station_list"] if r["station"].pk == station.pk]
    assert item["latest_tooltip"] == "Latest: 21.00 ft3/s"
    assert len(item["sparkline_points"].split()) == 2


def test_the_source_health_report_counts_current_readings(capsys):
    station = _station()
    _revised_chains(station, 3)
    out = StringIO()

    call_command("check_source_health", "usgs", stdout=out)

    line = [ln for ln in out.getvalue().splitlines() if ln.startswith("usgs")][0]
    assert line.split()[-1] == "3"


def test_a_station_with_one_revised_reading_still_has_one_reading_to_the_pruner():
    station = _station()
    _revised_chains(station, 1)
    out = StringIO()

    call_command("prune_dataless_stations", stdout=out)

    station.refresh_from_db()
    assert station.is_active is False


def test_the_fixture_dumper_writes_the_current_value_once(tmp_path):
    station = _station()
    _revised_chains(station, 2, first_day=date(2026, 10, 29))
    path = tmp_path / "readings.json"

    call_command("dump_reading_fixture", output=str(path), start="2026-10-01", stdout=StringIO())

    rows = json.loads(path.read_text())
    assert sorted(r["value"] for r in rows) == ["20.0000", "21.0000"]


# -- The list of revised readings ------------------------------------------------------------------------


def test_the_list_page_has_its_title_description_back_link_and_columns(usgs_api, operator):
    station, _ = _revised_station_page(usgs_api, operator)

    body = _get(_client(operator), _revised_url(station))
    text = _text(body)

    assert re.search(r"<h1[^>]*>\s*Readings USGS revised\s*</h1>", body)
    assert station.station_name in text
    assert (
        "This page lists the readings USGS revised after OpenH2O first fetched them. "
        "Revised is the date USGS puts on the new value. Fetched is the day OpenH2O got it."
    ) in text
    back = re.search(r'<a [^>]*href="([^"]+)"[^>]*class="back-link"|<a [^>]*class="back-link"[^>]*href="([^"]+)"', body)
    assert back and (back.group(1) or back.group(2)) == _station_url(station)
    assert f"Back to {station.station_name}" in text
    assert _headers(body) == ["Date", "Parameter", "Value", "Earlier value", "Revised", "Fetched"]


def test_the_list_gives_one_row_per_replaced_row_newest_observation_first(usgs_api, operator):
    station = _station()
    _usgs_sync(usgs_api, station, [
        _feature("11261100", date(2026, 10, 30), 12.5),
        _feature("11261100", date(2026, 10, 29), 8.0),
        _feature("11261100", date(2026, 10, 28), 7.0),
    ])
    _usgs_sync(usgs_api, station, [
        _feature("11261100", date(2026, 10, 30), 14.0, modified=MOD1),
        _feature("11261100", date(2026, 10, 29), 8.0, modified=MOD1),
        _feature("11261100", date(2026, 10, 28), 6.0, modified=MOD2),
    ])

    rows = _main_rows(_get(_client(operator), _revised_url(station)))

    assert len(rows) == 2
    fetched = _words(timezone.localdate())
    assert _cells(rows[0]) == ["Oct 30, 2026", "Discharge (cfs)", "14.00 ft3/s", "12.50", MOD1_WORDS, fetched]
    assert _cells(rows[1]) == ["Oct 28, 2026", "Discharge (cfs)", "6.00 ft3/s", "7.00", MOD2_WORDS, fetched]
    assert "record-void-text" in rows[0]


def test_a_chain_of_three_is_two_rows_each_with_its_own_earlier_value_and_dates(usgs_api, operator):
    station = _station()
    day = date(2026, 10, 30)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 10.0)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 11.0, modified=MOD1)])
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.0, modified=MOD2)])

    rows = _main_rows(_get(_client(operator), _revised_url(station)))

    cells = sorted(_cells(row) for row in rows)
    assert len(rows) == 2
    # Both show the chain's current value; each shows the value it replaced and the date of its replacement.
    assert [c[2] for c in cells] == ["12.00 ft3/s", "12.00 ft3/s"]
    assert {(c[3], c[4]) for c in cells} == {("10.00", MOD1_WORDS), ("11.00", MOD2_WORDS)}


def test_a_station_that_holds_several_statistics_names_the_statistic_in_the_parameter(operator):
    from datasync.adapters.registry import get_parameter_label

    station = _station()
    _revised_chains(station, 1, code="00010", statistic="00001", unit="deg C")
    _revised_chains(station, 1, code="00010", statistic="00003", unit="deg C")

    rows = _main_rows(_get(_client(operator), _revised_url(station)))

    labels = sorted(_cells(row)[1] for row in rows)
    assert labels == sorted([
        get_parameter_label("usgs", "00010", "00001"),
        get_parameter_label("usgs", "00010", "00003"),
    ])
    assert len(set(labels)) == 2


def test_a_source_with_no_dates_has_no_revised_column_and_says_so(cdec_api, operator):
    station = _station(_source("cdec"), "BUR", "BULLARDS TEST")
    station.parameters = ["15"]
    station.save()
    _cdec_sync(cdec_api, station, [_cdec_item("BUR", "2026-10-30", 100.0)])
    _cdec_sync(cdec_api, station, [_cdec_item("BUR", "2026-10-30", 105.0)])

    body = _get(_client(operator), _revised_url(station))
    text = _text(body)

    assert re.search(r"<h1[^>]*>\s*Readings CDEC revised\s*</h1>", body)
    assert _headers(body) == ["Date", "Parameter", "Value", "Earlier value", "Fetched"]
    assert "This page lists the readings CDEC revised after OpenH2O first fetched them." in text
    assert "Fetched is the day OpenH2O got the new value." in text
    assert "Revised is the date" not in text
    (row,) = _main_rows(body)
    assert _cells(row)[-1] == _words(timezone.localdate())


def test_a_row_without_a_date_in_a_list_that_has_them_says_not_stated(operator):
    station = _station()
    _revised_chains(station, 1, first_day=date(2026, 3, 2), modified=MOD1)
    _revised_chains(station, 1, first_day=date(2026, 3, 1), modified=None)

    rows = _main_rows(_get(_client(operator), _revised_url(station)))

    assert _headers(_get(_client(operator), _revised_url(station)))[4] == "Revised"
    assert _cells(rows[0])[4] == MOD1_WORDS
    assert _cells(rows[1])[4] == "Not stated"


def test_a_station_with_nothing_revised_says_so_in_a_sentence_and_is_not_a_404(operator):
    station = _station()
    _store(station, date(2026, 10, 30), 3.0)

    response = _client(operator).get(_revised_url(station))

    assert response.status_code == 200
    body = response.content.decode()
    assert "<td" not in body[body.index("<main"):]
    assert (
        "USGS has not revised any reading at this station since OpenH2O first fetched it."
        in _text(body)
    )


def test_the_list_pages_in_hundreds_and_says_how_many_it_shows(operator):
    station = _station()
    _revised_chains(station, 250)
    client = _client(operator)
    url = _revised_url(station)
    newest = date(2026, 1, 1) + timedelta(days=249)

    page_one = _get(client, url)
    rows = _main_rows(page_one)
    assert len(rows) == 100
    assert _cells(rows[0])[0] == _words(newest)
    assert "Showing the 100 newest of 250" in _text(page_one)
    assert "Show the next 100" in _text(page_one)
    assert "page=2" in re.search(r'<a [^>]*href="([^"]+)"[^>]*>\s*Show the next 100', page_one).group(1)
    assert "Back to the newest 100" not in _text(page_one)

    page_two = _get(client, url + "?page=2")
    assert len(_main_rows(page_two)) == 100
    assert _cells(_main_rows(page_two)[0])[0] == _words(newest - timedelta(days=100))
    assert "Showing 101 to 200 of 250" in _text(page_two)
    assert "Show the next 100" in _text(page_two)
    assert "Back to the newest 100" in _text(page_two)

    page_three = _get(client, url + "?page=3")
    assert len(_main_rows(page_three)) == 50
    assert "Showing 201 to 250 of 250" in _text(page_three)
    assert "Show the next 100" not in _text(page_three)
    assert "Back to the newest 100" in _text(page_three)


def test_ninety_four_rows_are_all_shown_with_no_next_link(operator):
    station = _station()
    _revised_chains(station, 94)

    body = _get(_client(operator), _revised_url(station))

    assert len(_main_rows(body)) == 94
    assert "Showing all 94" in _text(body)
    assert "Show the next 100" not in _text(body)
    assert "Back to the newest 100" not in _text(body)


def test_one_hundred_and_one_rows_page_to_a_second_page_of_one(operator):
    station = _station()
    _revised_chains(station, 101)
    client = _client(operator)

    page_one = _get(client, _revised_url(station))
    assert len(_main_rows(page_one)) == 100
    assert "Showing the 100 newest of 101" in _text(page_one)
    assert "Show the next 100" in _text(page_one)
    page_two = _get(client, _revised_url(station) + "?page=2")
    assert len(_main_rows(page_two)) == 1


def test_the_list_asks_the_database_the_same_questions_for_a_page_of_100_or_of_3(operator):
    small = _station(external="L1", name="Small")
    large = _station(external="L2", name="Large")
    _revised_chains(small, 3)
    _revised_chains(large, 250)
    client = _client(operator)
    client.get(_revised_url(small))

    with CaptureQueriesContext(connection) as few:
        client.get(_revised_url(small))
    with CaptureQueriesContext(connection) as many:
        client.get(_revised_url(large))

    assert len(many) <= len(few) + 2


def test_the_list_is_read_only_and_open_to_whoever_may_read_the_station(viewer, operator):
    station = _station()
    _revised_chains(station, 1)

    assert _client(viewer).get(_revised_url(station)).status_code == 200
    anonymous = _client().get(_revised_url(station))
    assert anonymous.status_code == 302 and "login" in anonymous["Location"]
    assert _client(operator).post(_revised_url(station)).status_code == 405
    assert _client(operator).get(reverse("datasync:station_revised", args=[station.pk + 999])).status_code == 404


# -- (g) Fetch readings now ------------------------------------------------------------------------------


def _stored_run(station, count, first_ago=200):
    """``count`` stored daily values, each older than the window."""
    today = date.today()
    for i in range(count):
        _store(station, today - timedelta(days=first_ago + i), 10 + i)


def _answer_for(station, count, first_ago=200, bump=1.0, modified=MOD1):
    today = date.today()
    return [
        _feature(
            station.external_station_id, today - timedelta(days=first_ago + i), 10 + i + bump,
            modified=modified,
        )
        for i in range(count)
    ]


def _new_features(station, count):
    today = date.today()
    return [
        _feature(station.external_station_id, today - timedelta(days=i), 50 + i, modified=MOD1)
        for i in range(count)
    ]


def _status_text(markup):
    """A status line's words: tags removed with no space left behind, so a link ends cleanly before a full stop."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", markup))).strip()


def test_both_new_and_revised_readings_are_counted_and_the_revised_count_links_to_the_list(usgs_api, operator):
    station = _station()
    _stored_run(station, 94)
    usgs_api.features = _answer_for(station, 94) + _new_features(station, 7)

    markup = _press(_client(operator), station)

    newest = _card_date(date.today())
    assert _status_text(markup) == f"OpenH2O fetched 7 new readings and 94 revised readings. The newest is from {newest}."
    link = re.search(r'<a [^>]*href="([^"]+)"[^>]*>(\d+ revised readings?)</a>', markup)
    assert link and link.group(1) == _revised_url(station)
    assert link.group(2) == "94 revised readings"


def test_one_new_and_one_revised_reading_are_singular(usgs_api, operator):
    station = _station()
    _stored_run(station, 1)
    usgs_api.features = _answer_for(station, 1) + _new_features(station, 1)

    markup = _press(_client(operator), station)

    newest = _card_date(date.today())
    assert _status_text(markup) == f"OpenH2O fetched 1 new reading and 1 revised reading. The newest is from {newest}."
    assert re.search(r'<a [^>]*href="%s"[^>]*>1 revised reading</a>' % re.escape(_revised_url(station)), markup)


def test_new_readings_only_say_that_the_earlier_ones_did_not_change(usgs_api, operator):
    station = _station()
    _stored_run(station, 2)
    usgs_api.features = _answer_for(station, 2, bump=0.0) + _new_features(station, 3)

    markup = _press(_client(operator), station)

    newest = _card_date(date.today())
    assert _status_text(markup) == (
        f"OpenH2O fetched 3 new readings. None of the earlier readings changed. The newest is from {newest}."
    )
    assert "<a " not in markup


def test_one_new_reading_only_is_singular(usgs_api, operator):
    station = _station()
    usgs_api.features = _new_features(station, 1)

    markup = _press(_client(operator), station)

    newest = _card_date(date.today())
    assert _status_text(markup) == (
        f"OpenH2O fetched 1 new reading. None of the earlier readings changed. The newest is from {newest}."
    )


def test_revised_readings_only_say_nothing_new_and_that_the_newest_is_still_the_old_one(usgs_api, operator):
    station = _station()
    _stored_run(station, 94)
    usgs_api.features = _answer_for(station, 94)

    markup = _press(_client(operator), station)

    newest = _card_date(date.today() - timedelta(days=200))
    assert _status_text(markup) == f"OpenH2O fetched 94 revised readings and nothing new. The newest is still from {newest}."
    link = re.search(r'<a [^>]*href="([^"]+)"[^>]*>94 revised readings</a>', markup)
    assert link and link.group(1) == _revised_url(station)


def test_one_revised_reading_only_is_singular(usgs_api, operator):
    station = _station()
    _stored_run(station, 1)
    usgs_api.features = _answer_for(station, 1)

    markup = _press(_client(operator), station)

    newest = _card_date(date.today() - timedelta(days=200))
    assert _status_text(markup) == f"OpenH2O fetched 1 revised reading and nothing new. The newest is still from {newest}."


def test_nothing_new_and_nothing_revised_says_so_whether_the_source_sent_nothing_or_the_same(usgs_api, operator):
    station = _station()
    _stored_run(station, 2)
    newest = _card_date(date.today() - timedelta(days=200))
    expected = f"USGS did not send any new or revised readings. The newest is still from {newest}."
    client = _client(operator)

    usgs_api.features = []
    assert _status_text(_press(client, station)) == expected

    usgs_api.features = _answer_for(station, 2, bump=0.0)
    assert _status_text(_press(client, station)) == expected
    assert "USGS NWIS" not in expected


def test_a_station_with_no_reading_and_nothing_sent_gets_no_date_sentence(usgs_api, operator):
    station = _station()
    usgs_api.features = []

    markup = _press(_client(operator), station)

    assert _status_text(markup) == "USGS did not send any new or revised readings."


def test_a_failed_run_keeps_its_own_message_escaped(usgs_api, operator, monkeypatch):
    station = _station()

    def broken(self, method, url, **kwargs):
        raise ValueError("The provider said <b>no</b>.")

    monkeypatch.setattr(USGSAdapter, "_request", broken)

    markup = _press(_client(operator), station)

    assert "&lt;b&gt;no&lt;/b&gt;" in markup
    assert "<b>" not in markup


# -- (e) pruning removes a chain together --------------------------------------------------------------


def _age(rows, days):
    DataRecordStaging.objects.filter(pk__in=[r.pk for r in rows]).update(
        created_at=timezone.now() - timedelta(days=days)
    )


def test_prune_takes_a_replaced_row_with_its_replacement_and_keeps_a_chain_with_a_recent_row():
    station = _station()
    both_old_a, both_old_b = _revised_chains(station, 1, first_day=date(2025, 1, 1))
    old_then_recent_a, old_then_recent_b = _revised_chains(station, 1, first_day=date(2025, 1, 2))
    three = _revised_chains(station, 1, first_day=date(2025, 1, 3))
    DataRecordStaging.objects.filter(pk=three[1][0].pk).update(replaced_at=timezone.now())
    third = DataRecordStaging.objects.create(
        data_source=station.data_source, station=station, raw_data={},
        observation_date=three[0][0].observation_date, parameter_code="00060", statistic="00003",
        value=D("77"), unit="ft3/s", status="published", published_at=timezone.now(),
        replaces=three[1][0], change_reason="Revised by USGS Nov 3, 2026",
    )
    all_old = _revised_chains(station, 1, first_day=date(2025, 1, 4))
    lone_old = _store(station, date(2025, 1, 5), 1.0)
    lone_recent = _store(station, date(2025, 1, 6), 2.0)
    hand = _station(_source("manual"), "HAND-1", "HAND GAUGE")
    hand_old = _store(hand, date(2025, 1, 7), 3.0, code="00065", statistic="")

    _age([*both_old_a, *both_old_b], 400)
    _age([*old_then_recent_a], 400)
    _age([*old_then_recent_b], 10)
    _age([*three[0], three[1][0]], 400)
    _age([third], 10)
    _age([*all_old[0], *all_old[1]], 400)
    _age([lone_old, hand_old], 400)
    _age([lone_recent], 10)

    out = StringIO()
    call_command("prune_old_data", stdout=out)
    counted = int(re.search(r"Published staging records\s+(\d+)", out.getvalue()).group(1))
    # both_old (2) + all_old (2) + lone_old (1): a chain goes whole or stays whole.
    assert counted == 5
    assert DataRecordStaging.objects.count() == 12

    out = StringIO()
    call_command("prune_old_data", "--confirm", stdout=out)

    assert "Deleted: 5 staging" in out.getvalue()
    left = set(DataRecordStaging.objects.values_list("pk", flat=True))
    kept = {
        *(r.pk for r in old_then_recent_a), *(r.pk for r in old_then_recent_b),
        *(r.pk for r in three[0]), *(r.pk for r in three[1]), third.pk,
        lone_recent.pk, hand_old.pk,
    }
    assert left == kept
    assert not left & {r.pk for r in [*both_old_a, *both_old_b, *all_old[0], *all_old[1], lone_old]}


# -- (f) the fixture loader goes through the same door ---------------------------------------------------


def _fixture_row(day="2026-10-30", value="12.5000", unit="ft3/s", external="11261100", **extra):
    return {
        "source": "usgs", "external_station_id": external, "parameter_code": "00060",
        "statistic": "00003", "observation_date": f"{day}T00:00:00-07:00", "value": value, "unit": unit,
        **extra,
    }


def _load(tmp_path, rows, name="readings.json"):
    path = tmp_path / name
    path.write_text(json.dumps(rows))
    out = StringIO()
    call_command("load_reading_fixture", fixture=str(path), stdout=out)
    return out.getvalue()


def test_the_loader_behaves_as_the_sync_does(tmp_path):
    station = _station()

    _load(tmp_path, [_fixture_row()])
    (first,) = _rows(station)
    assert first.status == "published" and first.published_at is not None and first.raw_data == {}

    _load(tmp_path, [_fixture_row()])
    assert len(_rows(station)) == 1

    _load(tmp_path, [_fixture_row(value="14.0000")])
    old, new = _rows(station)
    assert old.pk == first.pk and old.replaced_at is not None and old.value == D("12.5000")
    assert new.replaces_id == old.pk and new.value == D("14.0000") and new.status == "published"
    assert new.change_reason == f"Revised by USGS, fetched {_words(timezone.localdate())}"
    assert list(DataRecordStaging.objects.current()) == [new]

    _load(tmp_path, [_fixture_row(value="14.0000")])
    assert len(_rows(station)) == 2


def test_the_loader_rounds_and_ignores_a_unit_respelling_and_a_blank(tmp_path):
    station = _station()
    _load(tmp_path, [_fixture_row(value="26.1235")])

    _load(tmp_path, [_fixture_row(value="26.12345")])
    _load(tmp_path, [_fixture_row(value="26.1235", unit="cfs")])
    _load(tmp_path, [_fixture_row(value=None)])

    (only,) = _rows(station)
    assert only.value == D("26.1235") and only.unit == "ft3/s" and only.replaced_at is None


def test_the_loader_replaces_a_stored_blank_with_a_figure(tmp_path):
    station = _station()
    _load(tmp_path, [_fixture_row(value=None)])

    _load(tmp_path, [_fixture_row(value="3.0000")])

    blank, figure = _rows(station)
    assert blank.value is None and blank.replaced_at is not None
    assert figure.value == D("3.0000") and figure.replaces_id == blank.pk


def test_the_loader_takes_a_fixed_number_of_queries_however_many_rows(tmp_path):
    station = _station()
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(3000)]
    rows = [_fixture_row(day=str(day), value=str(i)) for i, day in enumerate(days)]
    changed = [
        _fixture_row(day=str(day), value=str(i + 1 if i < 500 else i)) for i, day in enumerate(days)
    ]

    with CaptureQueriesContext(connection) as first_load:
        _load(tmp_path, rows)
    with CaptureQueriesContext(connection) as same_again:
        _load(tmp_path, rows)
    with CaptureQueriesContext(connection) as with_changes:
        _load(tmp_path, changed)

    assert DataRecordStaging.objects.filter(station=station).count() == 3500
    assert DataRecordStaging.objects.current().filter(station=station).count() == 3000
    assert DataRecordStaging.objects.filter(station=station, replaced_at__isnull=False).count() == 500
    assert len(first_load) < 40
    assert len(same_again) < 40
    assert len(with_changes) < 40


# -- (h) the committed readings fixture ------------------------------------------------------------------


def test_the_committed_readings_fixture_loaded_twice_writes_nothing_the_second_time():
    pinned = json.loads((ROOT / "data/demo/expected_shape.json").read_text())["models"][
        "datasync.DataRecordStaging"
    ]["expected"]
    in_file = len(json.loads((ROOT / "data/merced/readings.json").read_text()))
    assert pinned == in_file == 30951
    call_command("seed_data_sources", stdout=StringIO())
    call_command("load_station_fixture", stdout=StringIO())

    call_command("load_reading_fixture", stdout=StringIO())
    first = list(DataRecordStaging.objects.order_by("pk").values_list("pk", "value", "replaced_at"))
    call_command("load_reading_fixture", stdout=StringIO())
    second = list(DataRecordStaging.objects.order_by("pk").values_list("pk", "value", "replaced_at"))

    assert len(first) == pinned
    assert second == first
    assert DataRecordStaging.objects.current().count() == pinned


# -- Deleting what has a replaced row in it -----------------------------------------------------------------


def test_deleting_a_station_with_a_replaced_row_deletes_its_readings_and_keeps_its_logs():
    station = _station()
    _revised_chains(station, 3)
    log = DataSyncLog.objects.create(data_source=station.data_source, station=station, status="success")

    station.delete()

    assert DataRecordStaging.objects.count() == 0
    log.refresh_from_db()
    assert log.station is None


def test_deleting_a_source_with_a_replaced_row_deletes_its_stations_and_readings():
    station = _station()
    _revised_chains(station, 3)

    station.data_source.delete()

    assert DataRecordStaging.objects.count() == 0
    assert MonitoredStation.objects.count() == 0


def test_pruning_stations_with_a_replaced_row_present_deletes_the_dataless_ones():
    thin = _station(external="THIN", name="Thin")
    _revised_chains(thin, 1)
    rich = _station(external="RICH", name="Rich")
    _revised_chains(rich, 3)

    call_command("prune_dataless_stations", "--delete", stdout=StringIO())

    assert not MonitoredStation.objects.filter(pk=thin.pk).exists()
    assert MonitoredStation.objects.filter(pk=rich.pk).exists()
    assert DataRecordStaging.objects.filter(station=rich).count() == 6


def test_removing_the_demonstration_with_a_replaced_row_present():
    from core import demonstration as demo
    from core.models import SiteConfig
    from tests import factories as f

    f.BoundaryFactory(name=demo.DEMONSTRATION_BOUNDARY)
    SiteConfig.objects.create(agency_name=demo.DEMONSTRATION_NAME, demonstration_mode=True)
    station = _station()
    _revised_chains(station, 3)

    call_command("remove_demonstration", stdout=StringIO())

    assert DataRecordStaging.objects.count() == 0
    assert MonitoredStation.objects.count() == 0


# -- No figure moves when a reading is revised --------------------------------------------------------------


def _engine_snapshot():
    from accounting.models import CalculationRun
    from parcels.models import ParcelLedger

    decimals = [
        f.name for f in CalculationRun._meta.concrete_fields if isinstance(f, models.DecimalField)
    ]
    runs = list(
        CalculationRun.objects.order_by("parcel_id", "period").values_list("parcel_id", "period", *decimals)
    )
    ledger = list(
        ParcelLedger.objects.current()
        .order_by("parcel_id", "effective_date", "source_type", "amount_acre_feet")
        .values_list("parcel_id", "effective_date", "source_type", "amount_acre_feet")
    )
    return runs, ledger


def test_no_calculation_output_moves_when_a_reading_is_revised(ref, usgs_api):
    ld.build_d1()
    station = _station()
    day = date(2025, 7, 15)
    _usgs_sync(usgs_api, station, [_feature("11261100", day, 12.5, modified=MOD1)])
    ld.run_months(["2025-07"])
    before = _engine_snapshot()
    assert before[0] and before[1]

    _usgs_sync(usgs_api, station, [_feature("11261100", day, 99.0, modified=MOD2)])
    assert DataRecordStaging.objects.filter(station=station, replaced_at__isnull=False).count() == 1
    ld.run_months(["2025-07"])

    assert _engine_snapshot() == before
