# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the CIMIS adapter against DWR's new 2026 Web API (Phase 68 / ISS-007).

Hermetic — no live HTTP. Fixtures are real captured responses from the new API:
  datasync/fixtures/cimis_station_new.json  (GetAllStations slice)
  datasync/fixtures/cimis_data_new.json     (GetDataByStationNumber slice)

Covers the three correctness surfaces that changed:
  - HMS combined-string lat/lon parsing (the "synced but 0 stations" bug)
  - parse() reading the day-asce-eto record key
  - validate() ETo bounds keyed on day-asce-eto (not the retired day-eto)
"""

import json
from pathlib import Path

import datasync
from datasync.adapters.cimis import CIMISAdapter, _parse_hms_decimal

FIX = Path(datasync.__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


# ── HMS decimal parsing (the 0-stations bug) ────────────────────────────────


class TestParseHmsDecimal:
    def test_latitude_decimal_half(self):
        assert _parse_hms_decimal("36º48'52N / 36.814444") == 36.814444

    def test_longitude_signed_decimal_half(self):
        assert _parse_hms_decimal("-119º43'54W / -119.73167") == -119.73167

    def test_empty_returns_none(self):
        assert _parse_hms_decimal("") is None

    def test_none_returns_none(self):
        assert _parse_hms_decimal(None) is None

    def test_garbage_returns_none(self):
        assert _parse_hms_decimal("not a coordinate") is None

    def test_raw_float_string_still_parses(self):
        # Defensive: a bare decimal (no HMS prefix) should still work.
        assert _parse_hms_decimal("36.5") == 36.5


# ── parse(): new day-asce-eto record key ────────────────────────────────────


class TestParse:
    def test_extracts_asce_eto_value(self):
        adapter = CIMISAdapter()
        records = adapter.parse(_load("cimis_data_new.json"))
        eto = [r for r in records if r["parameter_code"] == "day-asce-eto" and r["value"] is not None]
        assert eto, "no day-asce-eto records parsed"
        assert eto[0]["value"] == 0.32
        assert eto[0]["unit"] == "in"

    def test_all_five_parameters_present(self):
        adapter = CIMISAdapter()
        records = adapter.parse(_load("cimis_data_new.json"))
        codes = {r["parameter_code"] for r in records}
        assert codes == {
            "day-asce-eto", "day-precip", "day-sol-rad-avg",
            "day-wind-spd-avg", "day-air-tmp-avg",
        }


# ── validate(): ETo bounds keyed on day-asce-eto ────────────────────────────


class TestValidate:
    def test_accepts_normal_eto(self):
        adapter = CIMISAdapter()
        valid, rejected = adapter.validate([
            {"parameter_code": "day-asce-eto", "value": 0.32, "unit": "in"},
        ])
        assert len(valid) == 1 and not rejected

    def test_rejects_negative_eto(self):
        adapter = CIMISAdapter()
        valid, rejected = adapter.validate([
            {"parameter_code": "day-asce-eto", "value": -0.1, "unit": "in"},
        ])
        assert not valid and rejected[0]["rejection_reason"] == "negative ETo"

    def test_rejects_eto_over_one_inch(self):
        adapter = CIMISAdapter()
        valid, rejected = adapter.validate([
            {"parameter_code": "day-asce-eto", "value": 1.5, "unit": "in"},
        ])
        assert not valid and rejected[0]["rejection_reason"] == "ETo exceeds 1.0 in/day"

    def test_rejects_null_value(self):
        adapter = CIMISAdapter()
        valid, rejected = adapter.validate([
            {"parameter_code": "day-precip", "value": None, "unit": "in"},
        ])
        assert not valid and rejected[0]["rejection_reason"] == "null value"


# ── discover_stations(): the bug is fixed (non-empty result) ────────────────


class TestDiscoverStations:
    def _adapter_with_fixture(self):
        adapter = CIMISAdapter()

        class _Resp:
            def json(self_inner):
                return _load("cimis_station_new.json")

        adapter._discover_request = lambda *a, **k: _Resp()
        return adapter

    def test_returns_stations_near_boundary(self):
        from django.contrib.gis.geos import Point

        adapter = self._adapter_with_fixture()
        # Central San Joaquin Valley point; fixture has Fresno-area stations.
        boundary = Point(-119.7, 36.6, srid=4326)
        results = adapter.discover_stations(boundary, radius_km=100)

        assert results, "discovery returned 0 stations — the HMS parse bug is back"
        # Every returned station has real numeric coordinates (not skipped).
        for r in results:
            assert isinstance(r["latitude"], float)
            assert isinstance(r["longitude"], float)
            assert r["station_id"]

    def test_fresno_station_coordinates_parsed(self):
        from django.contrib.gis.geos import Point

        adapter = self._adapter_with_fixture()
        boundary = Point(-119.7, 36.6, srid=4326)
        results = adapter.discover_stations(boundary, radius_km=100)
        by_id = {r["station_id"]: r for r in results}
        # Station 1 (Fresno/F.S.U.) — HmsLatitude "36º48'52N / 36.814444".
        assert "1" in by_id, "Fresno station not discovered"
        assert by_id["1"]["latitude"] == 36.814444
        assert by_id["1"]["longitude"] == -119.73167
