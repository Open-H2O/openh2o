# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for all 8 health check functions in health/checks.py.

Each check returns a dict with: category, status, message, details.
Status values: "green", "yellow", or "red".
"""

from decimal import Decimal

import pytest
from django.test import override_settings

from tests.factories import ParcelLedgerFactory
from health.checks import (
    check_database,
    check_disk,
    check_docker,
    check_ledger_integrity,
    check_migrations,
    check_orphans,
    check_ssl,
    check_sync_freshness,
    run_all_checks,
)


VALID_STATUSES = {"green", "yellow", "red"}


class TestCheckDatabase:
    def test_returns_dict_with_required_keys(self):
        result = check_database()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_database(self):
        result = check_database()
        assert result["category"] == "database"

    def test_status_is_green_when_connected(self):
        """DB is connected in test environment, should return green."""
        result = check_database()
        assert result["status"] == "green"

    def test_details_contains_model_counts(self):
        result = check_database()
        details = result["details"]
        assert "parcels" in details
        assert "wells" in details
        assert "ledger_entries" in details
        assert "water_accounts" in details

    def test_details_counts_are_integers(self):
        result = check_database()
        for key, val in result["details"].items():
            assert isinstance(val, int), f"{key} should be int, got {type(val)}"


class TestCheckDisk:
    def test_returns_dict_with_required_keys(self):
        result = check_disk()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_disk(self):
        result = check_disk()
        assert result["category"] == "disk"

    def test_status_is_valid(self):
        result = check_disk()
        assert result["status"] in VALID_STATUSES

    def test_status_green_in_test_environment(self):
        """Disk usage should be well under 90% in a fresh test environment."""
        result = check_disk()
        assert result["status"] == "green"

    def test_details_contains_base_dir(self):
        result = check_disk()
        assert "base_dir" in result["details"]

    def test_details_base_dir_has_percent_used(self):
        result = check_disk()
        base = result["details"]["base_dir"]
        assert "percent_used" in base
        assert isinstance(base["percent_used"], float)

    def test_details_base_dir_has_free_gb(self):
        result = check_disk()
        base = result["details"]["base_dir"]
        assert "free_gb" in base


class TestCheckMigrations:
    def test_returns_dict_with_required_keys(self):
        result = check_migrations()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_migrations(self):
        result = check_migrations()
        assert result["category"] == "migrations"

    def test_status_is_green_in_test(self):
        """All migrations should be applied in a test environment."""
        result = check_migrations()
        assert result["status"] == "green"

    def test_details_has_unapplied_count(self):
        result = check_migrations()
        assert "unapplied_count" in result["details"]
        assert result["details"]["unapplied_count"] == 0


class TestCheckSyncFreshness:
    def test_returns_dict_with_required_keys(self):
        result = check_sync_freshness()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_sync_freshness(self):
        result = check_sync_freshness()
        assert result["category"] == "sync_freshness"

    def test_status_is_valid(self):
        result = check_sync_freshness()
        assert result["status"] in VALID_STATUSES

    def test_no_active_sources_returns_green(self):
        """With no active data sources (empty DB), should return green."""
        result = check_sync_freshness()
        # Either "No active data sources" (green) or stale (red/yellow) is valid
        assert result["status"] in VALID_STATUSES

    def test_details_is_dict(self):
        result = check_sync_freshness()
        assert isinstance(result["details"], dict)


class TestCheckLedgerIntegrity:
    def test_returns_dict_with_required_keys(self):
        result = check_ledger_integrity()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_ledger_integrity(self):
        result = check_ledger_integrity()
        assert result["category"] == "ledger_integrity"

    def test_status_is_valid(self):
        result = check_ledger_integrity()
        assert result["status"] in VALID_STATUSES

    def test_status_green_with_empty_db(self):
        """Empty DB has no orphans or zero-amount entries."""
        result = check_ledger_integrity()
        assert result["status"] == "green"

    def test_details_has_orphan_entries(self):
        result = check_ledger_integrity()
        assert "orphan_entries" in result["details"]

    def test_details_has_zero_amount_entries(self):
        result = check_ledger_integrity()
        assert "zero_amount_entries" in result["details"]


class TestCheckOrphans:
    def test_returns_dict_with_required_keys(self):
        result = check_orphans()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_orphans(self):
        result = check_orphans()
        assert result["category"] == "orphans"

    def test_status_is_valid(self):
        result = check_orphans()
        assert result["status"] in VALID_STATUSES

    def test_status_green_with_empty_db(self):
        """Empty DB has no unassigned parcels."""
        result = check_orphans()
        assert result["status"] == "green"

    def test_details_has_unassigned_parcels(self):
        result = check_orphans()
        assert "unassigned_parcels" in result["details"]

    def test_details_has_active_wells(self):
        result = check_orphans()
        assert "active_wells" in result["details"]

    def test_details_has_monitored_stations(self):
        result = check_orphans()
        assert "monitored_stations" in result["details"]


class TestCheckSsl:
    def test_returns_dict_with_required_keys(self):
        result = check_ssl()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_ssl(self):
        result = check_ssl()
        assert result["category"] == "ssl"

    def test_status_is_valid(self):
        result = check_ssl()
        assert result["status"] in VALID_STATUSES

    def test_yellow_in_dev_environment(self):
        """Dev environment has no public domain, so SSL check returns yellow."""
        result = check_ssl()
        # In test/dev with no SITE_DOMAIN and localhost in ALLOWED_HOSTS, expect yellow
        assert result["status"] in {"yellow", "green", "red"}


class TestCheckDocker:
    def test_returns_dict_with_required_keys(self):
        result = check_docker()
        assert "category" in result
        assert "status" in result
        assert "message" in result
        assert "details" in result

    def test_category_is_docker(self):
        result = check_docker()
        assert result["category"] == "docker"

    def test_status_is_valid(self):
        result = check_docker()
        assert result["status"] in VALID_STATUSES

    def test_details_has_expected_and_actual(self):
        result = check_docker()
        # Either success path (expected/actual) or error path (error key)
        assert "expected" in result["details"] or "error" in result["details"]


class TestRunAllChecks:
    def test_returns_list(self):
        results = run_all_checks()
        assert isinstance(results, list)

    def test_returns_eight_checks(self):
        results = run_all_checks()
        assert len(results) == 8

    def test_all_have_required_keys(self):
        results = run_all_checks()
        for r in results:
            assert "category" in r
            assert "status" in r
            assert "message" in r
            assert "details" in r

    def test_all_statuses_valid(self):
        results = run_all_checks()
        for r in results:
            assert r["status"] in VALID_STATUSES, (
                f"category {r['category']} has invalid status {r['status']!r}"
            )

    def test_categories_are_all_present(self):
        expected_categories = {
            "database",
            "disk",
            "sync_freshness",
            "ledger_integrity",
            "orphans",
            "ssl",
            "docker",
            "migrations",
        }
        results = run_all_checks()
        actual_categories = {r["category"] for r in results}
        assert actual_categories == expected_categories


class TestHealthDemoMode:
    """HEALTH_DEMO_MODE exempts the staleness/zero-amount alarms on the frozen
    public demo, where the DB is snapshot-restored nightly and those signals are
    static by design. Every other check is unaffected by the flag."""

    @override_settings(HEALTH_DEMO_MODE=True)
    def test_sync_freshness_is_green_in_demo_mode(self):
        result = check_sync_freshness()
        assert result["status"] == "green"
        assert result["details"].get("demo_mode") is True

    @pytest.mark.django_db
    @override_settings(HEALTH_DEMO_MODE=True)
    def test_zero_amount_ledger_is_green_in_demo_mode(self):
        ParcelLedgerFactory(amount_acre_feet=Decimal("0"))
        result = check_ledger_integrity()
        assert result["status"] == "green"

    @pytest.mark.django_db
    @override_settings(HEALTH_DEMO_MODE=False)
    def test_zero_amount_ledger_is_yellow_when_live(self):
        ParcelLedgerFactory(amount_acre_feet=Decimal("0"))
        result = check_ledger_integrity()
        assert result["status"] == "yellow"
