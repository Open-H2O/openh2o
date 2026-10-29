# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Station and basin discovery tell "nothing there" from "could not ask".

Recorded responses only: the Bulletin 118 answer for a public GSA boundary is
stored under tests/fixtures/discovery_06/, and no test reaches the network.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.template.loader import render_to_string

from datasync.adapters import get_adapter
from datasync.adapters import usgs as usgs_module
from datasync.models import DataSource
from geography.models import Boundary, Zone
from setup.services import run_auto_populate_step, run_station_provider_step

FIXTURES = Path(__file__).parent / "fixtures" / "discovery_06"
BASE_DIR = Path(__file__).resolve().parent.parent

BOX = SimpleNamespace(extent=(-120.2, 36.9, -120.0, 37.1))
GEOM = Polygon.from_bbox((-120.2, 36.9, -120.0, 37.1))

ADAPTER_CODES = ["usgs", "cdec", "dwr_wdl", "dwr_sgma", "cimis", "noaa"]


def _adapter(code):
    adapter = get_adapter(code)
    adapter._rate_limit = lambda: None
    return adapter


def _geometry_for(code):
    return GEOM if code == "cimis" else BOX


def _response(status, body=""):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    resp.url = "https://example.invalid/site/"
    return resp


# ── Row 5: a provider that did not answer is not "none found" ───────────────


@pytest.mark.parametrize("code", ADAPTER_CODES)
@pytest.mark.parametrize("exc", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_adapter_discovery_lets_a_transport_failure_through(code, exc):
    adapter = _adapter(code)
    with patch.object(type(adapter), "_discover_request", side_effect=exc):
        with pytest.raises(type(exc)):
            adapter.discover_stations(_geometry_for(code))


# CDEC is fetched through the curl binary, which does not return the HTTP
# status, so an error page reaches it as an unreadable station table (its own
# test file covers that case) rather than as an HTTP error.
@pytest.mark.parametrize("code", [c for c in ADAPTER_CODES if c != "cdec"])
def test_adapter_discovery_lets_a_server_error_through(code):
    adapter = _adapter(code)
    with patch("datasync.adapters.base.requests.request", return_value=_response(500, "boom")):
        with pytest.raises(requests.HTTPError):
            adapter.discover_stations(_geometry_for(code))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "exc, status, sentence",
    [
        (requests.Timeout("slow"), "timed_out",
         "this data provider did not answer in time, so OpenH2O skipped it."),
        (requests.ConnectionError("down"), "failed",
         "the stations from this data provider did not load."),
    ],
)
@pytest.mark.parametrize("code", ["usgs", "cdec", "dwr_wdl"])
def test_wizard_reports_what_happened_when_a_provider_does_not_answer(
    code, exc, status, sentence
):
    boundary = Boundary.objects.create(name="Wizard box", geometry=MultiPolygon(GEOM))
    DataSource.objects.create(name=f"{code} source", code=code)
    adapter = _adapter(code)
    with patch("geography.management.commands.auto_populate.get_adapter", return_value=adapter), \
         patch.object(type(adapter), "_discover_request", side_effect=exc):
        count, errors, got = run_station_provider_step(boundary, code)
    assert (count, got) == (0, status)
    assert errors == [sentence]


def test_step_result_row_shows_the_timeout_sentence_and_not_none_found():
    html = render_to_string("setup/partials/_step_result.html", {"result": {
        "label": "U.S. Geological Survey", "success": False, "count": 0,
        "errors": ["this data provider did not answer in time, so OpenH2O skipped it."],
    }})
    assert "did not answer in time" in html
    assert "No new records" not in html


# ── Row 6: Groundwater Basins ───────────────────────────────────────────────


@pytest.fixture
def arroyo_boundary():
    geom = GEOSGeometry(
        (FIXTURES / "arroyo_boundary_geometry.json").read_text(), srid=4326
    )
    return Boundary.objects.create(name="Arroyo test", geometry=MultiPolygon(geom))


def _recorded_basins():
    return json.loads((FIXTURES / "b118_arroyo_grande.json").read_text())


