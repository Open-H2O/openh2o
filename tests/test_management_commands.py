# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Smoke tests for key management commands.

Verifies commands run without raising exceptions. Uses call_command() which
runs commands in-process with the test database.

Excluded per plan:
- sync_all: requires network or mock setup beyond scope
- seed_demo_data: creates a massive dataset; too slow for smoke tests
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command


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
        from health.checks import run_all_checks

        assert len(data) == len(run_all_checks())

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


@pytest.mark.django_db
class TestImportLedgerCsvIdempotency:
    """ISS-029: re-running the manual ledger import must not double the books,
    and importing into a finalized (filed) period must be refused."""

    HEADER = "parcel_number,effective_date,amount_acre_feet,source_type\n"

    def _write_csv(self, tmp_path, parcel_number):
        csv_path = tmp_path / "ledger.csv"
        csv_path.write_text(
            self.HEADER
            + f"{parcel_number},2024-06-01,12.5,meter_reading\n"
            + f"{parcel_number},2024-07-01,8.0,meter_reading\n"
        )
        return str(csv_path)

    def test_reimport_same_csv_does_not_double(self, tmp_path):
        from parcels.models import ParcelLedger
        from tests.factories import ParcelFactory

        parcel = ParcelFactory()
        csv_path = self._write_csv(tmp_path, parcel.parcel_number)

        call_command("import_ledger_csv", csv_path, stdout=StringIO())
        first = ParcelLedger.objects.count()
        assert first == 2

        # The nervous-operator re-run: same file, second time.
        call_command("import_ledger_csv", csv_path, stdout=StringIO())
        second = ParcelLedger.objects.count()
        assert second == first  # ISS-029: stable on re-run, no silent doubling

    def test_corrected_amount_reimport_lands_as_new_row(self, tmp_path):
        # Dedup keys on amount too, so a re-import where the operator FIXED a
        # value is a real correction that lands (not silently swallowed).
        from parcels.models import ParcelLedger
        from tests.factories import ParcelFactory

        parcel = ParcelFactory()
        csv_path = self._write_csv(tmp_path, parcel.parcel_number)
        call_command("import_ledger_csv", csv_path, stdout=StringIO())

        corrected = tmp_path / "ledger_corrected.csv"
        corrected.write_text(
            self.HEADER
            + f"{parcel.parcel_number},2024-06-01,99.0,meter_reading\n"
        )
        call_command("import_ledger_csv", str(corrected), stdout=StringIO())

        # original 2 rows + the corrected (different amount) row = 3
        assert ParcelLedger.objects.count() == 3
        assert ParcelLedger.objects.filter(
            amount_acre_feet=Decimal("99.0000")
        ).exists()

    def test_finalized_period_refused_explicit(self, tmp_path):
        from accounting.models import ReportingPeriod
        from django.core.management.base import CommandError
        from tests.factories import ParcelFactory

        parcel = ParcelFactory()
        period = ReportingPeriod.objects.create(
            name="WY 2024 (filed)",
            start_date=date(2023, 10, 1),
            end_date=date(2024, 9, 30),
            is_finalized=True,
        )
        csv_path = self._write_csv(tmp_path, parcel.parcel_number)
        with pytest.raises(CommandError):
            call_command(
                "import_ledger_csv",
                csv_path,
                reporting_period=period.name,
                stdout=StringIO(),
            )

    def test_rows_dated_in_finalized_period_refused(self, tmp_path):
        # No explicit period; the rows are dated inside a finalized period and
        # must be refused so a re-import can't slip rows into a filed month.
        from parcels.models import ParcelLedger
        from accounting.models import ReportingPeriod
        from tests.factories import ParcelFactory

        parcel = ParcelFactory()
        ReportingPeriod.objects.create(
            name="WY 2024 (filed)",
            start_date=date(2023, 10, 1),
            end_date=date(2024, 9, 30),
            is_finalized=True,
        )
        csv_path = self._write_csv(tmp_path, parcel.parcel_number)
        call_command("import_ledger_csv", csv_path, stdout=StringIO())
        assert ParcelLedger.objects.count() == 0  # both rows refused, none written


