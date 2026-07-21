# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run setup polish (Phase 48-02).

Locks the four first-run smoothing behaviors:

  1. needs_setup CTA — an empty install (zero Boundary rows) shows the admin a
     "Start here" call-to-action on the dashboard; a populated install does not;
     the flag is gated so a non-admin on an enforced deployment never sees it.
  2. Station review/enable — the wizard-completion review lists inactive stations
     in the chosen boundary and an "Enable all" bulk-activates them.
  3. Friendly GeoJSON-upload errors — a bad upload re-renders the wizard with a
     specific, plain-language message (not a generic failure).

Pinned to config.settings.local (prod settings 301-redirect the test client).
"""
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import reverse

from core.modules import ALL_MODULE_NAMES
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary

User = get_user_model()


def _seed_session(client, **values):
    """Pre-seed wizard state into the test client's session.

    Sessions are signed-cookie backed (ISS-069), which has NO server-side store,
    so ``session.save()`` alone does not carry injected values into the next
    request the way the old DB backend did. Refresh the client's session cookie
    from the saved session so the seeded keys actually reach the view (ISS-071).
    """
    session = client.session
    for key, value in values.items():
        session[key] = value
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

DASHBOARD_URL = reverse("accounting:dashboard")
WIZARD_URL = reverse("setup:wizard")


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _operator(username="operator", email="operator@example.com"):
    return User.objects.create_user(
        username=username, email=email, password="x",
        is_active=True, is_staff=False, agency_admin=False,
    )


def _admin(username="admin", email="admin@example.com"):
    return User.objects.create_user(
        username=username, email=email, password="x",
        is_active=True, is_staff=True, is_superuser=True,
    )


def _boundary(name="Test Boundary"):
    return Boundary.objects.create(
        name=name,
        geometry=MultiPolygon(Polygon.from_bbox((-119.5, 36.0, -119.0, 36.5))),
    )


# --------------------------------------------------------------------------
# Task 1 — needs_setup first-run CTA
# --------------------------------------------------------------------------


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_empty_install_shows_start_here_cta(db):
    client = Client()
    client.force_login(_admin())
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Start here" in body
    assert reverse("setup:wizard") in body


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_populated_install_hides_cta(db):
    _boundary()
    client = Client()
    client.force_login(_admin())
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 200
    assert "Start here" not in resp.content.decode()


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_cta_is_a_banner_not_a_wall(db):
    """A deployment with accounting data but no boundary still renders its
    dashboard — the Start-here CTA is a non-blocking banner above the content,
    not a replacement for it."""
    from tests.factories import ReportingPeriodFactory

    ReportingPeriodFactory()
    client = Client()
    client.force_login(_admin())
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Start here" in body            # CTA shows (no boundary yet)
    assert "Active Water Accounts" in body  # but the dashboard renders too


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_enforced_non_admin_never_sees_cta(db):
    """A read-only operator on an enforced deployment can't run setup, so the
    needs_setup flag stays False even with zero boundaries — no action they
    can't take, and no boundary query on their request."""
    client = Client()
    client.force_login(_operator())
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 200
    assert "Start here" not in resp.content.decode()


# --------------------------------------------------------------------------
# Task 2 — station review and bulk-enable at wizard completion
# --------------------------------------------------------------------------


def _source(name="DWR Water Data Library", code="dwr_wdl"):
    return DataSource.objects.create(name=name, code=code)


def _station(source, ext_id, lon, lat, active=False):
    return MonitoredStation.objects.create(
        data_source=source,
        external_station_id=ext_id,
        station_name=f"Station {ext_id}",
        location=Point(lon, lat, srid=4326),
        is_active=active,
    )


