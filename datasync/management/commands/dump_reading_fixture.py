# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Freeze the demonstration's telemetry readings into a committed fixture.

The third fixture, and it exists for the reason the first two do. The
demonstration already freezes its rivers (``data/merced/flowlines.json``) and its
monitoring stations (``data/merced/stations.json``). It did not freeze the
*readings those stations produce*, so a demonstration built from this repository
came up with every station chart blank — while the landing hero, reading a frozen
``last_data_at``, announced "37 of 42 stations reporting". **The site asserted
freshness it could not show.** That is what this command ends.

Found on production 2026-08-01, minutes after the v2.8 cutover, by opening
``/datasync/stations/4/`` (BLACK RASCAL DIVERSION) and seeing an empty chart.

**This is a DOWNSAMPLE, not a deduplication, and the distinction matters.**
``DataRecordStaging`` carries a ``UniqueConstraint`` on
``(station, parameter_code, observation_date)`` — duplicate rows cannot exist in
it. CDEC publishes genuinely sub-daily: measured on production, 197,812 raw rows
across 15 active stations represent 3,348 station-parameter-days, roughly a
reading every 25 minutes on the busiest sensors. Keeping one row per day
therefore **discards real measurements**. That is the right trade for a two-year
demonstration chart (200,000 points do not render meaningfully across two years,
and the committed file would be ~25 MB instead of ~1 MB), but it must never be
described as removing duplicates.

**Which reading survives the downsample: the LAST of each day.** Deterministic,
and it is the value a person reading "today's level" would expect. A daily mean
was considered and rejected: it invents a number no source ever published, on a
platform whose whole argument is that every figure names who published it.

**Determinism is a gate requirement, not tidiness.** ``expected_shape.json`` pins
every model at tolerance 0, so this fixture's row count must be reproducible
exactly or every future ``make deploy`` fails gate 2. Rows are ordered by
(source, station, parameter, date) before writing, and the day's survivor is
chosen by ``max(observation_date)`` — no ties possible, because the unique
constraint forbids them.

**Only ACTIVE stations.** The 293 inactive stations show no chart anywhere, so
freezing their history would pay file size for nothing.

**``raw_data`` is written as ``{}``.** The field is the adapter's untouched
upstream payload, useful when debugging a live sync and meaningless in a frozen
demonstration — and carrying it would multiply the file size several times over.
``load_reading_fixture`` writes ``{}`` back.

Usage:
    python manage.py dump_reading_fixture
    python manage.py dump_reading_fixture --start 2024-10-01
    python manage.py dump_reading_fixture --output /tmp/readings.json
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from datasync.models import DataRecordStaging

DEFAULT_OUTPUT = "data/merced/readings.json"

# Two water years. A California water year runs 1 Oct - 30 Sep, so this is
# WY2025 (2024-10-01) forward. Chosen by Brent 2026-08-01: one year shows a
# season, two years show that seasons repeat, which is the point of a chart on a
# water-accounting platform.
DEFAULT_START = "2024-10-01"


class Command(BaseCommand):
    help = (
        "Freeze active stations' published readings into data/merced/readings.json, "
        "downsampled to the last reading of each day."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=DEFAULT_OUTPUT,
            help=f"Where to write the fixture (default: {DEFAULT_OUTPUT})",
        )
        parser.add_argument(
            "--start",
            default=DEFAULT_START,
            help=f"Earliest observation date to include (default: {DEFAULT_START})",
        )

    def handle(self, *args, **options):
        out = Path(options["output"])
        start = timezone.make_aware(datetime.fromisoformat(options["start"]))

        qs = (
            DataRecordStaging.objects
            .filter(
                station__is_active=True,
                status="published",
                observation_date__gte=start,
            )
            .select_related("station", "station__data_source")
            .order_by("observation_date")
        )

        # Keep the LAST reading of each (station, parameter, calendar day).
        # Iterating in ascending observation_date order means the last write
        # wins, which IS the last reading of the day. No sort key ambiguity.
        survivors = {}
        raw_seen = 0
        for rec in qs.iterator(chunk_size=5000):
            raw_seen += 1
            day = timezone.localtime(rec.observation_date).date()
            survivors[(rec.station_id, rec.parameter_code, day)] = rec

        rows = []
        for rec in survivors.values():
            rows.append(
                {
                    "source": rec.station.data_source.code,
                    "external_station_id": rec.station.external_station_id,
                    "parameter_code": rec.parameter_code,
                    "observation_date": rec.observation_date.isoformat(),
                    "value": None if rec.value is None else str(rec.value),
                    "unit": rec.unit,
                }
            )

        # Deterministic order. Gate 2 pins this model at tolerance 0, so a
        # fixture whose contents shuffle between dumps would make every future
        # diff unreadable even though the count held.
        rows.sort(
            key=lambda r: (
                r["source"],
                r["external_station_id"],
                r["parameter_code"],
                r["observation_date"],
            )
        )

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=1) + "\n")

        per_source = defaultdict(int)
        for r in rows:
            per_source[r["source"]] += 1

        size_mb = out.stat().st_size / 1_048_576
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(rows)} readings to {out} ({size_mb:.2f} MB)"
            )
        )
        self.stdout.write(
            f"  downsampled from {raw_seen} raw rows "
            f"(ratio {raw_seen / max(len(rows), 1):.1f}:1 — real sub-daily "
            f"readings discarded, NOT duplicates)"
        )
        for code in sorted(per_source):
            self.stdout.write(f"  {code:<10} {per_source[code]:>7} readings")
        self.stdout.write(
            "\n  Pin this count in data/demo/expected_shape.json under "
            "datasync.DataRecordStaging,\n  or the next `make deploy` fails gate 2."
        )
