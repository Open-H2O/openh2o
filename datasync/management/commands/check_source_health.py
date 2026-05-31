# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Health report for data sources.

Usage:
    python manage.py check_source_health          # All sources
    python manage.py check_source_health cdec      # Single source
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from datasync.models import DataSource, DataSyncLog, MonitoredStation


class Command(BaseCommand):
    help = "Health report for data sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "code", nargs="?", type=str, default=None,
            help="Data source code (optional, shows all if omitted)",
        )

    def handle(self, *args, **options):
        code = options.get("code")

        if code:
            sources = DataSource.objects.filter(code=code)
            if not sources.exists():
                self.stdout.write(self.style.ERROR(f"Source '{code}' not found."))
                return
        else:
            sources = DataSource.objects.all().order_by("code")

        if not sources.exists():
            self.stdout.write(
                self.style.WARNING("No data sources. Run seed_data_sources first.")
            )
            return

        now = timezone.now()

        # Header
        self.stdout.write("")
        header = (
            f"{'Source':<15} {'Active':<8} {'Stations':<10} "
            f"{'Last Sync':<22} {'Last Status':<12} "
            f"{'Recent Fails':<14} {'Records':<10}"
        )
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for source in sources:
            stations_total = MonitoredStation.objects.filter(
                data_source=source
            ).count()
            stations_active = MonitoredStation.objects.filter(
                data_source=source, is_active=True
            ).count()

            # Last sync log
            last_log = DataSyncLog.objects.filter(
                data_source=source
            ).order_by("-started_at").first()

            if last_log:
                last_sync = last_log.started_at.strftime("%Y-%m-%d %H:%M")
                last_status = last_log.status
            else:
                last_sync = "never"
                last_status = "-"

            # Recent failures (last 7 days)
            week_ago = now - timezone.timedelta(days=7)
            recent_fails = DataSyncLog.objects.filter(
                data_source=source,
                status="failed",
                started_at__gte=week_ago,
            ).count()

            # Total published records
            from datasync.models import DataRecordStaging
            total_records = DataRecordStaging.objects.filter(
                data_source=source,
                status="published",
            ).count()

            # Format station count
            station_str = f"{stations_active}/{stations_total}"

            # Color the status
            active_str = "yes" if source.is_active else "no"
            status_style = self.style.SUCCESS if last_status == "success" else (
                self.style.ERROR if last_status == "failed" else self.style.WARNING
            )

            row = (
                f"{source.code:<15} {active_str:<8} {station_str:<10} "
                f"{last_sync:<22} "
            )
            self.stdout.write(row, ending="")
            self.stdout.write(status_style(f"{last_status:<12}"), ending="")
            self.stdout.write(f" {recent_fails:<14} {total_records:<10}")

        self.stdout.write("")

        # Summary
        total_sources = sources.count()
        active_sources = sources.filter(is_active=True).count()
        total_stations = MonitoredStation.objects.filter(
            data_source__in=sources
        ).count()
        active_stations = MonitoredStation.objects.filter(
            data_source__in=sources, is_active=True
        ).count()

        self.stdout.write(
            f"Summary: {active_sources}/{total_sources} sources active, "
            f"{active_stations}/{total_stations} stations active"
        )
        self.stdout.write("")
