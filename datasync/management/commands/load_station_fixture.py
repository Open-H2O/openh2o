# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Load the committed monitoring-station fixture back into a database.

The other half of ``dump_station_fixture``. Together they are what lets a
demonstration built from this repository carry the monitoring section it has
always shown, without ``rebuild-golden.sh`` making a live call to CDEC, USGS,
DWR, NOAA or CIMIS on every build.

**It resolves every data source BEFORE it writes a single row.** If the fixture
names a source code the database does not have, the command raises
``CommandError`` naming the codes and says the fix. This mirrors
``load_openet_fixture`` and ``seed_merced._require_frozen_flowlines``, and exists
for the reason recorded there: a half-written database whose error message never
mentions the cause sends the operator debugging the wrong thing.

**It never creates a ``DataSource``.** ``seed_data_sources`` owns that table.
Inventing a source here would make this fixture a second, competing source of
truth for which upstream services the platform knows about — and the rebuild
runs ``seed_data`` before this command precisely so the six codes already exist.
A missing code means the build sequence is wrong, which is worth stopping for.

``last_data_at`` is set to ``None`` explicitly, because the fixture deliberately
does not carry it (see ``dump_station_fixture``'s docstring). The hourly
``sync_source`` cron fills it — ``sync_source`` cannot *create* a station, but it
does write readings into existing ones, which is the whole design: **the fixture
restores the stations and the ordinary sync restores the readings.**

Idempotent by ``update_or_create`` on the ``(data_source, external_station_id)``
unique pair. The rebuild runs it exactly once, but ``seed_merced`` is idempotent
throughout and this matches.

Usage:
    python manage.py load_station_fixture
    python manage.py load_station_fixture --fixture /tmp/stations.json
"""

import json
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError

from datasync.models import DataSource, MonitoredStation

DEFAULT_FIXTURE = "data/merced/stations.json"


class Command(BaseCommand):
    help = (
        "Load data/merced/stations.json into MonitoredStation, resolving data "
        "sources by code. Refuses before writing anything if a code is unknown."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture",
            default=DEFAULT_FIXTURE,
            help=f"Fixture to load (default: {DEFAULT_FIXTURE})",
        )

    def handle(self, *args, **options):
        fixture = Path(options["fixture"])
        if not fixture.exists():
            raise CommandError(
                f"Fixture not found: {fixture}\n"
                "  Regenerate it from a database that holds the stations with:\n"
                "    python manage.py dump_station_fixture"
            )

        rows = json.loads(fixture.read_text())

        # --- Resolve everything first. Nothing below this block writes. ---
        wanted = {row["source"] for row in rows}
        sources = DataSource.objects.in_bulk(wanted, field_name="code")
        missing = sorted(wanted - set(sources))
        if missing:
            raise CommandError(
                f"{len(missing)} data source code(s) in {fixture} are not in "
                f"this database: {', '.join(missing)}\n"
                "  Nothing was written. This fixture never creates a DataSource "
                "-- seed_data_sources owns\n  that table. Seed the sources first:\n"
                "    python manage.py seed_data"
            )

        created_count = 0
        updated_count = 0

        for row in rows:
            _, created = MonitoredStation.objects.update_or_create(
                data_source=sources[row["source"]],
                external_station_id=row["external_station_id"],
                defaults={
                    "station_name": row["station_name"],
                    "location": Point(row["lon"], row["lat"], srid=4326),
                    "usgs_site_id": row["usgs_site_id"],
                    "wqx_monitoring_location_id": row["wqx_monitoring_location_id"],
                    "parameters": row["parameters"],
                    "is_active": row["is_active"],
                    "notes": row["notes"],
                    # Explicitly NULL: the fixture carries no reading times, and
                    # asserting one would claim data arrived when it did not.
                    "last_data_at": None,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        active = sum(1 for row in rows if row["is_active"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(rows)} stations from {fixture} "
                f"({created_count} created, {updated_count} updated, "
                f"{active} active)"
            )
        )
        # The active count is the number the landing page displays, so it is
        # reported on its own line rather than buried in the summary.
        self.stdout.write(f"  active stations: {active} of {len(rows)}")
