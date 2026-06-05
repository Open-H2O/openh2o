# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Deactivate active monitoring stations that carry too little data to be useful.

The monitoring map renders one marker per active station. A station with zero or
one published reading is noise: it shows as a dead/flat dot, draws no sparkline,
and its popup says nothing. This command deactivates (never deletes) any active
station below a published-record threshold so the map shows only stations with a
real, chartable record. It is reversible — flip is_active back on, or re-run a
sync and the station can be re-activated.

Run it AFTER syncing (so periodic groundwater wells have had a chance to pull
their multi-year history); otherwise a legitimately sparse-but-real well could be
pruned before its data lands.

Usage:
    python manage.py prune_dataless_stations              # deactivate <2-record stations
    python manage.py prune_dataless_stations --min-records 3
    python manage.py prune_dataless_stations --dry-run    # preview only
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from datasync.models import MonitoredStation


class Command(BaseCommand):
    help = "Deactivate active stations with fewer than --min-records published readings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-records", type=int, default=2,
            help="Minimum published readings to stay active (default: 2 — enough to draw a sparkline)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be deactivated without changing anything",
        )

    def handle(self, *args, **options):
        min_records = options["min_records"]
        dry_run = options["dry_run"]

        # Count only PUBLISHED staging rows per active station.
        stations = (
            MonitoredStation.objects.filter(is_active=True)
            .annotate(
                published_count=Count(
                    "datarecordstaging",
                    filter=Q(datarecordstaging__status="published"),
                )
            )
            .select_related("data_source")
        )

        to_prune = [s for s in stations if s.published_count < min_records]

        if not to_prune:
            self.stdout.write(
                self.style.SUCCESS(
                    f"No active stations below {min_records} published records. Nothing to prune."
                )
            )
            return

        for s in to_prune:
            verb = "would deactivate" if dry_run else "deactivated"
            self.stdout.write(
                f"  {verb}: {s.data_source.code} {s.external_station_id} "
                f"({s.station_name}) — {s.published_count} records"
            )

        if not dry_run:
            ids = [s.pk for s in to_prune]
            MonitoredStation.objects.filter(pk__in=ids).update(is_active=False)

        action = "Would deactivate" if dry_run else "Deactivated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {len(to_prune)} dataless station(s) "
                f"(< {min_records} published records). "
                f"{MonitoredStation.objects.filter(is_active=True).count()} active stations remain."
            )
        )
