# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Freeze the demonstration's monitoring stations into a committed JSON fixture.

The sibling of ``dump_openet_fixture``, and it exists for the same reason. Until
this command, the only copy of the Merced demonstration's 335 monitoring
stations lived inside a running database. ``seed_merced`` step 2
(``auto_populate``) discovers them with a live CDEC/USGS/DWR fetch, and
``--skip-auto-populate`` — which every offline build uses — therefore produced a
demonstration with **no stations at all**. The landing page counts them
(``config/views.py``), so a repository-built demonstration read "0 of 0 stations
reporting" while production read "37 of 42" (re-derived 2026-08-01 by running
`config/views.py`'s own expression against production; the "21 of 42" figure
carried in 104-01 and 104-02 was never re-derived and is wrong).

103-01 argued the stations did not need freezing because nothing later in
``seed_merced``'s ``SEQUENCE`` reads ``MonitoredStation``. That test was
build-internal — it asked what the seed consumes, not what the demonstration
SHOWS. The stations are on screen, on the map and named on the about page; they
are part of the demonstration, so they are repository content.

**Keyed by the natural pair ``(data_source.code, external_station_id)`` — never
by primary key.** ``DataSource`` has no natural-key manager (only
``geography.Boundary`` defines one in this project), so a plain Django
``loaddata`` fixture would bake ``data_source_id`` integers that differ between
production and staging and silently attach stations to the wrong source.
``load_station_fixture`` resolves the codes back to rows. Adding a natural-key
manager to ``DataSource`` instead would change serialization behaviour for every
existing fixture and dump path in the project, to save writing this file.

**The output is a flat list and is deliberately unstamped.** No timestamp, no
hostname, no git hash, no derived header. That buys a real test: re-running this
dump against an unchanged database produces a byte-identical file, so
``git diff`` is an honest answer to "have the stations moved?" A generated-at
stamp would make every regeneration look like a change and the diff would stop
meaning anything.

**``last_data_at`` IS stored, and the first cut of this command got that wrong.**
The reversal is worth reading, because the mistake was a good principle applied
to the wrong thing.

The original argument was that a frozen timestamp "asserts data arrived at a
moment it did not, in a file whose whole purpose is honesty about provenance",
and that the hourly sync would refill it anyway. Both halves were measured wrong
on 2026-08-01:

* **It is not a fabrication.** DWR SGMA genuinely published on 2026-03-23. That
  is a true fact about a real published record — the same *kind* of fact as the
  station's name and its coordinates, which this fixture freezes without
  hesitation. The honesty principle was aimed at invented data; this is not
  invented.
* **The sync could not refill it.** ``sync_source`` used a flat 7-day window
  while ``dwr_sgma`` and ``dwr_wdl`` publish roughly quarterly, so both fetched
  **zero** rows for their 19 stations. Dropping ``last_data_at`` would have taken
  production's landing page from "37 of 42" to "20 of 42" **permanently**, with
  the nightly 03:15 restore re-applying it — the exact "a fix does not survive
  the reset" trap this milestone exists to end. (That window bug is now fixed
  too; see ``sync_source.default_window_days``. Both were needed: the wider
  window lets the data be re-fetched, the frozen timestamp means the
  demonstration is coherent the moment it is restored rather than a day later.)

Determinism survives, because a stored ``last_data_at`` only moves when somebody
re-dumps against a database whose readings have moved — which is precisely what
``git diff`` should show. It is serialised as an ISO-8601 UTC string, or
``null`` for a station that has never reported.

Full measurement:
``.planning/phases/104-deploy-cutover/104-02-station-freshness-findings-2026-08-01.md``

``created_at``/``updated_at`` are ``auto_now_add``/``auto_now`` and belong to
Django. No primary key appears anywhere.

These are real public USGS/CDEC/DWR/NOAA/CIMIS stations, and that is correct
rather than a leak: the demonstration's about page lists them under *"Real
published records — USGS and CDEC"*, and the identity policy treats station
names as **protected**, not banned.

Usage:
    python manage.py dump_station_fixture                    # -> data/merced/stations.json
    python manage.py dump_station_fixture --output /tmp/a.json
"""

import json
from datetime import timezone as dt_timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from datasync.models import MonitoredStation

DEFAULT_FIXTURE = "data/merced/stations.json"


def _stable_parameters(value):
    """Sort a parameter list when — and only when — sorting is meaningful.

    ``parameters`` is a free-form JSONField. It is a list of scalar codes on
    every row this project writes, and sorting those makes the dump independent
    of insertion order. Anything else (a dict, a nested structure, a mixed list)
    is passed through untouched rather than guessed at: a wrong sort would be a
    silent data change, and ``sort_keys=True`` already normalises dict ordering.
    """
    if isinstance(value, list) and all(
        isinstance(item, (str, int, float, bool)) for item in value
    ):
        return sorted(value, key=repr)
    return value


class Command(BaseCommand):
    help = (
        "Dump MonitoredStation rows to a deterministic JSON fixture keyed by "
        "(data source code, external station id) — no timestamps, no pks, so "
        "re-running against an unchanged database is byte-identical"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=DEFAULT_FIXTURE,
            help=f"Where to write the fixture (default: {DEFAULT_FIXTURE})",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])

        queryset = MonitoredStation.objects.select_related("data_source")

        rows = [
            {
                "source": station.data_source.code,
                "external_station_id": station.external_station_id,
                "station_name": station.station_name,
                "lon": station.location.x,
                "lat": station.location.y,
                "usgs_site_id": station.usgs_site_id,
                "wqx_monitoring_location_id": station.wqx_monitoring_location_id,
                "parameters": _stable_parameters(station.parameters),
                "is_active": station.is_active,
                # Normalised to UTC before serialising so the file does not
                # change shape with the dumping host's timezone.
                "last_data_at": (
                    station.last_data_at.astimezone(dt_timezone.utc).isoformat()
                    if station.last_data_at
                    else None
                ),
                "notes": station.notes,
            }
            for station in queryset
        ]
        rows.sort(key=lambda row: (row["source"], row["external_station_id"]))

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w") as handle:
            json.dump(rows, handle, sort_keys=True, indent=1)
            handle.write("\n")

        active = sum(1 for row in rows if row["is_active"])
        per_source = {}
        for row in rows:
            code = row["source"]
            total, source_active = per_source.get(code, (0, 0))
            per_source[code] = (total + 1, source_active + (1 if row["is_active"] else 0))

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(rows)} stations to {output} ({active} active)"
            )
        )
        for code in sorted(per_source):
            total, source_active = per_source[code]
            self.stdout.write(f"  {code}: {total} ({source_active} active)")
