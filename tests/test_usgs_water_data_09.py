# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The USGS adapter talks to the USGS Water Data APIs (api.waterdata.usgs.gov).

Recorded responses only, stored under tests/fixtures/usgs_water_data/: no test
reaches the network. The service documentation is at
https://api.waterdata.usgs.gov/docs/ogcapi/.
"""

import copy
import importlib
import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from django.apps import apps as django_apps
from django.core.management import call_command

from datasync.adapters import get_adapter
from datasync.adapters import usgs as usgs_module
from datasync.models import DataSource

FIXTURES = Path(__file__).parent / "fixtures" / "usgs_water_data"
REPO_ROOT = Path(__file__).resolve().parent.parent

BOX = SimpleNamespace(extent=(-120.9785, 37.0445, -120.0515, 37.5230))
TODAY = date(2026, 10, 29)


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _response(body, status=200):
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode() if not isinstance(body, bytes) else body
    resp.url = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/x/items"
    return resp


def _adapter():
    adapter = get_adapter("usgs")
    adapter._rate_limit = lambda: None
    return adapter


@pytest.fixture(autouse=True)
def _no_key_and_frozen_clock(monkeypatch):
    monkeypatch.delenv("USGS_API_KEY", raising=False)
    monkeypatch.setattr(usgs_module, "_today", lambda: TODAY, raising=False)


STATION = SimpleNamespace(
    external_station_id="11261500", parameters=["00060", "00065", "00010"]
)


# (a) the request ------------------------------------------------------------


def test_fetch_asks_the_daily_collection_for_the_station():
    with patch(
        "datasync.adapters.base.requests.request",
        return_value=_response({"features": [], "links": []}),
    ) as req:
        _adapter().fetch(STATION, date(2026, 10, 22), date(2026, 10, 29))
    assert req.call_count == 1
    args, kwargs = req.call_args
    assert args == ("GET", usgs_module.DAILY_URL)
    assert usgs_module.DAILY_URL == (
        "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items"
    )
    assert kwargs["params"] == {
        "f": "json",
        "monitoring_location_id": "USGS-11261500",
        "parameter_code": "00060,00065,00010",
        "datetime": "2026-10-22/2026-10-29",
        "limit": 10000,
    }
    assert "api_key" not in kwargs["params"]
    assert "X-Api-Key" not in (kwargs.get("headers") or {})


def test_fetch_without_station_parameters_asks_for_every_known_code():
    station = SimpleNamespace(external_station_id="11261500", parameters=[])
    with patch(
        "datasync.adapters.base.requests.request",
        return_value=_response({"features": [], "links": []}),
    ) as req:
        _adapter().fetch(station, date(2026, 10, 22), date(2026, 10, 29))
    codes = req.call_args.kwargs["params"]["parameter_code"].split(",")
    assert codes == list(usgs_module.PARAMETER_MAP)


def test_the_key_travels_in_a_header_and_never_in_the_url(monkeypatch, caplog):
    monkeypatch.setenv("USGS_API_KEY", "k-test-123")
    with patch(
        "datasync.adapters.base.requests.request",
        return_value=_response({"features": [], "links": []}),
    ) as req, caplog.at_level("DEBUG"):
        _adapter().fetch(STATION, date(2026, 10, 22), date(2026, 10, 29))
    kwargs = req.call_args.kwargs
    assert kwargs["headers"]["X-Api-Key"] == "k-test-123"
    assert "api_key" not in kwargs["params"]
    assert "k-test-123" not in caplog.text


def test_the_key_is_optional():
    assert _adapter().missing_required_credential() is None


# (b) paging -----------------------------------------------------------------


def test_a_two_page_answer_is_followed_to_the_end(monkeypatch):
    monkeypatch.setenv("USGS_API_KEY", "k-test-123")
    page1 = _load("daily_page_with_next.json")
    page2 = copy.deepcopy(page1)
    page2["links"] = [lk for lk in page2["links"] if lk["rel"] != "next"]
    next_href = next(lk["href"] for lk in page1["links"] if lk["rel"] == "next")
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(page1), _response(page2)],
    ) as req:
        features = _adapter().fetch(STATION, date(2026, 10, 22), date(2026, 10, 29))
    assert len(features) == 6
    assert req.call_count == 2
    second = req.call_args_list[1]
    assert second.args[1] == next_href
    assert second.kwargs["headers"]["X-Api-Key"] == "k-test-123"


def test_a_next_link_to_another_host_is_not_followed(monkeypatch, caplog):
    monkeypatch.setenv("USGS_API_KEY", "k-test-123")
    page1 = _load("daily_page_with_next.json")
    for lk in page1["links"]:
        if lk["rel"] == "next":
            lk["href"] = "https://example.invalid/ogcapi/v1/collections/daily/items?cursor=x"
    with patch(
        "datasync.adapters.base.requests.request", return_value=_response(page1)
    ) as req, caplog.at_level("WARNING"):
        features = _adapter().fetch(STATION, date(2026, 10, 22), date(2026, 10, 29))
    assert req.call_count == 1
    assert len(features) == 3
    assert "example.invalid" in caplog.text
    assert "k-test-123" not in caplog.text


def test_paging_stops_at_twenty_pages():
    page = _load("daily_page_with_next.json")
    with patch(
        "datasync.adapters.base.requests.request", side_effect=lambda *a, **k: _response(page)
    ) as req:
        _adapter().fetch(STATION, date(2026, 10, 22), date(2026, 10, 29))
    assert req.call_count == 20


def test_paging_stops_on_a_page_with_no_features():
    page1 = _load("daily_page_with_next.json")
    empty = copy.deepcopy(page1)
    empty["features"] = []
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(page1), _response(empty)],
    ) as req:
        features = _adapter().fetch(STATION, date(2026, 10, 22), date(2026, 10, 29))
    assert req.call_count == 2
    assert len(features) == 3


# (c) parse ------------------------------------------------------------------


def _five():
    return _load("daily_five_stations.json")["features"]


def test_parse_gives_one_record_per_station_code_and_day():
    records = _adapter().parse(_five())
    keys = [(r["station_id"], r["parameter_code"], r["observation_date"]) for r in records]
    assert len(keys) == len(set(keys))
    assert {r["station_id"] for r in records} == {
        "11261100", "11261500", "11262900", "11273400", "11274000",
    }
    assert all(not r["station_id"].startswith("USGS-") for r in records)


def test_water_temperature_is_the_daily_maximum_as_before():
    records = _adapter().parse(_five())
    temp = [
        r for r in records
        if r["station_id"] == "11261500" and r["parameter_code"] == "00010"
        and r["observation_date"] == "2026-10-28"
    ]
    assert len(temp) == 1
    assert temp[0]["value"] == 17.3
    assert temp[0]["statistic_id"] == "00001"


def test_lowest_statistic_wins_whatever_the_order():
    features = list(reversed(_five()))
    records = _adapter().parse(features)
    rec = next(
        r for r in records
        if r["station_id"] == "11273400" and r["parameter_code"] == "00010"
        and r["observation_date"] == "2026-10-29"
    )
    assert rec["value"] == 15.8


def test_units_use_the_spelling_the_pages_print():
    records = _adapter().parse(_five())
    units = {r["parameter_code"]: r["unit"] for r in records}
    assert units == {"00060": "ft3/s", "00010": "deg C"}
    well = _adapter().parse(_load("daily_well.json")["features"])
    assert {r["unit"] for r in well} == {"ft"}


def test_values_are_floats_and_the_date_is_a_date_string():
    records = _adapter().parse(_five())
    assert all(isinstance(r["value"], float) for r in records)
    assert all(len(r["observation_date"]) == 10 for r in records)
    flow = next(r for r in records if r["station_id"] == "11262900")
    assert flow["value"] == 119.0
    assert flow["observation_date"] == "2026-10-28"


def test_qualifiers_keep_the_old_list_shape():
    features = copy.deepcopy(_five()[:3])
    features[0]["properties"]["approval_status"] = "Approved"
    features[1]["properties"]["approval_status"] = "Provisional"
    features[1]["properties"]["qualifier"] = ["e"]
    features[1]["properties"]["parameter_code"] = "00060"
    features[1]["properties"]["time"] = "2026-10-20"
    features[2]["properties"]["approval_status"] = "Provisional"
    features[2]["properties"]["qualifier"] = "ICE"
    features[2]["properties"]["parameter_code"] = "00065"
    records = {r["parameter_code"] + r["observation_date"]: r for r in _adapter().parse(features)}
    assert records["000102026-10-28"]["qualifiers"] == ["A"]
    assert records["000602026-10-20"]["qualifiers"] == ["P", "e"]
    assert records["000652026-10-28"]["qualifiers"] == ["P", "ICE"]


def test_a_null_value_comes_back_as_none_and_validate_rejects_it():
    features = copy.deepcopy(_five()[:2])
    features[0]["properties"]["value"] = None
    adapter = _adapter()
    records = adapter.parse(features)
    assert [r["value"] for r in records].count(None) == 1
    valid, rejected = adapter.validate(records)
    assert len(rejected) == 1
    assert rejected[0]["rejection_reason"] == "null value"
    assert len(valid) == 1


def test_a_non_numeric_value_is_dropped_and_the_rest_kept(caplog):
    features = copy.deepcopy(_five())
    flow = next(f for f in features if f["properties"]["parameter_code"] == "00060")
    flow["properties"]["value"] = "Ice"
    with caplog.at_level("WARNING"):
        records = _adapter().parse(features)
    assert "non-numeric" in caplog.text
    assert len(records) == len(_adapter().parse(_five())) - 1


def test_mock_records_pass_through_parse():
    rows = json.loads(
        (REPO_ROOT / "datasync" / "fixtures" / "usgs.json").read_text()
    )["records"]
    assert _adapter().parse(rows) == rows


# (d) discovery --------------------------------------------------------------


def _discover_calls(series, wells, locations):
    return [_response(series), _response(wells), _response(locations)]


def test_discovery_answers_with_names_and_coordinates():
    series = _load("series_streams.json")
    wells = _load("series_wells.json")
    both = copy.deepcopy(series)
    both["features"] += wells["features"]
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(both), _response(_load("locations.json"))],
    ) as req:
        stations = _adapter().discover_stations(BOX)

    series_call, names_call = req.call_args_list
    assert series_call.args == ("GET", usgs_module.SERIES_URL)
    params = series_call.kwargs["params"]
    assert params["f"] == "json"
    assert params["parameter_code"] == "00060,72019"
    assert params["computation_period_identifier"] == "Daily"
    assert params["limit"] == 10000
    x0, y0, x1, y1 = (float(v) for v in params["bbox"].split(","))
    deg = 50 / 111.0
    assert (x0, y0) == pytest.approx((-120.9785 - deg, 37.0445 - deg), abs=1e-4)
    assert (x1, y1) == pytest.approx((-120.0515 + deg, 37.5230 + deg), abs=1e-4)
    assert series_call.kwargs["timeout"] == _adapter().discovery_timeout

    assert names_call.args == ("GET", usgs_module.LOCATIONS_URL)
    nparams = names_call.kwargs["params"]
    assert nparams["f"] == "json"
    assert nparams["properties"] == "monitoring_location_name,site_type_code"
    assert nparams["limit"] == 10000
    assert nparams["id"].split(",") == sorted(nparams["id"].split(","))

    assert [s["station_id"] for s in stations] == [
        "11153000", "11261100", "11261500", "364518120222001", "365325120391505",
    ]
    by_id = {s["station_id"]: s for s in stations}
    flow = by_id["11261500"]
    assert flow["name"] == "SAN JOAQUIN R A FREMONT FORD BRIDGE CA"
    assert flow["site_type"] == "ST"
    assert flow["parameters"] == usgs_module.STREAM_PARAMS
    assert flow["longitude"] == pytest.approx(-120.9309993, abs=1e-5)
    assert flow["latitude"] == pytest.approx(37.3099115, abs=1e-5)
    well = by_id["364518120222001"]
    assert well["name"] == "013S015E31J006M"
    assert well["site_type"] == "GW"
    assert well["parameters"] == usgs_module.GW_PARAMS


def test_a_series_that_ended_over_a_year_ago_is_dropped():
    series = _load("series_streams.json")
    ids = {f["properties"]["monitoring_location_id"] for f in series["features"]}
    assert "USGS-11254000" in ids
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(series), _response(_load("locations.json"))],
    ) as req:
        stations = _adapter().discover_stations(BOX)
    asked = req.call_args_list[1].kwargs["params"]["id"].split(",")
    assert "USGS-11254000" not in asked
    assert "11254000" not in {s["station_id"] for s in stations}


def test_the_365_day_rule_follows_the_clock(monkeypatch):
    series = _load("series_streams.json")
    monkeypatch.setattr(usgs_module, "_today", lambda: date(2028, 1, 1))
    with patch(
        "datasync.adapters.base.requests.request", return_value=_response(series)
    ) as req:
        assert _adapter().discover_stations(BOX) == []
    assert req.call_count == 1


def test_a_non_usgs_id_is_dropped():
    series = _load("series_streams.json")
    series["features"][0]["properties"]["monitoring_location_id"] = "AZ014-331122000"
    dropped = "AZ014-331122000"
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(series), _response(_load("locations.json"))],
    ) as req:
        _adapter().discover_stations(BOX)
    asked = req.call_args_list[1].kwargs["params"]["id"]
    assert dropped not in asked
    assert all(i.startswith("USGS-") for i in asked.split(","))


def test_no_names_call_when_no_series_is_kept():
    series = _load("series_streams.json")
    series["features"] = [
        f for f in series["features"]
        if f["properties"]["monitoring_location_id"] == "USGS-11254000"
    ]
    with patch(
        "datasync.adapters.base.requests.request", return_value=_response(series)
    ) as req:
        assert _adapter().discover_stations(BOX) == []
    assert req.call_count == 1


def test_names_are_asked_in_chunks_of_at_most_a_hundred():
    template = _load("series_streams.json")["features"][0]
    feats = []
    for i in range(230):
        f = copy.deepcopy(template)
        f["properties"]["monitoring_location_id"] = f"USGS-{10000000 + i}"
        f["properties"]["end"] = "2026-10-27T07:00:00+00:00"
        feats.append(f)
    empty_names = {"type": "FeatureCollection", "features": []}
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response({"features": feats}), *[_response(empty_names)] * 3],
    ) as req:
        _adapter().discover_stations(BOX)
    sizes = [len(c.kwargs["params"]["id"].split(",")) for c in req.call_args_list[1:]]
    assert sizes == [100, 100, 30]


def test_a_timeout_propagates():
    with patch(
        "datasync.adapters.base.requests.request", side_effect=requests.Timeout("slow")
    ):
        with pytest.raises(requests.Timeout):
            _adapter().discover_stations(BOX)


def test_a_timeout_on_the_names_call_propagates():
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(_load("series_streams.json")), requests.Timeout("slow")],
    ):
        with pytest.raises(requests.Timeout):
            _adapter().discover_stations(BOX)


def test_an_error_status_propagates():
    with patch(
        "datasync.adapters.base.requests.request", return_value=_response({}, status=503)
    ):
        with pytest.raises(requests.HTTPError):
            _adapter().discover_stations(BOX)


def test_the_discovery_key_header_is_sent(monkeypatch):
    monkeypatch.setenv("USGS_API_KEY", "k-test-123")
    with patch(
        "datasync.adapters.base.requests.request",
        side_effect=[_response(_load("series_streams.json")), _response(_load("locations.json"))],
    ) as req:
        _adapter().discover_stations(BOX)
    for call in req.call_args_list:
        assert call.kwargs["headers"]["X-Api-Key"] == "k-test-123"
        assert "api_key" not in call.kwargs["params"]


def test_the_two_discovery_calls_fit_inside_one_poll():
    adapter = _adapter()
    assert adapter.discovery_timeout == 15.0
    assert 2 * adapter.discovery_timeout + adapter.rate_limit_seconds < 60


# (e) the old address is gone from product code -------------------------------

OLD_ADDRESS = "waterservices.usgs." + "gov"
SKIP_DIRS = {
    ".git", ".planning", "tests", "__pycache__", "node_modules", "staticfiles",
    "media", "backups", "logs", "secrets", ".venv", "venv",
}
SCANNED_SUFFIXES = {".py", ".html", ".js", ".css", ".sh", ".json", ".toml", ".txt", ".yml"}


def _product_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.split("\n")
        files = [REPO_ROOT / n for n in out if n]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in REPO_ROOT.rglob("*") if p.is_file()]
    for path in files:
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.is_file() and (path.suffix in SCANNED_SUFFIXES or path.name == "Makefile"):
            yield path


def test_the_old_service_address_appears_only_in_the_address_migration():
    hits = set()
    scanned = 0
    for path in _product_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        if OLD_ADDRESS in text:
            hits.add(path.relative_to(REPO_ROOT).as_posix())
    assert scanned > 100, "the scan found too few files to mean anything"
    assert hits == {"datasync/migrations/0007_usgs_water_data_address.py"}


# (f) the stored address -----------------------------------------------------

MIGRATION = "datasync.migrations.0007_usgs_water_data_address"
NEW_URL = "https://api.waterdata.usgs.gov"
OLD_URL = "https://" + OLD_ADDRESS


@pytest.mark.django_db
def test_seeding_gives_a_new_site_the_new_address():
    call_command("seed_data_sources")
    assert DataSource.objects.get(code="usgs").url == NEW_URL


@pytest.mark.django_db
def test_the_migration_moves_an_old_address_and_leaves_an_edited_one():
    module = importlib.import_module(MIGRATION)
    DataSource.objects.create(code="usgs", name="USGS NWIS", url=OLD_URL)
    other = DataSource.objects.create(code="cdec", name="CDEC", url=OLD_URL)

    module.forward(django_apps, None)
    assert DataSource.objects.get(code="usgs").url == NEW_URL
    assert DataSource.objects.get(code="cdec").url == OLD_URL, "only the usgs row moves"
    other.delete()

    module.reverse(django_apps, None)
    assert DataSource.objects.get(code="usgs").url == OLD_URL

    DataSource.objects.filter(code="usgs").update(url="https://usgs.example.org")
    module.forward(django_apps, None)
    assert DataSource.objects.get(code="usgs").url == "https://usgs.example.org"
    module.reverse(django_apps, None)
    assert DataSource.objects.get(code="usgs").url == "https://usgs.example.org"