def test_station_review_groups_and_counts(db):
    from setup.services import build_station_review

    boundary = _boundary()
    wdl = _source("DWR Water Data Library", "dwr_wdl")
    usgs = _source("US Geological Survey", "usgs")
    # Two inside the boundary bbox, one active; one outside.
    _station(wdl, "A1", -119.25, 36.25, active=False)
    _station(usgs, "B1", -119.10, 36.10, active=True)
    _station(wdl, "OUT", -118.0, 35.0, active=False)  # outside boundary

    review = build_station_review(boundary)
    assert review["review_total"] == 2  # OUT excluded by point-in-polygon
    assert review["review_active"] == 1
    assert review["review_inactive"] == 1
    # Grouped by friendly provider name, not the raw code.
    names = {g["source_name"] for g in review["review_groups"]}
    assert names == {"DWR Water Data Library", "US Geological Survey"}


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_enable_all_activates_only_boundary_stations(db):
    boundary = _boundary()
    wdl = _source()
    inside = _station(wdl, "IN", -119.25, 36.25, active=False)
    outside = _station(wdl, "OUT", -118.0, 35.0, active=False)

    client = Client()
    client.force_login(_admin())
    _seed_session(client, setup_wizard_boundary_id=boundary.pk)

    resp = client.post(reverse("setup:activate_stations"))
    assert resp.status_code == 200

    inside.refresh_from_db()
    outside.refresh_from_db()
    assert inside.is_active is True      # enabled
    assert outside.is_active is False    # untouched — outside the watershed


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_rerun_discovery_does_not_auto_enable(db):
    """The discovery step creates stations inactive; only the explicit enable
    step flips them. A re-discovery of an already-present station must not
    silently activate it."""
    boundary = _boundary()
    wdl = _source()
    station = _station(wdl, "A1", -119.25, 36.25, active=False)

    # Simulate a second discovery pass (get_or_create no-ops on the existing row).
    MonitoredStation.objects.get_or_create(
        data_source=wdl,
        external_station_id="A1",
        defaults={"station_name": "x", "location": Point(-119.25, 36.25, srid=4326), "is_active": False},
    )
    station.refresh_from_db()
    assert station.is_active is False


# --------------------------------------------------------------------------
# Task 3 — friendly GeoJSON-upload errors + three-state step feedback
# --------------------------------------------------------------------------


def _upload(client, payload_bytes, name="boundary.geojson"):
    f = SimpleUploadedFile(name, payload_bytes, content_type="application/geo+json")
    return client.post(WIZARD_URL, {"action": "upload", "geojson_file": f})


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_upload_non_json_shows_specific_error(db):
    client = Client()
    client.force_login(_admin())
    resp = _upload(client, b"this is not json at all")
    assert resp.status_code == 200
    # Apostrophe in "isn't" is HTML-escaped through the {{ error }} variable;
    # assert on the apostrophe-free part of the message.
    assert "valid JSON" in resp.content.decode()
    assert not Boundary.objects.exists()


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_upload_wrong_geometry_type_shows_specific_error(db):
    client = Client()
    client.force_login(_admin())
    point = json.dumps({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-119.0, 36.0]},
        "properties": {},
    })
    resp = _upload(client, point.encode())
    assert resp.status_code == 200
    assert "Polygon or MultiPolygon is required" in resp.content.decode()
    assert not Boundary.objects.exists()


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_upload_empty_featurecollection_shows_specific_error(db):
    client = Client()
    client.force_login(_admin())
    fc = json.dumps({"type": "FeatureCollection", "features": []})
    resp = _upload(client, fc.encode())
    assert resp.status_code == 200
    assert "FeatureCollection is empty" in resp.content.decode()


def test_step_result_failed_is_not_a_green_check(db):
    failed = {"label": "Parcels", "success": False, "count": 0, "errors": ["API timed out"]}
    html = render_to_string("setup/partials/_step_result.html", {"result": failed})
    assert "wizard-step--error" in html
    assert "Couldn't complete" in html
    assert "API timed out" in html
    assert "wizard-step--complete" not in html


def test_step_result_empty_success_is_distinct_from_failure(db):
    empty = {"label": "Stations", "success": True, "count": 0, "errors": []}
    html = render_to_string("setup/partials/_step_result.html", {"result": empty})
    assert "wizard-step--complete" in html
    assert "None found" in html
    assert "wizard-step--error" not in html


def test_step_result_with_data_shows_count(db):
    ok = {"label": "Basins", "success": True, "count": 3, "errors": []}
    html = render_to_string("setup/partials/_step_result.html", {"result": ok})
    assert "3 records created" in html


# --------------------------------------------------------------------------
# Task 4 — completion routes to next steps, not a dead-end
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 49-02 — per-provider station discovery polling (ISS-051)
# --------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402

PROGRESS_URL = reverse("setup:progress")


