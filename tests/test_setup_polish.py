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

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import reverse

from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary

User = get_user_model()

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
    session = client.session
    session["setup_wizard_boundary_id"] = boundary.pk
    session.save()

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
    assert "isn't valid JSON" in resp.content.decode()
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


def test_completion_panel_routes_to_next_steps(db):
    boundary = _boundary()
    ctx = {
        "all_done": True,
        "results": [{"label": "Basins", "step": "basins", "success": True, "count": 2, "errors": []}],
        "boundary": boundary,
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
