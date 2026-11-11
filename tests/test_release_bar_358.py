# SPDX-License-Identifier: AGPL-3.0-or-later
"""A hand-entered station's page opens when it holds a current reading and a voided one.

The card lists the station's published readings (a date and time each) beside the readings a
person typed and later voided (a day each). Both kinds sit in one list sorted newest first, so
the page must order a day against a date and time without failing.
"""

import html
from io import StringIO

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from core import corrections
from core.models import User
from datasync.models import DataRecordStaging, DataSource, MonitoredStation, TypedReading

pytestmark = pytest.mark.django_db

REASON = "typed against the wrong gauge"


@pytest.fixture
def operator():
    return User.objects.create_user(
        username="operator", email="operator@example.org", password="a-good-passw0rd",
        is_active=True,
    )


@pytest.fixture
def hand_station():
    call_command("seed_data_sources", stdout=StringIO())
    return MonitoredStation.objects.create(
        data_source=DataSource.objects.get(code="manual"),
        external_station_id="MC-CHK9",
        station_name="Main Canal at Check 9 staff gauge (invented for this test)",
        location=Point(-120.6012, 37.3321, srid=4326),
        is_active=True,
    )


def _type(client, station, day, value):
    response = client.post(
        reverse("datasync:station_reading_add", args=[station.pk]),
        {"observation_date": day, "value": value, "parameter": "00065", "notes": ""},
    )
    assert response.status_code == 302


def test_a_station_with_a_current_and_a_voided_reading_opens_and_lists_both(
    hand_station, operator
):
    client = Client()
    client.force_login(operator)
    _type(client, hand_station, "2026-10-29", "3.10")
    _type(client, hand_station, "2026-10-30", "3.42")
    first = TypedReading.objects.get(observation_date="2026-10-29")
    corrections.void(first, user=operator, reason=REASON)
    assert DataRecordStaging.objects.current().filter(station=hand_station).count() == 1

    response = client.get(reverse("datasync:station_detail", args=[hand_station.pk]))

    assert response.status_code == 200
    body = html.unescape(response.content.decode())
    assert "3.42" in body
    assert "3.10" in body
    assert body.index("Oct 30, 2026") < body.index("Oct 29, 2026")