def _discovery_adapter(code, *, raises=False):
    """Stand-in adapter: returns one in-bbox station, or raises (fail-soft test)."""
    a = MagicMock()
    a.missing_required_credential.return_value = None
    if raises:
        a.discover_stations.side_effect = RuntimeError("simulated provider outage")
    else:
        a.discover_stations.return_value = [{
            "station_id": f"{code.upper()}-1",
            "name": f"{code} station",
            "latitude": 36.25,
            "longitude": -119.25,  # inside the _boundary bbox
            "parameters": ["p"],
        }]
    return a


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_stations_phase_polls_one_provider_per_request(db, settings, monkeypatch):
    """The wizard advances ONE provider per stations-phase poll, renders a labeled
    row for each (a clean error row for one that raises), and reaches completion
    with the station review attached — never a single all-providers request that
    can outlast the worker timeout (ISS-051)."""
    from geography.management.commands import auto_populate as ap
    from setup.services import STATION_PROVIDERS

    settings.DATASYNC_MOCK_MODE = False
    for code in STATION_PROVIDERS:
        DataSource.objects.create(name=f"{code.upper()} Service", code=code)
    boundary = _boundary()

    # usgs (first provider) raises; every other provider discovers one station.
    monkeypatch.setattr(
        ap, "get_adapter",
        lambda code: _discovery_adapter(code, raises=(code == "usgs")),
    )

    client = Client()
    client.force_login(_admin())
    # Start the run already at the stations phase — the three geographic steps
    # call external ArcGIS services and are covered elsewhere.
    _seed_session(
        client,
        setup_wizard_boundary_id=boundary.pk,
        setup_wizard_step_index=3,  # stations is index 3
        setup_wizard_provider_index=0,
        setup_wizard_results=[
            {"step": "basins", "label": "Groundwater Basins", "count": 1, "errors": [], "success": True},
            {"step": "parcels", "label": "Parcel Boundaries", "count": 1, "errors": [], "success": True},
            {"step": "flowlines", "label": "Flowlines", "count": 1, "errors": [], "success": True},
        ],
    )

    n = len(STATION_PROVIDERS)  # 7
    # DB count after each poll proves one provider advances per request: usgs
    # raises (0 created), then each subsequent provider adds exactly one.
    expected_counts = [0, 1, 2, 3, 4, 5, 6]
    responses = []
    for i in range(n):
        resp = client.post(PROGRESS_URL)
        assert resp.status_code == 200
        assert MonitoredStation.objects.count() == expected_counts[i], (
            f"after poll {i + 1} expected {expected_counts[i]} stations"
        )
        responses.append(resp.content.decode())

    # Poll 1 — usgs raised → a clean labeled ERROR row, the run keeps going.
    first = responses[0]
    assert "USGS Service" in first
    assert "wizard-step--error" in first
    # The error message renders through a {{ }} variable, so its apostrophe is
    # HTML-escaped — assert on the apostrophe-free part (cf. the upload tests).
    assert "reach this data provider." in first
    assert "what's next" not in first.lower()  # still polling, not finished
    assert "Checking" in first                  # spinner names the next provider

    # Final poll — completion panel + station review attached for the 6 stations.
    final = responses[-1]
    assert "what's next" in final.lower()
    assert "Monitoring stations" in final       # build_station_review attached
    assert "Enable all 6" in final              # 6 inactive in-boundary stations


def test_step_result_skip_note_is_a_clean_row_not_an_error(db):
    """A provider's clean skip (e.g. no API key) renders its note on a green row,
    not a red error and not the generic 'None found' empty-success text."""
    skipped = {
        "label": "NOAA Weather Stations",
        "success": True,
        "count": 0,
        "errors": [],
        "note": "Skipped — no API key configured. You can add one later.",
    }
    html = render_to_string("setup/partials/_step_result.html", {"result": skipped})
    assert "wizard-step--complete" in html
    assert "no API key configured" in html
    assert "wizard-step--error" not in html
    assert "None found" not in html  # the note replaces the empty-success text


def test_completion_panel_routes_to_next_steps(db):
    boundary = _boundary()
    ctx = {
        "all_done": True,
        "results": [{"label": "Basins", "step": "basins", "success": True, "count": 2, "errors": []}],
        "boundary": boundary,
        # Supplied by hand because `render_to_string` runs no context processors:
        # the panel's next-step rows are module-guarded from Phase 88, and an
        # absent `enabled_modules` resolves to '' rather than raising -- so
        # without this the guarded rows would silently vanish and the assertions
        # below would be testing the wrong thing quietly.
        "enabled_modules": list(ALL_MODULE_NAMES),
        "review_groups": [],
        "review_total": 0,
        "review_active": 0,
        "review_inactive": 0,
    }
    html = render_to_string("setup/partials/_progress.html", ctx)
    assert "what's next" in html.lower()
    # Routes into the Getting Started walkthrough + the four ordered next actions.
    assert reverse("getting_started") in html
    assert reverse("parcels:list") in html
    assert reverse("wells:list") in html
    assert reverse("accounting:accounts_list") in html
    assert reverse("geography:zone_list") in html
    # The old single-link dead-end to the station list is gone from the panel.
    assert "Go to Stations" not in html
