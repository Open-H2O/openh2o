# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Smoke tests for key management commands.

Verifies commands run without raising exceptions. Uses call_command() which
runs commands in-process with the test database.

Excluded per plan:
- sync_all: requires network or mock setup beyond scope
- seed_demo_data: creates a massive dataset; too slow for smoke tests
"""

import pytest
from django.core.management import call_command
from io import StringIO


class TestSeedData:
    def test_seed_data_runs_without_error(self):
        """seed_data runs all 6 seed sub-commands without raising."""
        out = StringIO()
        call_command("seed_data", stdout=out)
        output = out.getvalue()
        assert "All seed data loaded" in output

    def test_seed_data_is_idempotent(self):
        """Running seed_data twice should not raise (idempotent)."""
        call_command("seed_data", stdout=StringIO())
        call_command("seed_data", stdout=StringIO())


class TestSeedRoles:
    def test_seed_roles_runs_without_error(self):
        out = StringIO()
        call_command("seed_roles", stdout=out)

    def test_seed_roles_creates_roles(self):
        from core.models import Role

        call_command("seed_roles", stdout=StringIO())
        assert Role.objects.exists()

    def test_seed_roles_idempotent(self):
        from core.models import Role

        call_command("seed_roles", stdout=StringIO())
        count_before = Role.objects.count()
        call_command("seed_roles", stdout=StringIO())
        count_after = Role.objects.count()
        assert count_before == count_after


class TestSeedWaterTypes:
    def test_seed_water_types_runs_without_error(self):
        out = StringIO()
        call_command("seed_water_types", stdout=out)

    def test_seed_water_types_creates_records(self):
        from accounting.models import WaterType

        call_command("seed_water_types", stdout=StringIO())
        assert WaterType.objects.exists()

    def test_seed_water_types_idempotent(self):
        from accounting.models import WaterType

        call_command("seed_water_types", stdout=StringIO())
        count = WaterType.objects.count()
        call_command("seed_water_types", stdout=StringIO())
        assert WaterType.objects.count() == count


class TestSeedDataSources:
    def test_seed_data_sources_runs_without_error(self):
        out = StringIO()
        call_command("seed_data_sources", stdout=out)

    def test_seed_data_sources_creates_records(self):
        from datasync.models import DataSource

        call_command("seed_data_sources", stdout=StringIO())
        assert DataSource.objects.exists()

    def test_seed_data_sources_idempotent(self):
        from datasync.models import DataSource

        call_command("seed_data_sources", stdout=StringIO())
        count = DataSource.objects.count()
        call_command("seed_data_sources", stdout=StringIO())
        assert DataSource.objects.count() == count


class TestRunHealthChecks:
    def test_run_health_checks_runs_without_error(self):
        out = StringIO()
        call_command("run_health_checks", stdout=out)

    def test_run_health_checks_saves_results(self):
        from health.models import HealthCheckResult

        count_before = HealthCheckResult.objects.count()
        call_command("run_health_checks", stdout=StringIO())
        count_after = HealthCheckResult.objects.count()
        assert count_after > count_before

    def test_run_health_checks_json_output(self):
        """--json flag returns parseable JSON."""
        import json

        out = StringIO()
        call_command("run_health_checks", json=True, stdout=out)
        output = out.getvalue()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 8

    def test_run_health_checks_category_filter(self):
        """--category flag filters to a single result."""
        out = StringIO()
        call_command("run_health_checks", category="database", json=True, stdout=out)
        import json

        data = json.loads(out.getvalue())
        assert len(data) == 1
        assert data[0]["category"] == "database"


class TestPruneOldData:
    def test_prune_dry_run_runs_without_error(self):
        """Default mode (no --confirm) is dry-run, should not raise."""
        out = StringIO()
        call_command("prune_old_data", stdout=out)
        output = out.getvalue()
        assert "DRY RUN" in output

    def test_prune_dry_run_deletes_nothing(self):
        """Dry run should not delete any records."""
        from datasync.models import DataSyncLog
        from health.models import HealthCheckResult

        # Create some health check results first
        call_command("run_health_checks", stdout=StringIO())
        count_before = HealthCheckResult.objects.count()

        call_command("prune_old_data", stdout=StringIO())

        # Records should still exist (default retention is 365 days)
        count_after = HealthCheckResult.objects.count()
        assert count_after == count_before

    def test_prune_with_confirm_runs_without_error(self):
        """--confirm flag performs actual deletion without raising."""
        out = StringIO()
        call_command("prune_old_data", confirm=True, stdout=out)
        # Should not contain "DRY RUN"
        assert "DRY RUN" not in out.getvalue()
