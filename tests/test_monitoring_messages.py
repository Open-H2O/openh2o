# SPDX-License-Identifier: AGPL-3.0-or-later
"""The monitoring dashboard's sentences (150.1-02, 2026-10-16), and the two
code changes with them: the
boundary line counts the active stations outside the boundary (it claimed
reservoirs and upstream gauges outside it on any site), and a station card
shows its source's name and the freshness words (it showed cdec, fresh, stale).

The station list and Add station brought two more code changes: the list's no-results line names the source (it printed the
code, dwr_sgma), and a source and station ID already on file get a sentence
on Add station (it was a server error).

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


# --- the station list and Add station ---------------------------------------


def _list(client, **params):
    resp = client.get(reverse("datasync:station_list"), params)
    return resp.content.decode().replace("&#x27;", "'")


def test_station_list_words(auth_client):
    src = DataSource.objects.create(code="probe_list", name="Probe List Source", is_active=True)
    MonitoredStation.objects.create(
        data_source=src, external_station_id="LIST-1", station_name="Probe Silent Gauge",
        location=Point(-120.5, 37.3, srid=4326), is_active=True, last_data_at=None,
    )
    body = _list(auth_client, active="all")
    assert (
        "This page lists every monitoring station on file and the public data source "
        "OpenH2O syncs it from. The map colors each station by how recently it reported. "
        "Open a station from the map or the list to see its readings and chart."
    ) in body
    assert 'class="btn-secondary btn-sm">Monitoring dashboard</a>' in body
    assert "Network health" not in body
    assert ">All sources</option>" in body
    assert body.count('title="Whether OpenH2O\'s scheduled syncs include this station."') == 2
    assert 'title="How recently the station reported, judged against how often its source publishes."' in body
    assert "<th>Last reading</th>" in body
    row = body.split("Probe Silent Gauge", 1)[1][:4000]
    assert ">No reading</span>" in row
    assert 'title="Turn syncing off"' in row


def test_toggle_hover_follows_the_switch(auth_client):
    src = DataSource.objects.create(code="probe_toggle", name="Probe Toggle Source", is_active=True)
    station = MonitoredStation.objects.create(
        data_source=src, external_station_id="TOG-1", station_name="Probe Toggle Gauge",
        location=Point(-120.5, 37.3, srid=4326), is_active=True,
    )
    resp = auth_client.post(reverse("datasync:station_toggle", args=[station.pk]))
    assert 'title="Turn syncing on"' in resp.content.decode()


def test_no_results_names_the_source(auth_client):
    DataSource.objects.create(code="probe_dept", name="Department of Probe Records", is_active=True)
    DataSource.objects.create(code="probe_short", name="PROBE NWIS", is_active=True)
    body = _list(auth_client, source="probe_dept", q="BEAR")
    assert "No station from the Department of Probe Records matches &ldquo;BEAR&rdquo;." in body
    assert "probe_dept matches" not in body and "from probe_dept" not in body
    body = _list(auth_client, source="probe_short")
    assert "No station from PROBE NWIS matches these filters." in body
    assert "0 stations from PROBE NWIS, syncing" in body
    body = _list(auth_client, q="NO-SUCH-PROBE-STATION")
    assert "No station matches &ldquo;NO-SUCH-PROBE-STATION&rdquo;." in body


def test_add_station_words(auth_client):
    DataSource.objects.create(code="probe_add", name="Probe Add Source", is_active=True)
    body = auth_client.get(reverse("datasync:station_add")).content.decode().replace("&#x27;", "'")
    assert (
        "This page adds one monitoring station for OpenH2O to sync from a public data "
        "source. The external station ID is the source's own identifier for the station, "
        "such as 11303000 at USGS."
    ) in body
    assert '<option value="">Choose a data source</option>' in body
    option = body.split("Probe Add Source", 1)[0].rsplit("<option", 1)[1]
    assert "probe_add" not in option.split(">", 1)[1]
    assert "identifier the external data provider" not in body


def test_add_station_errors(auth_client):
    resp = auth_client.post(reverse("datasync:station_add"), {})
    body = resp.content.decode()
    for line in (
        "Choose a data source.",
        "Enter the external station ID.",
        "Enter the station name.",
        "Enter the latitude and longitude in decimal degrees.",
    ):
        assert f"<div>{line}</div>" in body
    assert "is required" not in body
    resp = auth_client.post(reverse("datasync:station_add"), {
        "data_source": "not-a-number", "external_station_id": "X", "station_name": "Y",
        "lat": "37.1", "lng": "-120.1",
    })
    assert resp.status_code == 200
    assert "<div>Choose a data source.</div>" in resp.content.decode()


def test_add_station_already_on_file(auth_client):
    src = DataSource.objects.create(code="probe_dup", name="Probe Dup Source", is_active=True)
    MonitoredStation.objects.create(
        data_source=src, external_station_id="BSD", station_name="Probe Existing Gauge",
        location=Point(-120.5, 37.3, srid=4326), is_active=True,
    )
    before = MonitoredStation.objects.count()
    resp = auth_client.post(reverse("datasync:station_add"), {
        "data_source": str(src.pk), "external_station_id": "BSD",
        "station_name": "Probe Second Gauge", "lat": "37.2", "lng": "-120.2",
    })
    assert resp.status_code == 200
    assert "<div>Probe Dup Source station BSD is already on file.</div>" in resp.content.decode()
    assert MonitoredStation.objects.count() == before
