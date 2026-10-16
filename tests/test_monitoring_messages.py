# SPDX-License-Identifier: AGPL-3.0-or-later
"""The monitoring dashboard's sentences Brent approved (150.1-02 screen 15,
message A, 2026-10-16 05:10), and the two code changes with them: the
boundary line counts the active stations outside the boundary (it claimed
reservoirs and upstream gauges outside it on any site), and a station card
shows its source's name and the freshness words (it showed cdec, fresh, stale).

Station and source names are fictional (`Probe ...`).
"""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.models import User
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client():
    user = User.objects.create(username="mon-msg", email="mon-msg@example.com", is_active=True)
    client = Client()
    client.force_login(user)
    return client


def _body(client):
    resp = client.get(reverse("datasync:monitoring_dashboard"))
    return resp, resp.content.decode().replace("&#x27;", "'")


def test_description(auth_client):
    _, body = _body(auth_client)
    assert (
        "This page shows how recently each monitoring station reported and when "
        "OpenH2O last synced each data source. The page refreshes every minute."
    ) in body


def test_boundary_line_counts_the_stations_outside(auth_client):
    boundary = Boundary.objects.first()
    if boundary is None:
        square = Polygon.from_bbox((-121.0, 37.0, -120.0, 38.0))
        square.srid = 4326
        boundary = Boundary.objects.create(name="Probe Basin", geometry=MultiPolygon(square, srid=4326))
    src = DataSource.objects.create(code="probe_outside", name="Probe Outside Source", is_active=True)
    MonitoredStation.objects.create(
        data_source=src, external_station_id="OUT-1", station_name="Probe Far Gauge",
        location=Point(-60.0, 10.0, srid=4326), is_active=True,
        last_data_at=timezone.now() - timedelta(hours=1),
    )
    resp, body = _body(auth_client)
    active = MonitoredStation.objects.filter(is_active=True)
    outside = active.exclude(location__within=boundary.geometry).count()
    assert resp.context["outside_count"] == outside >= 1
    assert f"This site's boundary is {boundary.name}." in body
    verb = "lies" if outside == 1 else "lie"
    noun = "station" if active.count() == 1 else "stations"
    assert f"{outside} of the {active.count()} active {noun} {verb} outside the boundary." in body
    assert "upstream gauges outside it" not in body


def test_card_shows_the_source_name_and_freshness_words(auth_client):
    src = DataSource.objects.create(code="probe_card", name="Probe Card Source", is_active=True)
    MonitoredStation.objects.create(
        data_source=src, external_station_id="CARD-1", station_name="Probe Card Gauge",
        location=Point(-120.5, 37.3, srid=4326), is_active=True,
        last_data_at=timezone.now() - timedelta(hours=1),
    )
    _, body = _body(auth_client)
    card = body.split("Probe Card Gauge", 1)[1][:3000]
    assert 'title="Up to date"' in card
    assert ">PROBE_CARD<" in card
    assert ">probe_card<" not in card


def test_source_lines(auth_client):
    from datasync import freshness

    assert freshness.status_label("no_data") == "None up to date"
    assert freshness.source_blurb("dwr_sgma") == (
        "Department of Water Resources SGMA Portal: groundwater monitoring reported "
        "under the Sustainable Groundwater Management Act."
    )
    assert "—" not in "".join(freshness.SOURCE_BLURBS.values())
