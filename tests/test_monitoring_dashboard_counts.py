# SPDX-License-Identifier: AGPL-3.0-or-later
"""143-12, R-081 / R-082 / R-083: the monitoring dashboard's per-source cards
and the "Active stations" section say one consistent thing.

R-081/R-082: every source card renders the SAME three-part count line
("N active of M stations: F up to date, S slightly behind, D dormant"), and a
source with active stations but no sync log says what "Not yet synced" means
rather than leaving the reader to guess.

R-083: "Active stations" used to show a fixed slice (every card whose
freshness was not "dead") under a tile claiming a bigger total, with nothing
saying which cards these were or why. The section's own line now says how
many of the total are shown and links the rest.

Every source and station name here is fictional (`Probe ...`), never a name
from the session-scoped Merced seed.
"""
from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.models import User
from datasync.models import DataSource, MonitoredStation

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client():
    user = User.objects.create(
        username="r081-reader", email="r081-reader@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    return client


class TestSourceCardsShareOneCountShape:
    def test_active_stations_no_sync_log_says_not_yet_synced_and_why(
        self, auth_client
    ):
        src = DataSource.objects.create(
            code="probe_never_synced", name="Probe Never-Synced Source",
            is_active=True,
        )
        now = timezone.now()
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R081-1", station_name="Probe Fresh One",
            location=Point(-120.0, 37.0), is_active=True, last_data_at=now,
        )
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R081-2", station_name="Probe Stale One",
            location=Point(-120.0, 37.0), is_active=True,
            last_data_at=now - timedelta(hours=48),
        )
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R081-3", station_name="Probe Dead One",
            location=Point(-120.0, 37.0), is_active=True,
            last_data_at=now - timedelta(days=30),
        )
        resp = auth_client.get(reverse("datasync:monitoring_dashboard"))
        body = resp.content.decode()
        assert resp.status_code == 200
        assert '<span class="badge badge-grey">Not yet synced</span>' in body
        assert (
            "This deployment has not run a sync against PROBE_NEVER_SYNCED "
            "yet; the readings it holds were loaded, not synced." in body
        )
        assert (
            "3 active of 3 stations: 1 up to date, 1 slightly behind, "
            "1 dormant" in body
        )

    def test_a_source_with_no_active_stations_stops_after_saying_so(
        self, auth_client
    ):
        src = DataSource.objects.create(
            code="probe_none_active", name="Probe None-Active Source",
            is_active=True,
        )
        now = timezone.now()
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R082-1",
            station_name="Probe Switched-Off Station",
            location=Point(-120.0, 37.0), is_active=False, last_data_at=now,
        )
        resp = auth_client.get(reverse("datasync:monitoring_dashboard"))
        body = resp.content.decode()
        # The other card (above) carries the three-part clause; this one, with
        # zero active stations, stops after "none active": never three more
        # "none" clauses tacked on.
        assert "1 station, none active" in body
        assert "1 station, none active: none up to date" not in body


class TestActiveStationsSectionSaysWhichOnesAndWhy:
    def test_the_line_names_the_shown_count_and_links_the_dormant_filter(
        self, auth_client
    ):
        src = DataSource.objects.create(
            code="probe_active_section", name="Probe Active Section Source",
            is_active=True,
        )
        now = timezone.now()
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R083-1", station_name="Probe Shown Station",
            location=Point(-120.0, 37.0), is_active=True, last_data_at=now,
        )
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R083-2", station_name="Probe Hidden Dead One",
            location=Point(-120.0, 37.0), is_active=True,
            last_data_at=now - timedelta(days=30),
        )
        MonitoredStation.objects.create(
            data_source=src, external_station_id="R083-3", station_name="Probe Hidden Dead Two",
            location=Point(-120.0, 37.0), is_active=True,
            last_data_at=now - timedelta(days=30),
        )
        resp = auth_client.get(reverse("datasync:monitoring_dashboard"))
        body = resp.content.decode()
        assert (
            "1 of the 3 active stations: the ones up to date or slightly "
            "behind. The 2 dormant are on the "
            '<a class="text-link" href="/datasync/stations/?reporting=dead">'
            "station list</a>." in body
        )
        assert body.count("station-card-link") == 1
