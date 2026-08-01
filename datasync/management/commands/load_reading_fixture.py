# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Load the committed readings fixture back into a database.

The other half of ``dump_reading_fixture``. Together they are what lets a
demonstration built from this repository draw a station chart, without
``rebuild-golden.sh`` making a live call to CDEC, USGS, DWR or NOAA on every
build.

**It resolves every station BEFORE it writes a single row.** If the fixture
names a ``(source, external_station_id)`` pair the database does not have, the
command raises ``CommandError`` naming the pairs and says the fix. This mirrors
``load_station_fixture`` and ``load_openet_fixture``, and exists for the reason
recorded there: a half-written database whose error message never mentions the
cause sends the operator debugging the wrong thing.

**It never creates a station.** ``load_station_fixture`` owns that table, and the
rebuild runs it first — that ordering is what makes this command's resolve step a
real check rather than a formality. A missing pair means the build sequence is
wrong or the two fixtures were regenerated from different databases, both of
which are worth stopping for.

**Rows arrive as ``published``.** The chart endpoint
(``datasync/views.py``) filters ``status="published"``; a fixture loaded as
``staged`` would satisfy every gate, restore every row, and still leave the
charts blank. That is precisely the class of defect 104-02 caught by opening a
page after four green gates, so it is stated here rather than left to the reader.

**``raw_data`` is written as ``{}``** — see ``dump_reading_fixture``'s docstring.
The field is the adapter's untouched upstream payload; a frozen demonstration has
no upstream call to record.

Idempotent by ``update_or_create`` on the ``(station, parameter_code,
observation_date)`` unique triple, which is the model's own constraint.

Usage:
    python manage.py load_reading_fixture
    python manage.py load_reading_fixture --fixture /tmp/readings.json
"""

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datasync.models import DataRecordStaging, MonitoredStation

DEFAULT_FIXTURE = "data/merced/readings.json"


class Command(BaseCommand):
    help = (
        "Load data/merced/readings.json into DataRecordStaging as published "
        "rows, resolving stations by (source, external_station_id). Refuses "
        "before writing anything if a station is unknown."
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
                "  Regenerate it from a database that holds the readings with:\n"
                "    python manage.py dump_reading_fixture"
            )

        rows = json.loads(fixture.read_text())

        # --- Resolve everything first. Nothing below this block writes. ---
        stations = {
            (s.data_source.code, s.external_station_id): s
            for s in MonitoredStation.objects.select_related("data_source")
        }
        wanted = {(r["source"], r["external_station_id"]) for r in rows}
        missing = sorted(wanted - set(stations))
        if missing:
            shown = ", ".join(f"{src}:{sid}" for src, sid in missing[:8])
            more = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
            raise CommandError(
                f"{len(missing)} station(s) named in {fixture} are not in this "
                f"database: {shown}{more}\n"
                "  Nothing was written. This fixture never creates a station -- "
                "load_station_fixture owns\n  that table and the rebuild runs it "
                "first. Load the stations, then retry:\n"
                "    python manage.py load_station_fixture"
            )

        objs = []
        for r in rows:
            station = stations[(r["source"], r["external_station_id"])]
            objs.append(
                DataRecordStaging(
                    data_source=station.data_source,
                    station=station,
                    raw_data={},
                    observation_date=datetime.fromisoformat(r["observation_date"]),
                    parameter_code=r["parameter_code"],
                    value=None if r["value"] is None else Decimal(r["value"]),
                    unit=r["unit"],
                    # The chart endpoint filters on this. See the docstring.
                    status="published",
                    published_at=datetime.fromisoformat(r["observation_date"]),
                )
            )

        # ignore_conflicts rather than update_or_create per row: the model's
        # unique triple makes a re-run a genuine no-op, and 8k single-row
        # round-trips would dominate the rebuild's wall clock for no gain.
        DataRecordStaging.objects.bulk_create(
            objs, batch_size=2000, ignore_conflicts=True
        )

        written = DataRecordStaging.objects.filter(status="published").count()
        per_source = defaultdict(int)
        for r in rows:
            per_source[r["source"]] += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(rows)} readings from {fixture} "
                f"({written} published rows now in the database)"
            )
        )
        for code in sorted(per_source):
            self.stdout.write(f"  {code:<10} {per_source[code]:>7} readings")
