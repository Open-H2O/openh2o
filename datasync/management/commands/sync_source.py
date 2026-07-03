# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sync all active stations for a single data source.

Usage:
    python manage.py sync_source cdec
    python manage.py sync_source cdec --start 2024-01-01 --end 2024-01-31
    python manage.py sync_source cdec --mock
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from datasync.adapters import get_adapter
from datasync.models import DataSource, DataSyncLog, MonitoredStation


class Command(BaseCommand):
    help = "Sync all active stations for a single data source"

    def add_arguments(self, parser):
        parser.add_argument("code", type=str, help="Data source code (e.g. cdec, usgs)")
        parser.add_argument(
            "--start", type=str, default=None,
            help="Start date (YYYY-MM-DD). Defaults to 7 days ago.",
        )
        parser.add_argument(
            "--end", type=str, default=None,
            help="End date (YYYY-MM-DD). Defaults to today.",
        )
        parser.add_argument(
            "--mock", action="store_true",
            help="Force mock mode (use fixture data instead of live API)",
        )

    def handle(self, *args, **options):
        code = options["code"]

        try:
            data_source = DataSource.objects.get(code=code)
        except DataSource.DoesNotExist:
            raise CommandError(f"Data source '{code}' not found. Run seed_data_sources first.")

        adapter = get_adapter(code)
        if adapter is None:
            raise CommandError(f"No adapter registered for source code '{code}'.")

        # An inactive source is OFF, not a mock: skip it entirely rather than
        # syncing (previously an inactive source silently served canned fixtures
        # and stamped a fresh last_data_at, making a dead source look healthy).
        if not data_source.is_active and not options["mock"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{data_source.name} is inactive — skipping (no fetch, no "
                    "publish). Reactivate the source to sync it."
                )
            )
            return

        # Parse dates
        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        if options["start"]:
            start_date = date.fromisoformat(options["start"])
        if options["end"]:
            end_date = date.fromisoformat(options["end"])

        stations = MonitoredStation.objects.filter(
            data_source=data_source, is_active=True
        )

        if not stations.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"No active stations for {data_source.name}. "
                    "Run discover_stations first."
                )
            )
            return

        self.stdout.write(
            f"Syncing {stations.count()} station(s) for {data_source.name} "
            f"({start_date} to {end_date})"
        )

        # Reap orphaned "running" logs first. Syncs for a single source run
        # serially (one cron entry per source, no overlap), so any log still
        # marked "running" when a new run begins is a prior run that died
        # mid-flight — a SIGKILLed worker or a container restart between the
        # create and the finalize below. Left alone it latches "running" forever
        # and the monitoring panel shows a permanent "Syncing…". Close them out
        # as failed so the source reflects reality.
        reaped = DataSyncLog.objects.filter(
            data_source=data_source, status="running"
        ).update(
            status="failed",
            completed_at=timezone.now(),
            error_message="Orphaned: a prior run did not finish (process died mid-sync).",
        )
        if reaped:
            self.stdout.write(
                self.style.WARNING(
                    f"Reaped {reaped} orphaned 'running' log(s) for {code}."
                )
            )

        # Create a shared sync log for all stations in this run
        sync_log = DataSyncLog.objects.create(
            data_source=data_source, status="running"
        )

        failures = 0
        for station in stations:
            self.stdout.write(f"  {station.external_station_id}: {station.station_name}")
            result = adapter.sync(
                station, start_date, end_date, sync_log=sync_log, mock=options["mock"]
            )
            if result.error_message:
                failures += 1
                self.stdout.write(self.style.ERROR(f"    Error: {result.error_message}"))

        # Finalize the shared sync log
        sync_log.completed_at = timezone.now()
        sync_log.duration_seconds = (
            sync_log.completed_at - sync_log.started_at
        ).total_seconds()

        if failures == stations.count():
            sync_log.status = "failed"
        elif failures > 0:
            sync_log.status = "partial"
        elif sync_log.records_fetched > 0 and sync_log.records_staged == 0:
            # Every station returned data but none of it staged (an upstream
            # format change silently dropping records). Not a clean success.
            sync_log.status = "partial"
            if not sync_log.error_message:
                sync_log.error_message = (
                    f"{sync_log.records_fetched} records fetched but 0 staged "
                    "across all stations (all dropped in validate/stage)."
                )
        else:
            sync_log.status = "success"

        sync_log.save()

        # Update source timestamp
        data_source.last_sync_at = timezone.now()
        data_source.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {sync_log.records_fetched} fetched, "
                f"{sync_log.records_staged} staged, "
                f"{sync_log.records_published} published "
                f"({sync_log.duration_seconds:.1f}s)"
            )
        )
