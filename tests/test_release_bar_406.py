# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site asks OpenET's service for the field, never quietly for one point in it.

OpenET's polygon endpoint requires a ``reducer``: how the field's pixels become
one figure. A request without it is refused (422, "Field required" at
body.reducer, read against the live service on 2026-11-12). The adapter sent
none and caught every failure by asking again for the field's centre point, so a
site on OpenET's service recorded one pixel's crop ET under the field's name
with nothing on any page to say so.

A correct site asks for the field's mean, and when the field request is refused
it counts the field as failed rather than recording a point in its place.
"""

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.contrib.gis.geos import MultiPolygon, Polygon

from datasync.adapters.openet import POINT_URL, POLYGON_URL, OpenETAdapter
from datasync.models import CropETFigure, OpenETCache

START, END = dt.date(2025, 11, 1), dt.date(2026, 2, 28)


@pytest.fixture
def field(db):
    from parcels.models import Parcel

    return Parcel.objects.create(
        parcel_number="MER-REDUCER-001",
        geometry=MultiPolygon(Polygon.from_bbox((-120.54, 37.10, -120.53, 37.11)), srid=4326),
        area_acres=10,
        status="active",
    )


def _refused(method, url, **kwargs):
    """The field request is refused; a point request would be answered."""
    if url == POINT_URL:
        return MagicMock(json=lambda: [{"time": "2025-12-01", "et": 30.0}])
    response = requests.Response()
    response.status_code = 422
    response.url = url
    raise requests.HTTPError("422 Client Error: Unprocessable Entity", response=response)


def test_the_field_request_asks_for_the_fields_mean(field):
    adapter = OpenETAdapter()
    with patch.object(adapter, "_request") as request:
        request.return_value = MagicMock(json=lambda: [])
        adapter.fetch_polygon(field.geometry, START, END)

    method, url = request.call_args.args
    assert url == POLYGON_URL
    assert request.call_args.kwargs["json"]["reducer"] == "mean"


def test_a_refused_field_request_is_not_replaced_by_the_centre_point(field):
    adapter = OpenETAdapter()
    with patch.object(adapter, "_request", side_effect=_refused) as request:
        with pytest.raises(requests.HTTPError):
            adapter.fetch_polygon(field.geometry, START, END)

    urls = [call.args[1] for call in request.call_args_list]
    assert POINT_URL not in urls, "the refused field request was asked again for one point"
    assert urls == [POLYGON_URL]


def test_a_refused_field_request_counts_the_field_as_failed_and_records_nothing(field, settings):
    settings.OPENET_MONTHLY_BUDGET = 5
    adapter = OpenETAdapter()
    with patch.object(adapter, "_request", side_effect=_refused), patch.object(adapter, "_rate_limit"):
        summary = adapter.sync_parcel_et([field], START, END)

    assert summary["failed"] == 1
    assert summary["fetched"] == 0
    assert not OpenETCache.objects.filter(parcel=field).exists()
    assert not CropETFigure.objects.filter(parcel=field).exists()