GEOJSON_ONE_PARCEL = (
    '{"type":"FeatureCollection","features":[{"type":"Feature",'
    '"properties":{"APN":"NEW-IMPORT-001","OWNER":"New Owner"},'
    '"geometry":{"type":"Polygon","coordinates":'
    "[[[-119.50,36.50],[-119.49,36.50],[-119.49,36.51],"
    "[-119.50,36.51],[-119.50,36.50]]]}}]}"
)


@pytest.mark.django_db
class TestImportParcelsRunScoped:
    """ISS-030: a leftover `pending` staging row from an aborted earlier import
    must not be promoted by a later, unrelated import (cross-run bleed), and
    staging must not accumulate unbounded."""

    def test_leftover_pending_not_promoted(self, tmp_path):
        from parcels.models import Parcel, ParcelStaging
        from tests.factories import _box

        # An aborted earlier import left a `pending` staging row behind.
        ParcelStaging.objects.create(
            parcel_number="GHOST-LEFTOVER-001",
            raw_data={"APN": "GHOST-LEFTOVER-001", "OWNER": "Ghost"},
            geometry=_box(),
            status="pending",
        )

        geo = tmp_path / "parcels.geojson"
        geo.write_text(GEOJSON_ONE_PARCEL)
        call_command("import_parcels", str(geo), stdout=StringIO())

        # This run's parcel is materialized...
        assert Parcel.objects.filter(parcel_number="NEW-IMPORT-001").exists()
        # ...but the leftover from the prior aborted run is NOT promoted.
        assert not Parcel.objects.filter(
            parcel_number="GHOST-LEFTOVER-001"
        ).exists()
        # ...and this run cleared its own staging scratch (no unbounded growth).
        assert not ParcelStaging.objects.filter(
            parcel_number="NEW-IMPORT-001"
        ).exists()


@pytest.mark.django_db
class TestSyncOpenetIntraRunDedup:
    """ISS-030 (F-functional-26): two overlapping OpenETCache rows that both
    contribute the same parcel-month in one run must produce exactly ONE
    et_estimate ledger row, not two."""

    def test_overlapping_cache_rows_create_one_row(self):
        from datasync.models import OpenETCache
        from parcels.models import ParcelLedger
        from tests.factories import ParcelFactory, _box

        parcel = ParcelFactory()
        # Spans DIFFER but both cover 2024-06. Identical spans are now blocked by
        # openetcache_one_row_per_parcel_window, so overlapping-but-distinct
        # windows are the only duplicate coverage still reachable — a wide
        # backfill plus a single-month refresh, which is exactly how the GEE
        # re-fetch path used to produce them.
        OpenETCache.objects.create(
            parcel=parcel,
            geometry=_box(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            et_data=[{"date": "2024-06", "et": 100.0, "unit": "mm"}],
        )
        OpenETCache.objects.create(
            parcel=parcel,
            geometry=_box(),
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
            et_data=[{"date": "2024-06", "et": 100.0, "unit": "mm"}],
        )

        # Control parcel: identical geometry, ONE cache row, same 100 mm value.
        solo = ParcelFactory()
        OpenETCache.objects.create(
            parcel=solo,
            geometry=_box(),
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
            et_data=[{"date": "2024-06", "et": 100.0, "unit": "mm"}],
        )

        call_command(
            "sync_openet_to_ledger",
            start_date="2024-06-01",
            end_date="2024-06-30",
            stdout=StringIO(),
        )
        rows = ParcelLedger.objects.filter(
            parcel=parcel, source_type="et_estimate"
        )
        assert rows.count() == 1  # one row despite two overlapping cache rows

        # F-math-08: and that row must carry the ONE-row VALUE. Row count alone
        # never caught the doubling — the duplicate coverage was summed into a
        # single row of twice the magnitude. Compared against the control rather
        # than a hardcoded number so it stays true if the mm->AF math changes.
        solo_rows = ParcelLedger.objects.filter(
            parcel=solo, source_type="et_estimate"
        )
        assert solo_rows.count() == 1
        assert rows.first().amount_acre_feet == solo_rows.first().amount_acre_feet
