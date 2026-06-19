# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Regression tests for data-adapter robustness (Phase 46, plan 03 — ISS-038/016).

These cover the data-integrity boundary for live state data:
- CKAN datastore_search_sql queries are apostrophe-safe AND injection-safe
  (the endpoint has no bound-parameter form, so values are strict-escaped).
- One non-numeric USGS NWIS reading drops only that record, not the batch.
- sync_all exits nonzero (CommandError) on aggregate failure so cron can alert.
- Production LOGGING routes django.request tracebacks to console at ERROR.
"""

import importlib
import logging
import subprocess
from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from datasync.adapters.base import sql_float, sql_str_literal
from datasync.adapters.cdec import CDECAdapter
from datasync.adapters.dwr_sgma import DWRSGMAAdapter
from datasync.adapters.dwr_wdl import DWRWDLAdapter
from datasync.adapters.usgs import USGSAdapter


# ── (a) CKAN SQL safety ─────────────────────────────────────────────────────


class TestSqlSafetyHelpers:
    def test_apostrophe_is_doubled(self):
        assert sql_str_literal("O'Brien") == "'O''Brien'"

    def test_plain_value_is_quoted(self):
        assert sql_str_literal("361737N1194798W001") == "'361737N1194798W001'"

    def test_injection_payload_stays_inside_literal(self):
        # The closing quote of the payload is doubled, so it can't break out.
        assert sql_str_literal("x'; DROP TABLE foo;--") == "'x''; DROP TABLE foo;--'"

    def test_sql_float_accepts_finite(self):
        assert sql_float("-119.45") == -119.45
        assert sql_float(36.5) == 36.5

    def test_sql_float_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            sql_float("119.45 OR 1=1")

    def test_sql_float_rejects_non_finite(self):
        with pytest.raises(ValueError):
            sql_float("inf")
        with pytest.raises(ValueError):
            sql_float("nan")


def _capture_sql(adapter):
    """Replace adapter._request with a stub that captures the built SQL."""
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["sql"] = kwargs["params"]["sql"]
        return SimpleNamespace(json=lambda: {"result": {"records": []}})

    adapter._request = fake_request
    return captured


@pytest.mark.parametrize("adapter_cls", [DWRWDLAdapter, DWRSGMAAdapter])
class TestCkanQueryEscaping:
    def test_apostrophe_in_site_code_is_escaped_not_broken(self, adapter_cls):
        """A real site_code with an apostrophe yields a correct (escaped) query,
        not a query that silently breaks/empties."""
        adapter = adapter_cls()
        captured = _capture_sql(adapter)
        station = SimpleNamespace(external_station_id="36N O'Brien")

        adapter.fetch(station, date(2024, 1, 1), date(2024, 12, 31))

        sql = captured["sql"]
        assert "'36N O''Brien'" in sql  # apostrophe doubled, wrapped as a literal

    def test_injection_attempt_is_neutralized(self, adapter_cls):
        adapter = adapter_cls()
        captured = _capture_sql(adapter)
        station = SimpleNamespace(external_station_id="x'; DROP TABLE foo;--")

        adapter.fetch(station, date(2024, 1, 1), date(2024, 1, 2))

        sql = captured["sql"]
        # Payload's quote doubled → trapped inside the string literal.
        assert "'x''; DROP TABLE foo;--'" in sql


# ── (b) USGS per-value guard ────────────────────────────────────────────────


class TestUsgsParseRobustness:
    @staticmethod
    def _payload(values):
        return {
            "value": {
                "timeSeries": [
                    {
                        "variable": {
                            "variableCode": [{"value": "00060"}],
                            "unit": {"unitCode": "cfs"},
                        },
                        "sourceInfo": {"siteCode": [{"value": "11446500"}]},
                        "values": [{"value": values}],
                    }
                ]
            }
        }

    def test_one_bad_reading_drops_only_itself(self):
        """An 'Ice' qualifier reading among good ones imports the good readings
        and drops only the bad — it must not sink the whole batch."""
        raw = self._payload(
            [
                {"value": "12.5", "dateTime": "2024-01-01T00:00:00", "qualifiers": ["A"]},
                {"value": "Ice", "dateTime": "2024-01-02T00:00:00", "qualifiers": ["P", "Ice"]},
                {"value": "14.0", "dateTime": "2024-01-03T00:00:00", "qualifiers": ["A"]},
            ]
        )
        records = USGSAdapter().parse(raw)

        assert len(records) == 2
        assert {r["value"] for r in records} == {12.5, 14.0}

    def test_empty_reading_kept_as_null(self):
        """A genuinely empty value stays as a null record (validate rejects it
        downstream) rather than being silently dropped at parse."""
        raw = self._payload(
            [{"value": "", "dateTime": "2024-01-01T00:00:00", "qualifiers": []}]
        )
        records = USGSAdapter().parse(raw)

        assert len(records) == 1
        assert records[0]["value"] is None


# ── (c) sync_all exit code ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestSyncAllExitCode:
    def test_raises_command_error_on_source_failure(self, monkeypatch):
        from datasync.models import DataSource

        DataSource.objects.create(code="usgs", name="USGS NWIS", is_active=True)

        def boom(name, *args, **kwargs):
            raise RuntimeError("forced sync failure")

        monkeypatch.setattr(
            "datasync.management.commands.sync_all.call_command", boom
        )

        with pytest.raises(CommandError) as exc:
            call_command("sync_all", stdout=StringIO())

        assert "usgs" in str(exc.value)

    def test_no_active_sources_does_not_raise(self):
        # No sources at all → warning + exit 0 (not a failure).
        call_command("sync_all", stdout=StringIO())


# ── (d) discovery is time-bounded per provider (ISS-051) ────────────────────


class TestDiscoveryIsTimeBounded:
    """A single provider's discover_stations must fail fast — a tight timeout
    and a single attempt — so it can never exceed the gunicorn worker budget and
    hang the setup wizard. The generous 60s data-fetch path stays untouched.
    """

    @staticmethod
    def _bbox():
        # CDEC discover_stations only needs the boundary's extent.
        return SimpleNamespace(extent=(-119.5, 36.0, -119.0, 36.5))

    # CDEC fetches through the system curl binary (its WAF drops urllib3's TLS
    # fingerprint), so these assert the timeout contract on the curl --max-time
    # argument rather than on a urllib3 timeout kwarg.
    def test_discovery_uses_short_timeout_not_sixty(self, monkeypatch):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("datasync.adapters.cdec.subprocess.run", fake_run)
        adapter = CDECAdapter()

        result = adapter.discover_stations(self._bbox())

        assert result == []
        # The discovery call passes the tight timeout, never the 60s budget.
        argv = captured["argv"]
        max_time = argv[argv.index("--max-time") + 1]
        assert max_time == str(int(adapter.discovery_timeout))
        assert int(max_time) <= 10

    def test_timeout_fails_fast_returns_empty_and_warns(self, monkeypatch, caplog):
        calls = {"n": 0}

        def boom(argv, **kwargs):
            calls["n"] += 1
            raise subprocess.TimeoutExpired(cmd="curl", timeout=10)

        monkeypatch.setattr("datasync.adapters.cdec.subprocess.run", boom)
        adapter = CDECAdapter()

        with caplog.at_level(logging.WARNING):
            result = adapter.discover_stations(self._bbox())

        assert result == []
        # Exactly one attempt — no retry-backoff amplifying a slow provider.
        assert calls["n"] == 1
        assert "timed out" in caplog.text.lower()

    def test_data_fetch_path_keeps_generous_timeout(self, monkeypatch):
        """fetch() (the data path) must still use the 60s timeout — only the
        discovery path is bounded."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")

        monkeypatch.setattr("datasync.adapters.cdec.subprocess.run", fake_run)
        station = SimpleNamespace(external_station_id="KWH", parameters=["15"])

        CDECAdapter().fetch(station, date(2024, 1, 1), date(2024, 1, 2))

        argv = captured["argv"]
        assert argv[argv.index("--max-time") + 1] == "60"


# ── Task 2: production request-error logging (ISS-016) ──────────────────────


class TestProductionLogging:
    def test_django_request_routes_to_console_at_error(self, monkeypatch):
        """Importing production settings (with prod secrets supplied so the
        fail-fast guards pass) exposes a LOGGING dict that routes django.request
        to a StreamHandler at ERROR — so an unhandled 500 prints a traceback to
        container stdout."""
        monkeypatch.setenv(
            "DATABASE_URL", "postgis://openh2o:Str0ng-Test-Pass-9f3@db:5432/openh2o"
        )
        monkeypatch.setenv("ALLOWED_HOSTS", "water.example.org")
        monkeypatch.setenv("SECRET_KEY", "test-only-secret-not-for-production-use")

        prod = importlib.import_module("config.settings.production")
        prod = importlib.reload(prod)

        logging_cfg = prod.LOGGING
        req = logging_cfg["loggers"]["django.request"]
        assert req["level"] == "ERROR"
        assert any(
            logging_cfg["handlers"][h]["class"] == "logging.StreamHandler"
            for h in req["handlers"]
        )
        # Catch-all root logger is also wired to console.
        assert logging_cfg["root"]["handlers"]