@pytest.mark.django_db
def test_basins_step_creates_the_recorded_basins_then_says_already_there(arroyo_boundary):
    with patch(
        "geography.management.commands.auto_populate.query_by_boundary",
        return_value=_recorded_basins(),
    ) as query:
        first = run_auto_populate_step(arroyo_boundary, "basins")
        codes = sorted(
            Zone.objects.filter(boundary=arroyo_boundary).values_list("description", flat=True)
        )
        second = run_auto_populate_step(arroyo_boundary, "basins")

    assert query.call_count == 2
    assert [c.split()[-1] for c in codes] == ["3-012.01", "3-012.02"]

    count, errors = first
    assert (count, errors) == (2, [])
    assert first.note is None

    count, errors = second
    assert (count, errors) == (0, [])
    assert second.note == "2 basins found, already on this site."
    assert Zone.objects.filter(boundary=arroyo_boundary).count() == 2


@pytest.mark.django_db
def test_basins_step_with_nothing_found_carries_no_note(arroyo_boundary):
    with patch(
        "geography.management.commands.auto_populate.query_by_boundary", return_value=[]
    ):
        outcome = run_auto_populate_step(arroyo_boundary, "basins")
    assert tuple(outcome) == (0, [])
    assert outcome.note is None


def test_step_result_row_shows_the_basins_note_instead_of_none_found():
    html = render_to_string("setup/partials/_step_result.html", {"result": {
        "label": "Groundwater Basins", "success": True, "count": 0, "errors": [],
        "note": "2 basins found, already on this site.",
    }})
    assert "2 basins found, already on this site." in html
    assert "No new records" not in html


# ── Row 7: USGS discovery ───────────────────────────────────────────────────

SERIES = json.dumps({
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {
            "monitoring_location_id": "USGS-11111111",
            "parameter_code": "00060",
            "statistic_id": "00003",
            "computation_period_identifier": "Daily",
            "end": "2026-10-27T07:00:00+00:00",
        },
    }],
})
LOCATIONS = json.dumps({
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "id": "USGS-11111111",
        "properties": {"monitoring_location_name": "TEST CREEK NEAR NOWHERE", "site_type_code": "ST"},
        "geometry": {"type": "Point", "coordinates": [-120.1, 37.0]},
    }],
})
NO_SERIES = json.dumps({"type": "FeatureCollection", "features": []})


def _usgs_with(*responses):
    adapter = _adapter("usgs")
    return adapter, patch(
        "datasync.adapters.base.requests.request", side_effect=list(responses)
    )


def test_usgs_a_box_with_no_series_is_zero_sites_and_logs_no_warning(caplog):
    adapter, req = _usgs_with(_response(200, NO_SERIES))
    with req as request, caplog.at_level(logging.DEBUG):
        assert adapter.discover_stations(BOX) == []
    assert request.call_count == 1
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_usgs_finds_a_site_from_its_series_and_name():
    adapter, req = _usgs_with(_response(200, SERIES), _response(200, LOCATIONS))
    with req, patch.object(usgs_module, "_today", return_value=date(2026, 10, 29)):
        stations = adapter.discover_stations(BOX)
    assert [s["station_id"] for s in stations] == ["11111111"]
    assert (stations[0]["latitude"], stations[0]["longitude"]) == (37.0, -120.1)


def test_usgs_404_with_a_body_is_a_failure():
    adapter, req = _usgs_with(_response(404, "<html>Not Found</html>"))
    with req, pytest.raises(requests.HTTPError):
        adapter.discover_stations(BOX)


def test_usgs_server_error_is_a_failure():
    adapter, req = _usgs_with(_response(500, ""))
    with req, pytest.raises(requests.HTTPError):
        adapter.discover_stations(BOX)


def test_usgs_names_timeout_after_the_series_is_not_swallowed():
    adapter, req = _usgs_with(_response(200, SERIES), requests.Timeout("slow"))
    with req, patch.object(usgs_module, "_today", return_value=date(2026, 10, 29)):
        with pytest.raises(requests.Timeout):
            adapter.discover_stations(BOX)


def test_usgs_timeout_keeps_its_two_calls_inside_one_poll():
    worker_timeout = int(
        re.search(r"GUNICORN_TIMEOUT:-(\d+)", (BASE_DIR / "entrypoint.sh").read_text()).group(1)
    )
    adapter = get_adapter("usgs")
    calls = 2
    worst_case = calls * adapter.discovery_timeout + (calls - 1) * adapter.rate_limit_seconds
    # The cap is for a service that has stopped answering, and leaves 5 s of
    # margin under the worker limit.
    assert worst_case <= worker_timeout - 5
    assert adapter.discovery_timeout > get_adapter("cdec").discovery_timeout
