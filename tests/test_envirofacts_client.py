# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the EPA Envirofacts client (Phase 79, plan 01).

Every case here mirrors a behaviour verified against the live service on
2026-07-19 and recorded in ``79-RESEARCH.md``. The tests themselves are
HERMETIC: the only network-shaped thing they touch is the module-level
``_request`` seam, which every test replaces. There is no HTTP-mocking library
in this repo by choice — the idiom is ``_FakeResponse`` plus a monkeypatched
``_request``, exactly as ``tests/test_cdec_discovery.py`` does it.

The failure modes matter more than the happy path. Envirofacts signals "no such
system" with HTTP 200 and an empty array, and signals "bad table" with a JSON
*object* where success returns a JSON *array*. Both of those look like success
to naive code, so each one gets its own named test.
"""

import json
from pathlib import Path

import pytest
import requests

from drinking import envirofacts
from drinking.models import EnvirofactsCache

FIXTURES = Path(__file__).resolve().parent.parent / "drinking" / "fixtures"

PWSID = "CA1010001"  # Bakman Water Company, Fresno — the research specimen.


class _FakeResponse:
    """Minimal stand-in for requests.Response, as used across this suite."""

    def __init__(self, text, status_code=200, content_type="application/json"):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}

    def json(self):
        return json.loads(self.text)


def _fixture(name):
    return (FIXTURES / f"envirofacts_{name}.json").read_text()


def _respond_with(monkeypatch, body, status_code=200, counter=None):
    """Point the module's ``_request`` seam at a fixed body.

    ``body`` may be raw text or any JSON-serialisable object. ``counter`` is an
    optional single-element list the stub increments, so a test can assert on
    the exact number of HTTP calls performed.
    """
    text = body if isinstance(body, str) else json.dumps(body)

    def _fake_request(method, url, **kwargs):
        if counter is not None:
            counter[0] += 1
        return _FakeResponse(text, status_code=status_code)

    monkeypatch.setattr(envirofacts, "_request", _fake_request)


def _raise_on_request(monkeypatch, exc):
    def _fake_request(method, url, **kwargs):
        raise exc

    monkeypatch.setattr(envirofacts, "_request", _fake_request)


def _forbid_request(monkeypatch):
    """Make any HTTP call an outright test failure.

    This is how the cache-hit test proves ZERO HTTP happened: if the cache is
    not consulted, the second fetch explodes here rather than quietly
    succeeding against a stub.
    """

    def _fake_request(method, url, **kwargs):
        raise AssertionError("HTTP was performed when the cache should have served")

    monkeypatch.setattr(envirofacts, "_request", _fake_request)


# ── URL construction ────────────────────────────────────────────────────────


class TestBuildUrl:
    def test_build_url_water_system(self):
        assert (
            envirofacts.build_url("WATER_SYSTEM", "CA1010001")
            == "https://data.epa.gov/efservice/WATER_SYSTEM/PWSID/CA1010001/JSON"
        )

    def test_build_url_is_the_single_endpoint_seam(self):
        """A future dmapservice migration must be one edit, so every table goes
        through the same builder."""
        for table in ("WATER_SYSTEM_FACILITY", "GEOGRAPHIC_AREA"):
            url = envirofacts.build_url(table, PWSID)
            assert url.endswith(f"/{table}/PWSID/{PWSID}/JSON")
            assert "efservice" in url and "dmapservice" not in url


# ── Success paths ───────────────────────────────────────────────────────────


class TestFetchSuccess:
    def test_fetch_water_system_returns_one_dict_not_a_list(self, monkeypatch):
        _respond_with(monkeypatch, _fixture("water_system"))

        payload = envirofacts.fetch_water_system(PWSID)

        assert isinstance(payload, dict), "WATER_SYSTEM returns exactly one row per PWSID"
        assert len(payload) == 45
        assert payload["pws_name"] == "BAKMAN WATER COMPANY"

    def test_fetch_facilities_returns_36_rows_with_distinct_ids(self, monkeypatch):
        _respond_with(monkeypatch, _fixture("facilities"))

        rows = envirofacts.fetch_facilities(PWSID)

        assert isinstance(rows, list)
        assert len(rows) == 36
        assert all(isinstance(r, dict) for r in rows)
        assert len({r["facility_id"] for r in rows}) == 36

    def test_fetch_geographic_area_returns_a_single_dict(self, monkeypatch):
        _respond_with(monkeypatch, _fixture("geographic_area"))

        payload = envirofacts.fetch_geographic_area(PWSID)

        assert isinstance(payload, dict)
        assert payload["pwsid"] == PWSID

    def test_fetch_geographic_area_returns_none_when_absent(self, monkeypatch):
        """Geography is a hint, not a requirement — absence is not an error."""
        _respond_with(monkeypatch, [])

        assert envirofacts.fetch_geographic_area(PWSID) is None


# ── Not found: HTTP 200 with an empty body ──────────────────────────────────


class TestPwsidNotFound:
    def test_empty_list_on_http_200_raises_pwsid_not_found(self, monkeypatch):
        """The critical case. An unknown PWSID is 200 + [], never a 404.

        This must RAISE — returning None or {} would let the onboarding wizard
        create a water system with a blank name and zero facilities.
        """
        _respond_with(monkeypatch, [], status_code=200)

        with pytest.raises(envirofacts.PwsidNotFound) as excinfo:
            result = envirofacts.fetch_water_system("ZZ9999999")
            pytest.fail(f"expected PwsidNotFound, got {result!r}")

        assert "ZZ9999999" in str(excinfo.value)

    def test_facility_less_system_returns_empty_list_without_raising(self, monkeypatch):
        """A real system with no facilities is legitimate; a system that does
        not exist is not. These two must not share a code path."""
        _respond_with(monkeypatch, [])

        rows = envirofacts.fetch_facilities(PWSID)

        assert rows == []


# ── Error envelope: a dict where a list was expected ────────────────────────


class TestErrorEnvelope:
    def test_dict_payload_with_error_raises_with_verbatim_server_message(
        self, monkeypatch
    ):
        message = "NOT_A_TABLE/PWSID/CA1010001: The table is not available."
        _respond_with(monkeypatch, {"error": message}, status_code=404)

        with pytest.raises(envirofacts.EnvirofactsError) as excinfo:
            envirofacts.fetch_water_system(PWSID)

        assert type(excinfo.value) is envirofacts.EnvirofactsError
        assert message in str(excinfo.value)

    def test_non_list_non_dict_payload_names_the_received_type(self, monkeypatch):
        _respond_with(monkeypatch, json.dumps("a bare string"))

        with pytest.raises(envirofacts.EnvirofactsError) as excinfo:
            envirofacts.fetch_water_system(PWSID)

        assert "str" in str(excinfo.value)


# ── Transport failures ──────────────────────────────────────────────────────


class TestUnavailable:
    def test_timeout_raises_unavailable_and_is_not_pwsid_not_found(self, monkeypatch):
        """Conflating these would tell an operator their valid PWSID does not
        exist when in fact EPA was simply slow."""
        _raise_on_request(monkeypatch, requests.Timeout("timed out"))

        with pytest.raises(envirofacts.EnvirofactsUnavailable) as excinfo:
            envirofacts.fetch_water_system(PWSID)

        assert not isinstance(excinfo.value, envirofacts.PwsidNotFound)
        assert "respond" in str(excinfo.value).lower()

    def test_connection_error_raises_unavailable(self, monkeypatch):
        _raise_on_request(monkeypatch, requests.ConnectionError("no route to host"))

        with pytest.raises(envirofacts.EnvirofactsUnavailable):
            envirofacts.fetch_water_system(PWSID)


# ── Caching ─────────────────────────────────────────────────────────────────


class TestCaching:
    def test_first_call_performs_http_and_writes_a_cache_row(self, monkeypatch):
        calls = [0]
        _respond_with(monkeypatch, _fixture("water_system"), counter=calls)

        envirofacts.fetch_water_system(PWSID)

        assert calls[0] == 1
        row = EnvirofactsCache.objects.get(pwsid=PWSID, table_name="WATER_SYSTEM")
        assert row.payload[0]["pws_name"] == "BAKMAN WATER COMPANY"

    def test_second_call_within_ttl_performs_zero_http(self, monkeypatch):
        _respond_with(monkeypatch, _fixture("water_system"))
        first = envirofacts.fetch_water_system(PWSID)

        _forbid_request(monkeypatch)
        second = envirofacts.fetch_water_system(PWSID)

        assert second == first

    def test_stale_row_refetches_and_updates_in_place(self, monkeypatch):
        from datetime import timedelta

        from django.utils import timezone

        _respond_with(monkeypatch, _fixture("water_system"))
        envirofacts.fetch_water_system(PWSID)

        # .update() bypasses auto_now, which a .save() would reset.
        EnvirofactsCache.objects.filter(pwsid=PWSID).update(
            queried_at=timezone.now() - timedelta(days=365)
        )
        assert EnvirofactsCache.objects.get(pwsid=PWSID).is_stale()

        calls = [0]
        _respond_with(monkeypatch, _fixture("water_system"), counter=calls)
        envirofacts.fetch_water_system(PWSID)

        assert calls[0] == 1
        assert EnvirofactsCache.objects.count() == 1, "the row is updated, never duplicated"

    def test_refresh_true_bypasses_a_fresh_cache_row(self, monkeypatch):
        _respond_with(monkeypatch, _fixture("water_system"))
        envirofacts.fetch_water_system(PWSID)

        calls = [0]
        _respond_with(monkeypatch, _fixture("water_system"), counter=calls)
        envirofacts.fetch_water_system(PWSID, refresh=True)

        assert calls[0] == 1
        assert EnvirofactsCache.objects.count() == 1

    def test_cache_is_keyed_per_table_not_per_pwsid(self, monkeypatch):
        _respond_with(monkeypatch, _fixture("water_system"))
        envirofacts.fetch_water_system(PWSID)
        _respond_with(monkeypatch, _fixture("facilities"))
        envirofacts.fetch_facilities(PWSID)

        assert EnvirofactsCache.objects.filter(pwsid=PWSID).count() == 2
