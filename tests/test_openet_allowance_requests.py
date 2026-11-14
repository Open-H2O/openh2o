# SPDX-License-Identifier: AGPL-3.0-or-later
"""The OpenET allowance counts requests the site sent and OpenET answered, not stored rows.

On the field list one request carries up to 400 fields' figures, so counting stored rows
would read 8,905 used after 23 requests. The site writes down every request it sends and
counts the answered ones since 00:00 UTC on the 1st, when OpenET's own count turns over. A
refused request costs nothing and counts nothing. Rows written by Earth Engine or loaded from
a committed file count nothing. The older route (one request per use area) writes its
request down the same way, so it keeps counting what it spends.

**Every field number and figure here is made up** (field numbers from 99000000001, depths
of 1 mm); none is OpenET's.
"""

import datetime as dt
from decimal import Decimal as D
from unittest import mock

import pytest
import requests
from django.utils import timezone

from datasync.models import OpenETCache
from parcels.models import Parcel
from tests.factories import _box

pytestmark = pytest.mark.django_db


def _month_start():
    return timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _request(answered=True, kind="figures", at=None, ids=100):
    from datasync.models import OpenETRequest

    row = OpenETRequest.objects.create(kind=kind, ids_count=ids, answered=answered,
                                       http_status=200 if answered else 404)
    if at is not None:
        OpenETRequest.objects.filter(pk=row.pk).update(sent_at=at)
    return row


def test_answered_requests_are_counted_not_stored_field_months():
    from datasync.models import OpenETField, OpenETFieldMonth

    # 23 made-up figures requests that wrote 8,905 made-up field-months.
    for _ in range(23):
        _request()
    fields = OpenETField.objects.bulk_create(
        [OpenETField(field_id=99000000001 + n, received_on=dt.date(2025, 8, 6)) for n in range(372)]
    )
    months = [dt.date(2023 + (m + 9) // 12, (m + 9) % 12 + 1, 1) for m in range(24)]
    rows = [
        OpenETFieldMonth(field=f, month=m, et_mm=D("1"), pr_mm=D("1"), received_on=dt.date(2025, 8, 6))
        for f in fields for m in months
    ][:8905]
    OpenETFieldMonth.objects.bulk_create(rows)
    assert OpenETFieldMonth.objects.count() == 8905
    assert OpenETCache.monthly_query_count() == 23


def test_a_refused_request_counts_nothing():
    _request(answered=True)
    _request(answered=False)
    assert OpenETCache.monthly_query_count() == 1


def test_the_count_turns_over_at_midnight_utc_on_the_first():
    start = _month_start()
    _request(at=start + dt.timedelta(minutes=30))
    _request(at=start - dt.timedelta(minutes=30))  # 4:30 p.m. Pacific the day before
    assert OpenETCache.monthly_query_count() == 1


def test_earth_engine_and_fixture_rows_count_nothing():
    parcel = Parcel.objects.create(parcel_number="MADEUP-ALLOWANCE", geometry=_box(), area_acres=D("10"))
    for n, origin in enumerate(("gee", "fixture", "unknown")):
        OpenETCache.objects.create(
            parcel=parcel, geometry=parcel.geometry, start_date=dt.date(2025, 7, 1),
            end_date=dt.date(2025, 7, 31), variable=f"made_up_{n}", model_name="Ensemble",
            origin=origin, et_data=[],
        )
    assert OpenETCache.monthly_query_count() == 0


def test_the_budget_refuses_before_a_request_is_sent(settings, monkeypatch):
    from datasync import field_list

    monkeypatch.setenv("OPENET_API_KEY", "made-up-key-not-real")
    settings.OPENET_MONTHLY_BUDGET = 3
    for _ in range(3):
        _request()
    assert OpenETCache.check_budget() == (False, 3, 3)
    with mock.patch("requests.request") as sent, pytest.raises(field_list.AllowanceUsed):
        field_list.figures([99000000001], dt.date(2025, 7, 1), dt.date(2025, 7, 31))
    assert not sent.called


def _ok(body):
    resp = requests.Response()
    resp.status_code = 200
    resp._content = body
    resp.headers["Content-Type"] = "application/json"
    return resp


def test_the_older_route_writes_its_request_down_and_it_counts():
    from datasync.adapters.openet import OpenETAdapter
    from datasync.models import OpenETRequest

    parcel = Parcel.objects.create(parcel_number="MADEUP-OLD-ROUTE", geometry=_box(), area_acres=D("10"))
    made_up_answer = [{"time": "2025-07-01", "et": 1.0}]
    with (
        mock.patch.object(OpenETAdapter, "fetch_polygon", return_value=made_up_answer),
        mock.patch.object(OpenETAdapter, "_rate_limit"),
    ):
        OpenETAdapter().sync_with_cache(parcel, dt.date(2025, 7, 1), dt.date(2025, 7, 31))
    (row,) = OpenETRequest.objects.all()
    assert row.kind == "point_or_polygon"
    assert row.answered is True
    assert OpenETCache.monthly_query_count() == 1


def test_the_older_routes_failed_request_counts_nothing():
    from datasync.adapters.openet import OpenETAdapter
    from datasync.models import OpenETRequest

    parcel = Parcel.objects.create(parcel_number="MADEUP-OLD-FAIL", geometry=_box(), area_acres=D("10"))
    with (
        mock.patch.object(OpenETAdapter, "fetch_polygon", side_effect=RuntimeError("made-up failure")),
        mock.patch.object(OpenETAdapter, "_rate_limit"),
    ):
        OpenETAdapter().sync_with_cache(parcel, dt.date(2025, 7, 1), dt.date(2025, 7, 31))
    assert not OpenETRequest.objects.filter(answered=True).exists()
    assert OpenETCache.monthly_query_count() == 0
