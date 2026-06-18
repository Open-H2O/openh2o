# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Trim each station's queried sensor list down to the sensors it ACTUALLY carries.

Some adapters cannot learn a station's installed sensors at discovery time. CDEC,
for example, publishes no per-station sensor list in its station-search table, so
discover_stations stamps every CDEC station with the full candidate sensor set
(reservoir storage, elevation, inflow, outflow, river stage, flow, precipitation).
A small creek gauge that only measures stage and flow then gets queried for all
seven on every sync — most come back empty, the burst makes CDEC start dropping
connections, and one sync balloons to ~11 minutes of mostly-wasted requests.

This command reads which sensors each station has ACTUALLY published readings for
and rewrites ``station.parameters`` to that observed set (preserving the declared
order). A gauge queried for 7 sensors but reporting only stage + flow drops to 2,
cutting the request count 4-8x and the sync time to about a minute.

Run it AFTER a sync, so the probe has real published data to learn from. It never
blanks a station: a station that has published nothing yet is left untouched and
reported, so a not-yet-synced station can't be trimmed to zero. It is reversible —
re-run discover_stations to restore the full candidate set, then re-trim. On the
public demo, re-stamp the golden snapshot afterwards so the trim survives the
nightly reset.

Usage:
    python manage.py trim_station_sensors cdec            # apply (CDEC only)
    python manage.py trim_station_sensors cdec --dry-run  # preview only
    python manage.py trim_station_sensors                 # every source
"""

from django.core.management.base import BaseCommand, CommandError

from datasync.models import DataRecordStaging, DataSource, MonitoredStation


class Command(BaseCommand):
    help = "Rewrite each station's queried sensor list to the sensors it actually publishes"

    def add_arguments(self, parser):
        parser.add_argument(
            "code", nargs="?", default=None,
            help="Data source code (e.g. cdec). Omit to trim every source.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without saving anything",
        )

    def handle(self, *args, **options):
        code = options["code"]
        dry_run = options["dry_run"]

        sources = DataSource.objects.all().order_by("code")
        if code:
            sources = sources.filter(code=code)
            if not sources.exists():
                raise CommandError(f"Data source '{code}' not found.")

        before_total = after_total = changed = skipped_empty = 0

        for src in sources:
            stations = MonitoredStation.objects.filter(
                data_source=src, is_active=True
            ).order_by("external_station_id")
            for s in stations:
                declared = list(s.parameters or [])
                observed = set(
                    DataRecordStaging.objects
                    .filter(station=s, status="published")
                    .values_list("parameter_code", flat=True)
                )
                before_total += len(declared)

                # Never blank a station: if it has published nothing yet, leave the
                # full candidate set so a later sync can still discover its sensors.
                if not observed:
                    skipped_empty += 1
                    after_total += len(declared)
                    self.stdout.write(
                        f"  {src.code} {s.external_station_id}: no published data yet — "
                        f"left as-is ({len(declared)} sensors)"
                    )
                    continue

                # Keep only sensors that actually reported, in the declared order.
                # Fall back to the observed set if declaration and data somehow
                # disjoint, so we never end up querying fewer sensors than are real.
                trimmed = [p for p in declared if p in observed] or sorted(observed)
                after_total += len(trimmed)

                if trimmed != declared:
                    changed += 1
                    verb = "would trim" if dry_run else "trimmed"
                    self.stdout.write(
                        f"  {src.code} {s.external_station_id}: {verb} "
                        f"{len(declared)} -> {len(trimmed)} sensors  "
                        f"{declared} -> {trimmed}"
                    )
                    if not dry_run:
                        s.parameters = trimmed
                        s.save(update_fields=["parameters", "updated_at"])

        action = "Would reduce" if dry_run else "Reduced"
        self.stdout.write(self.style.SUCCESS(
            f"{action} sensor-queries from {before_total} to {after_total} "
            f"across {changed} station(s); {skipped_empty} left as-is (no data yet)."
        ))
