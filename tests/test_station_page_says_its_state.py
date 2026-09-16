# SPDX-License-Identifier: AGPL-3.0-or-later
"""143-12, R-077 / R-078: the station page says its own freshness word.

Before this plan, the only place the freshness word ("Dormant" / "Up to date" /
"Slightly behind") rendered was the pane header, which the full page skips
(`on_full_page=True`), so a dormant station's full page said nothing anywhere
explaining why every panel on it was empty. It also drew a full-height 0-1.0
telemetry axis for a station that had never published a reading.

Every station and source name here is fictional (`Probe ...`), never a name
from the session-scoped Merced seed, so this file cannot collide with it.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.models import User
from datasync.models import DataRecordStaging, DataSource, MonitoredStation

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client():
    user = User.objects.create(
        username="r077-reader", email="r077-reader@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    return client


class TestDormantStationSaysWhyItIsEmpty:
    def test_the_head_carries_a_dormant_badge(self, auth_client):
        src = DataSource.objects.create(
            code="probe_dormant_src", name="Probe Dormant Source", is_active=True
        )
        station = MonitoredStation.objects.create(
            data_source=src, external_station_id="R077-1",
            station_name="Probe Never-Published Station",
            location=Point(-120.0, 37.0), is_active=False, last_data_at=None,
        )
        resp = auth_client.get(reverse("datasync:station_detail", args=[station.pk]))
        body = resp.content.decode()
        assert resp.status_code == 200
        assert (
            '<span class="badge badge-grey" '
            'title="How recently the station published, judged against its '
            "own source's cadence. A station can be syncing and still "
            'dormant.">Dormant</span>' in body
        )

    def test_no_chart_for_a_station_that_has_never_published(self, auth_client):
        src = DataSource.objects.create(
            code="probe_dormant_src2", name="Probe Dormant Source Two", is_active=True
        )
        station = MonitoredStation.objects.create(
            data_source=src, external_station_id="R077-2",
            station_name="Probe Chartless Station",
            location=Point(-120.0, 37.0), is_active=False, last_data_at=None,
        )
        resp = auth_client.get(reverse("datasync:station_detail", args=[station.pk]))
        body = resp.content.decode()
        # Real tag counts, not the substring "chart-range-btn": that string
        # also appears in the always-loaded JS selector at the foot of the
        # partial, so a substring check would pass even with no canvas.
        assert body.count('id="telemetry-chart"') == 0
        assert body.count('<button class="chart-range-btn"') == 0
        assert "No published readings from this station." in body
        assert "Syncing is switched off for it." in body

    def test_no_current_readings_card_and_one_merged_sync_history_card(self, auth_client):
        src = DataSource.objects.create(
            code="probe_dormant_src3", name="Probe Dormant Source Three", is_active=True
        )
        station = MonitoredStation.objects.create(
            data_source=src, external_station_id="R077-3",
            station_name="Probe Empty-History Station",
            location=Point(-120.0, 37.0), is_active=False, last_data_at=None,
        )
        resp = auth_client.get(reverse("datasync:station_detail", args=[station.pk]))
        body = resp.content.decode()
        assert "No published readings yet." not in body
        assert (
            "No sync runs for Probe Dormant Source Three and no data records "
            "for this station yet." in body
        )
        # rule 6: the dashboard's old vocabulary never appears on this page.
        assert "On schedule" not in body
        assert "Behind schedule" not in body
        # the identity card stands alone, its fields in the account-info
        # two-column shape rather than one narrow card beside nothing.
        assert "field-grid-2" in body

    def test_a_station_with_one_fresh_reading_charts_and_says_up_to_date(
        self, auth_client
    ):
        src = DataSource.objects.create(
            code="probe_fresh_src", name="Probe Fresh Source", is_active=True
        )
        now = timezone.now()
        station = MonitoredStation.objects.create(
            data_source=src, external_station_id="R077-4",
            station_name="Probe Fresh Station",
            location=Point(-120.0, 37.0), is_active=True, last_data_at=now,
        )
        DataRecordStaging.objects.create(
            data_source=src, station=station, raw_data={}, observation_date=now,
            parameter_code="flow", value=Decimal("1.0"), unit="cfs",
            status="published",
        )
        resp = auth_client.get(reverse("datasync:station_detail", args=[station.pk]))
        body = resp.content.decode()
        assert '>Up to date</span>' in body
        assert body.count('id="telemetry-chart"') == 1
