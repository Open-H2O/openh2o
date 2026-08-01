# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sync all active stations for a single data source.

**The default pull window is sized to the SOURCE's own publishing cadence, not
a flat week**, and that is a correctness fix rather than a tuning knob. Until
2026-08-01 every source got a 7-day window. `dwr_sgma` and `dwr_wdl` publish
roughly QUARTERLY — `freshness.EXPECTED_DATA_INTERVAL_HOURS` records their
expected interval as 120 days — so a 7-day pull returned **zero rows every
night, forever**, for 19 of the demonstration's 42 active stations. Measured on
staging 2026-08-01: `sync_source dwr_sgma` fetched 0 for its 17 stations and
`sync_source dwr_wdl` fetched 0 for its 2, while cdec/usgs/noaa fetched
13,173/47/9. Nobody noticed because the freshness classifier is ALSO
cadence-aware, so those stations kept a green dot from a reading fetched months
earlier — right up until something cleared `last_data_at` (the stations fixture
did exactly that, which is how this was found).

The window is `max(7 days, expected interval x WINDOW_INTERVAL_MULTIPLIER)`. The
7-day floor is deliberate: it means no source's window ever became NARROWER than
it was before this change, so a daily source that missed a few nights still
catches up exactly as it always did. `--start` overrides it entirely.

Usage:
    python manage.py sync_source cdec
    python manage.py sync_source cdec --start 2024-01-01 --end 2024-01-31
    python manage.py sync_source cdec --mock
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from datasync import freshness
from datasync.adapters import get_adapter
from datasync.models import DataSource, DataSyncLog, MonitoredStation

# Pull twice the source's expected publishing interval, so a single missed
# publication still lands inside the next window rather than falling through it.
WINDOW_INTERVAL_MULTIPLIER = 2

# Never pull a narrower window than the flat 7 days every source used before
# 2026-08-01. This makes the change strictly widening: nothing that worked
# before can fetch less now.
MINIMUM_WINDOW_DAYS = 7


def default_window_days(source_code):
    """How many days back to pull for a source that was given no --start.

    Sized from `freshness.expected_interval_hours`, which is the same table the
    UI uses to decide whether a station counts as reporting. Deriving both from
    one place is the point: a source the dashboard judges on a 120-day cadence
    must not be fetched on a 7-day one.
    """
    interval_days = freshness.expected_interval_hours(source_code) / 24
    return max(MINIMUM_WINDOW_DAYS, int(interval_days * WINDOW_INTERVAL_MULTIPLIER))


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
        start_date = end_date - timedelta(days=default_window_days(code))
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
