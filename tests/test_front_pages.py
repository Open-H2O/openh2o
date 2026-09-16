# SPDX-License-Identifier: AGPL-3.0-or-later
"""The front page's hero leads with the station figure, in the station
list's own words, and the anonymous page counts its stations one way with
the system status in the head (143-09, R-137, R-138, R-140).
"""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from datasync.models import DataSource, MonitoredStation

User = get_user_model()


def _viewer():
    return User.objects.create_user(
        username="front-page-reader", email="front-page-reader@example.com",
        password="x", is_active=True,
    )


def _client_in():
    client = Client()
    client.force_login(_viewer())
    return client


def _seed_stations():
    """1 fresh + 1 dead among 2 ACTIVE (syncing) stations, plus 1 inactive
    station so the total (3) differs visibly from the syncing count (2)."""
    from django.contrib.gis.geos import Point

    src = DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)
    now = timezone.now()
    MonitoredStation.objects.create(
        data_source=src, external_station_id="FP-1", station_name="Fresh Station",
        location=Point(-119.5, 36.5), is_active=True, last_data_at=now,
    )
    MonitoredStation.objects.create(
        data_source=src, external_station_id="FP-2", station_name="Dead Station",
        location=Point(-119.6, 36.6), is_active=True,
        last_data_at=now - timedelta(days=400),
    )
    MonitoredStation.objects.create(
        data_source=src, external_station_id="FP-3", station_name="Off Station",
        location=Point(-119.7, 36.7), is_active=False, last_data_at=None,
    )


@pytest.mark.django_db
class TestTheHeroLeadsWithTheStationFigure:
    """R-137, R-138: the largest words on the signed-in front page are the
    station figure, in the station list's own vocabulary, not a greeting."""

    def test_hero_title_is_a_link_reading_the_measured_counts(self):
        _seed_stations()
        html = _client_in().get(reverse("index")).content.decode()
        anchor_open = '<a href="{}?reporting=fresh" class="home-hero-title-link">'.format(
            reverse("datasync:station_list")
        )
        assert anchor_open in html
        # Between the anchor's open tag and its text sits the freshness dot;
        # the text itself, and the anchor's close, follow it.
        after_open = html[html.index(anchor_open) + len(anchor_open):]
        assert after_open.lstrip().startswith('<span class="home-hero-dot')
        assert "1 of 2 syncing stations up to date</a>" in after_open[:400]

    def test_no_greeting_anywhere(self):
        _seed_stations()
        html = _client_in().get(reverse("index")).content.decode()
        for greeting in ("Good morning", "Good afternoon", "Good evening"):
            assert greeting not in html


@pytest.mark.django_db
class TestTheAnonymousPageCountsOneWay:
    """R-138, R-140: the stations card names the total and the syncing count
    together; one grid holds every count card; the system status sits in the
    page head, not a seventh card."""

    def test_stations_card_reads_total_and_syncing_apart(self):
        _seed_stations()
        html = Client().get(reverse("index")).content.decode()
        assert '<div class="dashboard-card-value">3</div>' in html  # the total
        assert "2 syncing" in html

    def test_one_dashboard_grid_and_a_system_running_badge(self):
        _seed_stations()
        html = Client().get(reverse("index")).content.decode()
        assert html.count('class="dashboard-grid dashboard-grid--counts"') == 1
        assert "System running" in html
        assert "dashboard-card-wide" not in html

    def test_no_methodology_settings_card(self):
        _seed_stations()
        html = Client().get(reverse("index")).content.decode()
        assert "Methodology settings" not in html
