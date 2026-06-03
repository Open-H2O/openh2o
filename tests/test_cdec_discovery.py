# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Regression tests for CDEC station discovery (Phase 49, plan 01 — ISS-048).

CDEC is a key-free, wired provider that was contributing ZERO stations to every
new boundary because ``discover_stations`` pointed at ``/dynamicapp/staMeta`` —
a human-facing HTML page — and called ``resp.json()`` on it, raising
``json.JSONDecodeError: Expecting value: line 2 column 1``. The old broad
``except Exception`` swallowed it into an empty list, but the only trace was the
bare decoder error, so the failure read as "CDEC simply has no nearby stations."

These tests pin two behaviours:
  1. A response we cannot parse into stations (HTML page, empty body, JSON of
     the wrong shape) returns [] AND logs one clear, greppable warning that
     names CDEC and the cause — never a bare JSONDecodeError, never a crash.
  2. A real CDEC station-search results table parses into the standard station
     dict shape and is filtered to the boundary extent.

The discovery source is CDEC's ``staSearch`` results page (the only
machine-reachable station list — CDEC has no station-search JSON endpoint), so
the fixtures are HTML, not JSON.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from datasync.adapters.cdec import CDECAdapter

FIXTURES = Path(__file__).resolve().parent.parent / "datasync" / "fixtures"


class _FakeResponse:
    """Minimal stand-in for requests.Response for monkeypatched _request."""

    def __init__(self, text, content_type="text/html;charset=UTF-8"):
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def json(self):
        # Mirrors requests.Response.json(): raises on a non-JSON body, exactly
        # as it did against the live HTML page that caused ISS-048.
        import json

        return json.loads(self.text)


def _fixture(name):
    return (FIXTURES / name).read_text()


def _adapter_returning(text, content_type="text/html;charset=UTF-8"):
    """A CDECAdapter whose _request yields a fixed fake response."""
    adapter = CDECAdapter()
    adapter._request = lambda method, url, **kwargs: _FakeResponse(text, content_type)
    return adapter


# Kaweah-area bounding box (xmin, ymin, xmax, ymax) = (lon, lat) extent.
KAWEAH_BBOX = SimpleNamespace(extent=(-119.3, 36.0, -118.7, 36.7))


# ── (1) defensive contract ──────────────────────────────────────────────────


class TestDefensiveParsing:
    def test_non_station_html_returns_empty_with_clear_warning(self, caplog):
        """The actual ISS-048 case: an HTML page (not a station table). Must be
        [] plus a clear warning naming CDEC — not a bare decoder error."""
        adapter = _adapter_returning(_fixture("cdec_non_station_page.html"))

        with caplog.at_level(logging.WARNING, logger="datasync.adapters.cdec"):
            result = adapter.discover_stations(KAWEAH_BBOX)

        assert result == []
        msg = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "cdec" in msg
        assert "station" in msg
        # The bare JSONDecodeError text must NOT be the warning the operator sees.
        assert "expecting value" not in msg

    def test_empty_body_returns_empty_with_warning(self, caplog):
        adapter = _adapter_returning("")

        with caplog.at_level(logging.WARNING, logger="datasync.adapters.cdec"):
            result = adapter.discover_stations(KAWEAH_BBOX)

        assert result == []
        assert any("cdec" in r.getMessage().lower() for r in caplog.records)

    def test_json_wrong_shape_does_not_crash(self, caplog):
        """A valid JSON body of the wrong shape (e.g. {}) must not crash; it has
        no station rows, so it returns []."""
        adapter = _adapter_returning("{}", content_type="application/json")

        with caplog.at_level(logging.WARNING, logger="datasync.adapters.cdec"):
            result = adapter.discover_stations(KAWEAH_BBOX)

        assert result == []


# ── (2) valid station table parse + bbox filter ─────────────────────────────


class TestValidStationTable:
    def test_parses_and_filters_to_bbox(self):
        adapter = _adapter_returning(_fixture("cdec_station_table.html"))

        stations = adapter.discover_stations(KAWEAH_BBOX)

        ids = {s["station_id"] for s in stations}
        # KWT/TRM/LKW are inside the Kaweah bbox; SHA (Shasta) and BLY
        # (Riverside) are far away and must be filtered out.
        assert ids == {"KWT", "TRM", "LKW"}

    def test_station_dicts_have_standard_shape(self):
        adapter = _adapter_returning(_fixture("cdec_station_table.html"))

        stations = adapter.discover_stations(KAWEAH_BBOX)
        kwt = next(s for s in stations if s["station_id"] == "KWT")

        assert kwt["name"] == "KAWEAH R-TERMINUS DM"
        assert kwt["latitude"] == pytest.approx(36.414167)
        assert kwt["longitude"] == pytest.approx(-119.011667)
        # Parameters come from PARAMETER_MAP (the table carries no per-station
        # sensor list); shape must match the other adapters' contract.
        assert isinstance(kwt["parameters"], list)
        assert kwt["parameters"]
