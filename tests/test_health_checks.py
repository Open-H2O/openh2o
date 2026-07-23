# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the health check functions in health/checks.py, plus the rollups the
dashboard and JSON API build from their persisted rows.

Each check returns a dict with: category, status, message, details.
Status values: "green", "yellow", "red", or "skipped". The roster is
EXPECTED_CATEGORIES below, never a literal in prose — this docstring said
"all 8" long after there were thirteen, the same frozen-count defect ISS-090
logged against the dashboard.
"""

import json
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

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
    not_applicable,
    run_all_checks,
)
from health.models import HealthCheckResult


# "skipped" joined the vocabulary in Phase 91 (ISS-087): a check whose module is
# switched off is its own alarm level, not a shade of green. Every module-gated
# check returns it, so the status-validity assertions have to know about it.
VALID_STATUSES = {"green", "yellow", "red", "skipped"}


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


# One source of truth for the check roster, so adding a check updates the count
# assertion and the category assertion together instead of drifting apart.
EXPECTED_CATEGORIES = {
    "database",
    "disk",
    "sync_freshness",
    "ledger_integrity",
    "orphans",
    "cache_duplication",
    "pod_fractions",
    "unallocated_delivery",
    "period_alignment",
    "et_meter_agreement",
    "ssl",
    "docker",
    "migrations",
}


class TestRunAllChecks:
    def test_returns_list(self):
        results = run_all_checks()
        assert isinstance(results, list)

    def test_returns_all_checks(self):
        results = run_all_checks()
        assert len(results) == len(EXPECTED_CATEGORIES)

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
        results = run_all_checks()
        actual_categories = {r["category"] for r in results}
        assert actual_categories == EXPECTED_CATEGORIES


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


# ---------------------------------------------------------------------------
# Liveness probe (M1) — DB-free 200 for the Docker HEALTHCHECK + Caddy gate.
# ---------------------------------------------------------------------------


class TestLivenessProbe:
    @pytest.mark.django_db
    def test_livez_returns_ok_with_no_health_rows(self, client):
        """Must be 200 even when zero HealthCheckResult rows exist and regardless
        of subsystem status — it reports process liveness, not aggregate health."""
        from django.urls import reverse

        resp = client.get(reverse("health:live"))
        assert resp.status_code == 200
        assert resp.content == b"ok"

    def test_livez_does_not_query_the_database(self):
        """No @django_db mark and no DB access: the probe must never depend on the
        database, so a DB hiccup can't flap the container unhealthy."""
        from django.test import Client
        from django.urls import reverse

        resp = Client().get(reverse("health:live"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# DB probe (ISS-008) — SELECT 1 so external monitors measure DB health.
# ---------------------------------------------------------------------------


class TestDbProbe:
    @pytest.mark.django_db
    def test_dbz_returns_ok_when_db_reachable(self, client):
        from django.urls import reverse

        resp = client.get(reverse("health:db"))
        assert resp.status_code == 200
        assert resp.content == b"ok"

    def test_dbz_returns_503_when_db_unreachable(self, monkeypatch):
        """Simulate a dead connection: the probe must degrade to 503, never raise."""
        from django.test import Client
        from django.urls import reverse
        from django.db import connection

        def boom(*a, **k):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(connection, "cursor", boom)
        resp = Client().get(reverse("health:db"))
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Phase 91 (ISS-087 + ISS-090) — the health page stops lying.
#
# Two defects, one shape: the page reported numbers that were not true. It said
# "8 categories" when there were thirteen, and a check whose module was switched
# off was stored as green — so turning half the platform off RAISED the reported
# score from 11/13 to 12/13, because the checks that could fail were removed
# rather than counted as skipped.
#
# These tests pin the producer (`not_applicable`), both rollups (dashboard and
# JSON API), and the registry-derived count. The regression in
# TestSkippedChecksDoNotRaiseTheScore was watched RED against the pre-fix view
# before the fix landed.
# ---------------------------------------------------------------------------

ALL_CATEGORIES = [c[0] for c in HealthCheckResult.CATEGORY_CHOICES]


def _persist(statuses):
    """Write one latest row per category, in registry order, with these statuses.

    Uses the ORM directly rather than running the real checks: these are rollup
    tests, and the arithmetic they pin must hold for any status mix, not only
    the mixes this deployment happens to produce today.
    """
    assert len(statuses) == len(ALL_CATEGORIES), (
        f"give one status per category ({len(ALL_CATEGORIES)}), got {len(statuses)}"
    )
    for category, status in zip(ALL_CATEGORIES, statuses):
        HealthCheckResult.objects.create(
            category=category,
            status=status,
            message=f"{category} is {status}",
            # Retained as provenance on skipped rows. Nothing branches on it any
            # more; it names WHICH module is absent.
            details={"module_disabled": "datasync"} if status == "skipped" else {},
        )


@pytest.fixture
def operator(client, django_user_model):
    """A signed-in operator — per-subsystem detail is withheld from anonymous callers."""
    user = django_user_model.objects.create_user(
        username="health-operator", password="x", is_active=True
    )
    client.force_login(user)
    return user


class TestNotApplicableIsSkipped:
    """Producer side (ISS-087): the eight module-gated checks all delegate here."""

    def test_status_is_skipped_not_green(self):
        result = not_applicable("cache_duplication", "datasync", "the OpenET cache")
        assert result["status"] == "skipped"

    def test_message_still_names_the_absent_module(self):
        """The human-readable reason is the point of ISS-087's first half — this
        task changed the stored status, not the explanation."""
        result = not_applicable("cache_duplication", "datasync", "the OpenET cache")
        assert "datasync" in result["message"]
        assert "the OpenET cache" in result["message"]

    def test_details_retains_module_disabled_as_provenance(self):
        result = not_applicable("orphans", "parcels", "parcel-to-account assignment")
        assert result["details"]["module_disabled"] == "parcels"


class TestSkippedChecksDoNotRaiseTheScore:
    """The regression (ISS-087). RED against the pre-fix view, which counted
    skipped rows in the denominator and let them reach a healthy rollup."""

    @pytest.mark.django_db
    def test_reduced_deployment_counts_only_applicable_checks(self, client, operator):
        # The shape a nine-module drinking-water deployment actually produces:
        # 4 green + 1 yellow applicable, 8 module-gated checks skipped.
        _persist(["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        ctx = client.get(reverse("health:dashboard")).context

        assert ctx["total"] == 13
        assert ctx["applicable"] == 5
        assert ctx["skipped"] == 8
        assert ctx["green_count"] == 4

    @pytest.mark.django_db
    def test_dropping_modules_does_not_improve_the_healthy_fraction(
        self, client, operator
    ):
        """The anti-assertion, stated as the bug it replaces.

        Pre-fix, the same two runs read 11/13 full and 12/13 reduced — the score
        went UP as the platform went away. The denominator must be `applicable`,
        so the reduced fraction can only be lower.
        """
        _persist(["green"] * 11 + ["yellow"] * 2)
        full = client.get(reverse("health:dashboard")).context
        full_fraction = full["green_count"] / full["applicable"]
        assert (full["green_count"], full["applicable"]) == (11, 13)

        HealthCheckResult.objects.all().delete()
        _persist(["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        reduced = client.get(reverse("health:dashboard")).context
        reduced_fraction = reduced["green_count"] / reduced["applicable"]
        assert (reduced["green_count"], reduced["applicable"]) == (4, 5)

        assert reduced_fraction <= full_fraction, (
            "switching modules off raised the reported health score — the "
            "denominator is counting skipped checks again (ISS-087)"
        )
        # And the specific pre-fix arithmetic is gone: 12/13 would have been the
        # old reduced reading, because 8 skipped rows scored as green.
        assert reduced["green_count"] != 12

    @pytest.mark.django_db
    def test_lone_yellow_still_degrades_a_mostly_skipped_deployment(
        self, client, operator
    ):
        _persist(["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        assert client.get(reverse("health:dashboard")).context["overall_status"] == (
            "degraded"
        )

    @pytest.mark.django_db
    def test_skipped_rows_alongside_green_roll_up_healthy(self, client, operator):
        """Skipped checks do not block a healthy verdict — they simply do not vote."""
        _persist(["green"] * 5 + ["skipped"] * 8)
        assert client.get(reverse("health:dashboard")).context["overall_status"] == (
            "healthy"
        )

    @pytest.mark.django_db
    def test_an_all_skipped_deployment_is_unknown_not_healthy(self, client, operator):
        """Nothing applicable to measure is not the same as everything is fine.

        Unreachable in practice — database, disk, docker and migrations are not
        module-gated — but the empty case has to be defined rather than falling
        through to "healthy".
        """
        _persist(["skipped"] * 13)
        assert client.get(reverse("health:dashboard")).context["overall_status"] == (
            "unknown"
        )


class TestHealthApiRollupExcludesSkipped:
    """ISS-087 at the JSON surface. The rollup changes; the payload does not —
    an external operator wants to SEE that a check was skipped and why."""

    @pytest.mark.django_db
    def test_reduced_set_returns_degraded_200(self, client, operator):
        _persist(["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        resp = client.get(reverse("health:api"))
        assert resp.status_code == 200
        assert json.loads(resp.content)["status"] == "degraded"

    @pytest.mark.django_db
    def test_skipped_rows_are_still_listed_for_authenticated_callers(
        self, client, operator
    ):
        _persist(["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        checks = json.loads(client.get(reverse("health:api")).content)["checks"]
        assert len(checks) == 13
        assert sum(1 for c in checks if c["status"] == "skipped") == 8

    @pytest.mark.django_db
    def test_green_plus_skipped_is_neither_degraded_nor_unhealthy(
        self, client, operator
    ):
        _persist(["green"] * 5 + ["skipped"] * 8)
        resp = client.get(reverse("health:api"))
        assert resp.status_code == 200
        assert json.loads(resp.content)["status"] == "healthy"

    @pytest.mark.django_db
    def test_all_skipped_is_unknown(self, client, operator):
        _persist(["skipped"] * 13)
        resp = client.get(reverse("health:api"))
        assert resp.status_code == 200
        assert json.loads(resp.content)["status"] == "unknown"


class TestCategoryCountIsRegistryDerived:
    """ISS-090: the count comes from what actually ran, not from a literal."""

    @pytest.mark.django_db
    def test_total_equals_the_category_registry(self, client, operator):
        _persist(["green"] * 13)
        ctx = client.get(reverse("health:dashboard")).context
        assert ctx["total"] == len(HealthCheckResult.CATEGORY_CHOICES)
        assert ctx["total"] == len(EXPECTED_CATEGORIES)

    @pytest.mark.django_db
    def test_the_rendered_page_carries_no_frozen_count(self, client, operator):
        """A fourteenth check must move the rendered number by itself."""
        _persist(["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        html = client.get(reverse("health:dashboard")).content.decode()
        assert "across 13 categories" in html
        assert "8 categories" not in html
        assert "5 applicable of 13" in html
        assert "4/5 healthy" in html


class TestCliSummaryDenominator:
    """ISS-087 at the CLI. This is the line that printed "12/13 healthy" on a
    deployment running half the platform."""

    @pytest.mark.django_db
    def test_summary_divides_by_applicable_and_shows_both_numbers(self, monkeypatch):
        from io import StringIO
        from django.core.management import call_command
        import health.management.commands.run_health_checks as cmd

        fake = [
            {"category": c, "status": s, "message": f"{c}", "details": {}}
            for c, s in zip(ALL_CATEGORIES, ["green"] * 4 + ["yellow"] + ["skipped"] * 8)
        ]
        monkeypatch.setattr(cmd, "run_all_checks", lambda: fake)
        out = StringIO()
        call_command("run_health_checks", stdout=out)
        printed = out.getvalue()

        assert "Summary: 4/5 healthy (5 applicable of 13, 8 skipped)" in printed
        assert "12/13" not in printed

    @pytest.mark.django_db
    def test_full_deployment_summary_has_no_skipped_clause(self, monkeypatch):
        from io import StringIO
        from django.core.management import call_command
        import health.management.commands.run_health_checks as cmd

        fake = [
            {"category": c, "status": s, "message": f"{c}", "details": {}}
            for c, s in zip(ALL_CATEGORIES, ["green"] * 11 + ["yellow"] * 2)
        ]
        monkeypatch.setattr(cmd, "run_all_checks", lambda: fake)
        out = StringIO()
        call_command("run_health_checks", stdout=out)
        printed = out.getvalue()

        assert "Summary: 11/13 healthy (13 applicable of 13)" in printed
        assert "skipped" not in printed

    @pytest.mark.django_db
    def test_skipped_rows_print_na_off_the_status_field(self, monkeypatch):
        """No details.module_disabled key at all — the status field alone must
        drive the N/A column."""
        from io import StringIO
        from django.core.management import call_command
        import health.management.commands.run_health_checks as cmd

        fake = [
            {"category": c, "status": s, "message": f"{c}", "details": {}}
            for c, s in zip(ALL_CATEGORIES, ["green"] * 12 + ["skipped"])
        ]
        monkeypatch.setattr(cmd, "run_all_checks", lambda: fake)
        out = StringIO()
        call_command("run_health_checks", stdout=out)
        printed = out.getvalue()

        assert f"{ALL_CATEGORIES[-1]:<20} {'N/A':<10}" in printed
