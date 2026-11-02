# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed station readings (151.6-05, design C).

A station of the "Entered by hand" source never syncs: a person types each
reading on the station's page. Saved readings are ordinary published rows in
``DataRecordStaging``, so the telemetry chart and the readings table show them
with no special case. A typed value at any other source's station is refused,
because the public service is the record there.
"""

import html
from datetime import datetime
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from core.access import READ_ONLY_MESSAGE
from core.models import User
from datasync.models import (
    DataRecordStaging,
    DataSource,
    MonitoredStation,
    TypedReading,
)

pytestmark = pytest.mark.django_db

PACIFIC = ZoneInfo("America/Los_Angeles")
BY_HAND_SENTENCE = (
    "Readings at a station entered by hand are typed on the station's page. "
    "OpenH2O fetches nothing for them."
)
TYPED_ONLY_AT_HAND = "Readings are typed only at a station entered by hand."
DUPLICATE = "A reading for this measurement on this date is already on file."


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
def manual():
    call_command("seed_data_sources", stdout=StringIO())
    return DataSource.objects.get(code="manual")


@pytest.fixture
def hand_station(manual):
    return MonitoredStation.objects.create(
        data_source=manual,
        external_station_id="MC-CHK4",
        station_name="Main Canal at Check 4 staff gauge",
        location=Point(-120.6012, 37.3321, srid=4326),
        is_active=True,
    )


@pytest.fixture
def usgs_station():
    source, _ = DataSource.objects.get_or_create(
        code="usgs", defaults={"name": "USGS NWIS"}
    )
    return MonitoredStation.objects.create(
        data_source=source,
        external_station_id="11261500",
        station_name="Probe USGS gauge",
        location=Point(-120.9, 37.3, srid=4326),
        is_active=True,
    )


def _add_url(station):
    return reverse("datasync:station_reading_add", args=[station.pk])


def _typed(**over):
    data = {
        "observation_date": "2026-10-30",
        "value": "3.42",
        "parameter": "00065",
        "notes": "",
    }
    data.update(over)
    return data


def _page(client, station):
    response = client.get(reverse("datasync:station_detail", args=[station.pk]))
    assert response.status_code == 200
    return html.unescape(response.content.decode())


# -- The source ----------------------------------------------------------------------------


def test_seed_creates_the_source_once(manual):
    assert manual.name == "Entered by hand"
    assert manual.is_active is True
    call_command("seed_data_sources", stdout=StringIO())
    assert DataSource.objects.filter(code="manual").count() == 1


def test_sync_source_manual_prints_its_sentence_and_exits_cleanly(manual, hand_station):
    out = StringIO()
    call_command("sync_source", "manual", stdout=out)
    assert BY_HAND_SENTENCE in out.getvalue()
    from datasync.models import DataSyncLog

    assert DataSyncLog.objects.count() == 0


def test_sync_all_does_not_call_the_manual_source(manual):
    with mock.patch(
        "datasync.management.commands.sync_all.call_command"
    ) as calls:
        call_command("sync_all", stdout=StringIO())
    called = [c.args[1] for c in calls.call_args_list]
    assert called, "the other seeded sources are still called"
    assert "manual" not in called


def test_the_schedule_sentence_for_a_hand_station(hand_station):
    from datasync import schedule

    assert (
        schedule.station_sentence(hand_station)
        == "An Operator or Administrator types each reading on this page."
    )


def test_the_data_migration_adds_the_source_to_an_existing_site_once():
    import importlib

    migration = importlib.import_module("datasync.migrations.0010_entered_by_hand_source")
    from django.apps import apps

    DataSource.objects.filter(code="manual").delete()
    DataSource.objects.get_or_create(code="usgs", defaults={"name": "USGS NWIS"})
    migration.add_source(apps, None)
    migration.add_source(apps, None)
    assert DataSource.objects.filter(code="manual", name="Entered by hand").count() == 1


def test_the_data_migration_leaves_an_empty_install_to_the_seed():
    import importlib

    migration = importlib.import_module("datasync.migrations.0010_entered_by_hand_source")
    from django.apps import apps

    DataSource.objects.all().delete()
    migration.add_source(apps, None)
    assert DataSource.objects.count() == 0


# -- Add monitoring station -------------------------------------------------------------------


def test_add_station_offers_entered_by_hand_and_creates_such_a_station(manual, operator):
    client = _client(operator)
    body = html.unescape(client.get(reverse("datasync:station_add")).content.decode())
    assert "Entered by hand" in body
    assert (
        "This page adds one monitoring station. OpenH2O syncs its readings from a "
        "public data source, or a person types them on the station's page."
    ) in body
    assert "Station ID" in body
    assert "External station ID" not in body
    assert (
        "The source's own ID, such as 11303000 at USGS, or the organization's own "
        "name or number for a station entered by hand."
    ) in body

    response = client.post(reverse("datasync:station_add"), {
        "data_source": str(manual.pk),
        "external_station_id": "MC-CHK4",
        "station_name": "Main Canal at Check 4 staff gauge",
        "lat": "37.3321",
        "lng": "-120.6012",
    })
    assert response.status_code == 302
    station = MonitoredStation.objects.get(data_source=manual)
    assert station.external_station_id == "MC-CHK4"


# -- The station page ------------------------------------------------------------------------------


def test_a_hand_station_page_drops_the_sync_controls(hand_station, operator):
    body = _page(_client(operator), hand_station)

    assert "Fetch readings now" not in body
    assert "Turn syncing" not in body
    assert 'id="toggle-cell"' not in body
    assert "Up to date" not in body and "Dormant" not in body and "Slightly behind" not in body
    assert "An Operator or Administrator types each reading on this page." in body
    assert "This page shows the station's readings and details." in body
    assert "recent syncs" not in body
    assert "Recent sync logs" not in body
    assert "Station ID" in body
    assert "External station ID" not in body
    assert "The ID is the organization's own name or number for the station." in body
    assert "Add a reading" in body


def test_the_form_has_the_drawn_fields_and_the_parameter_choices(hand_station, operator):
    body = _page(_client(operator), hand_station)

    for label in ("Date", "Value", "Parameter", "Notes"):
        assert f">{label}" in body
    assert 'class="btn-primary">Add reading<' in body
    for option in (
        "Gage Height (ft)",
        "Discharge (cfs)",
        "Water Temperature (deg C)",
        "Depth to Water Level (ft below surface)",
    ):
        assert f">{option}</option>" in body


def test_a_viewer_sees_the_readings_card_alone(hand_station, viewer):
    body = _page(_client(viewer), hand_station)

    assert "Readings, newest first" in body
    assert "Add a reading" not in body
    assert 'name="observation_date"' not in body
    assert "Recent sync logs" not in body


def test_a_usgs_station_page_keeps_its_sync_controls_and_has_no_form(usgs_station, operator):
    body = _page(_client(operator), usgs_station)

    assert "Add a reading" not in body
    assert 'name="observation_date"' not in body
    assert 'id="toggle-cell"' in body
    assert "Recent sync logs" in body or "Sync history" in body


# -- Typing a reading ----------------------------------------------------------------------------------


def test_a_writers_reading_is_saved_published_and_shown(hand_station, operator):
    client = _client(operator)
    response = client.post(
        _add_url(hand_station),
        _typed(notes="Boards pulled from the check at 7 a.m."),
    )

    assert response.status_code == 302
    row = DataRecordStaging.objects.get(station=hand_station)
    assert row.status == "published"
    assert row.published_at is not None
    assert row.statistic == ""
    assert row.parameter_code == "00065"
    assert row.unit == "ft"
    assert str(row.value) == "3.4200"
    assert row.data_source == hand_station.data_source
    assert row.observation_date == datetime(2026, 10, 30, 0, 0, tzinfo=PACIFIC)
    assert row.raw_data["typed_by"] == "operator@example.org"
    assert row.raw_data["notes"] == "Boards pulled from the check at 7 a.m."
    assert datetime.fromisoformat(row.raw_data["typed_at"]).tzinfo is not None

    hand_station.refresh_from_db()
    assert hand_station.last_data_at == row.observation_date

    body = _page(client, hand_station)
    assert "Gage Height (ft)" in body
    assert "3.42" in body
    assert "Oct 30, 2026" in body
    assert "Boards pulled from the check at 7 a.m." in body


def test_the_chart_and_current_readings_pick_the_typed_reading_up(hand_station, operator):
    client = _client(operator)
    client.post(_add_url(hand_station), _typed())

    body = _page(client, hand_station)
    assert "Current readings" in body

    data = client.get(
        reverse("datasync:station_chart_data", args=[hand_station.pk])
    ).json()
    assert data["selected_parameter"] == "00065"
    assert data["datasets"][0]["data"] == [3.42]


def test_the_newest_reading_sets_last_data_and_an_older_one_does_not_move_it_back(
    hand_station, operator
):
    client = _client(operator)
    client.post(_add_url(hand_station), _typed(observation_date="2026-10-30"))
    client.post(_add_url(hand_station), _typed(observation_date="2026-10-20", value="3.80"))

    hand_station.refresh_from_db()
    assert hand_station.last_data_at == datetime(2026, 10, 30, 0, 0, tzinfo=PACIFIC)


def test_a_typed_reading_leaves_an_audit_row_and_a_history_event(hand_station, operator):
    _client(operator).post(
        _add_url(hand_station), _typed(notes="Read at the staff gauge")
    )

    typed = TypedReading.objects.get()
    row = DataRecordStaging.objects.get(station=hand_station)
    assert typed.station == hand_station
    assert typed.reading == row
    assert typed.typed_by == operator
    assert typed.typed_by_email == "operator@example.org"
    assert typed.typed_at is not None
    assert typed.parameter_code == "00065"
    assert typed.observation_date.isoformat() == "2026-10-30"
    assert str(typed.value) == "3.4200"
    assert typed.notes == "Read at the staff gauge"
    insert = typed.events.get(pgh_label="insert")
    assert insert.pgh_context is not None
    assert insert.pgh_context.metadata["user"] == operator.pk


def test_a_second_reading_for_the_same_measurement_and_date_is_refused(
    hand_station, operator
):
    client = _client(operator)
    client.post(_add_url(hand_station), _typed())
    response = client.post(_add_url(hand_station), _typed(value="9.99"))

    assert response.status_code == 200
    assert DUPLICATE in html.unescape(response.content.decode())
    assert DataRecordStaging.objects.filter(station=hand_station).count() == 1
    assert TypedReading.objects.count() == 1
    assert str(DataRecordStaging.objects.get().value) == "3.4200"


def test_the_same_date_for_another_parameter_is_allowed(hand_station, operator):
    client = _client(operator)
    client.post(_add_url(hand_station), _typed())
    response = client.post(_add_url(hand_station), _typed(parameter="00060", value="41"))

    assert response.status_code == 302
    assert DataRecordStaging.objects.filter(station=hand_station).count() == 2


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"observation_date": ""}, "Enter the date of the reading."),
        ({"observation_date": "30/10/2026"}, "Enter the date of the reading."),
        ({"value": ""}, "Enter the value as a number."),
        ({"value": "three"}, "Enter the value as a number."),
        ({"value": "NaN"}, "Enter the value as a number."),
        ({"parameter": ""}, "Choose a parameter."),
        ({"parameter": "99999"}, "Choose a parameter."),
    ],
)
def test_an_invalid_form_says_why_keeps_what_was_typed_and_saves_nothing(
    hand_station, operator, bad, message
):
    response = _client(operator).post(
        _add_url(hand_station), _typed(notes="Keep this note", **bad)
    )

    body = html.unescape(response.content.decode())
    assert response.status_code == 200
    assert message in body
    assert "Keep this note" in body
    assert DataRecordStaging.objects.count() == 0
    assert TypedReading.objects.count() == 0


def test_an_invalid_form_keeps_the_other_fields(hand_station, operator):
    response = _client(operator).post(
        _add_url(hand_station), _typed(value="three", observation_date="2026-10-29")
    )
    body = response.content.decode()
    assert 'value="2026-10-29"' in body
    assert 'value="three"' in body


def test_a_viewer_cannot_type_a_reading(hand_station, viewer):
    response = _client(viewer).post(_add_url(hand_station), _typed())

    assert response.status_code == 403
    assert READ_ONLY_MESSAGE in response.content.decode()
    assert DataRecordStaging.objects.count() == 0


def test_a_signed_out_visitor_cannot_type_a_reading(hand_station):
    response = _client().post(_add_url(hand_station), _typed())
    assert response.status_code == 302
    assert DataRecordStaging.objects.count() == 0


def test_a_reading_at_another_sources_station_is_refused(usgs_station, operator):
    response = _client(operator).post(_add_url(usgs_station), _typed())

    assert response.status_code == 403
    assert TYPED_ONLY_AT_HAND in html.unescape(response.content.decode())
    assert DataRecordStaging.objects.count() == 0
    assert TypedReading.objects.count() == 0
    usgs_station.refresh_from_db()
    assert usgs_station.last_data_at is None


def test_a_get_of_the_reading_route_is_not_allowed(hand_station, operator):
    response = _client(operator).get(_add_url(hand_station))
    assert response.status_code == 405


# -- A hand station stays out of "fetched from a provider" -----------------------------------------


def test_the_monitoring_dashboard_has_no_card_for_the_manual_source(hand_station, operator):
    body = html.unescape(
        _client(operator).get(reverse("datasync:monitoring_dashboard")).content.decode()
    )
    assert "Entered by hand" not in body


def test_a_hand_station_is_not_counted_as_a_syncing_station(hand_station, operator):
    from datasync.views import _build_source_status

    codes = [s["source"].code for s in _build_source_status(None, datetime.now(PACIFIC))]
    assert "manual" not in codes


def test_site_health_does_not_judge_the_manual_source_by_its_last_sync(hand_station):
    from health.checks import check_sync_freshness

    result = check_sync_freshness()
    assert "manual" not in result["details"]


def test_the_syncing_station_count_leaves_out_hand_stations(hand_station, usgs_station):
    from config.views import _public_counts

    counts = _public_counts()
    assert counts["station_count"] == 2
    assert counts["active_station_count"] == 1


def test_a_hand_station_is_not_pruned_for_having_no_readings(hand_station):
    out = StringIO()
    call_command("prune_dataless_stations", "--delete", "--purge-inactive", stdout=out)
    assert MonitoredStation.objects.filter(pk=hand_station.pk).exists()


def test_the_monthly_prune_never_deletes_a_typed_reading(hand_station, operator):
    from datetime import timedelta

    from django.utils import timezone

    _client(operator).post(_add_url(hand_station), _typed())
    DataRecordStaging.objects.update(created_at=timezone.now() - timedelta(days=4000))
    call_command("prune_old_data", "--confirm", stdout=StringIO())
    assert DataRecordStaging.objects.filter(station=hand_station).count() == 1
