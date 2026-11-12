# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Freeze the demonstration's OpenET cache into a committed JSON fixture.

Until this command existed, the only copy of the Merced demo's satellite
evapotranspiration draws lived inside two running databases on the server. A
rebuild of the demonstration from the repository had two bad options: produce a
database with no ET at all (the accounting engine then computes nothing), or
spend OpenET quota on a fresh request for every rebuild. That gap is the reason
the golden snapshot has always had to be a photocopy of a live database rather
than a build output.

The fixture is keyed by ``parcel_number`` — never by primary key. Parcel pks
differ between deployments, and a pk-keyed fixture would silently attach ET to
the wrong parcels. ``load_openet_fixture`` resolves the numbers back to rows.

**Every row says where it came from and when it arrived.** ``source`` names the
service that sent the figures (OpenET for the ensemble's crop ET and its spread,
gridMET for rainfall), read from the row's model. ``received`` is the day the site
received them, read from the day each writer stamps on every item. A row whose
items carry no day, or two, is refused with nothing written: the dump never
supplies a day the site did not record, because a figure in this file is shown
on every page under its source's name. The per-item stamps are folded into the
row's one ``received`` day; ``load_openet_fixture`` puts them back.

**The output carries no time of its own.** No generated-at stamp, no hostname,
no git hash appears anywhere in the file. That buys a real test: re-running this
dump against an unchanged database produces a byte-identical file, so ``git
diff`` is an honest answer to "has the cache moved?" A generated-at stamp would
make every regeneration look like a change and the diff would stop meaning
anything. ``received`` is a property of the data, so it is the same on every run.

**``geometry`` is deliberately not stored.** It is ``parcel.geometry`` — the same
polygon, already committed in ``data/merced/selected_parcels.geojson`` and
already loaded by the seed. Storing it again would add roughly a megabyte of
duplicate coordinates whose only possible future is to disagree with the parcel
it claims to describe. The loader fills it from the parcel.

Usage:
    python manage.py dump_openet_fixture                     # -> data/merced/openet_cache.json
    python manage.py dump_openet_fixture --output /tmp/a.json
    python manage.py dump_openet_fixture --prefix MER-
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datasync.models import OpenETCache

DEFAULT_FIXTURE = "data/merced/openet_cache.json"
DEFAULT_PREFIX = "MER-"

#: The service that sent a row's figures, by the row's model.
SOURCE_OF_MODEL = {"Ensemble": "OpenET", "GRIDMET": "gridMET"}


def _row_label(row):
    return f"{row.parcel.parcel_number} {row.variable} {row.start_date} to {row.end_date}"


def provenance(row):
    """``(source, received day text, items without their day)`` or a refusal reason."""
    source = SOURCE_OF_MODEL.get(row.model_name)
    if source is None:
        return f"{_row_label(row)}: no known source for model {row.model_name!r}"
    items = row.et_data or []
    days = {item.get("fetched") for item in items if isinstance(item, dict)}
    if not items or days == {None}:
        return f"{_row_label(row)}: no received day on its items"
    if len(days) != 1 or None in days:
        return f"{_row_label(row)}: its items carry {len(days)} different received days"
    received = str(days.pop())[:10]
    stripped = [
        {key: value for key, value in item.items() if key != "fetched"}
        for item in items
    ]
    return source, received, stripped


class Command(BaseCommand):
    help = (
        "Dump the demo's OpenETCache rows to a deterministic JSON fixture "
        "keyed by parcel_number (no timestamps — re-running is byte-identical)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=DEFAULT_FIXTURE,
            help=f"Where to write the fixture (default: {DEFAULT_FIXTURE})",
        )
        parser.add_argument(
            "--prefix",
            default=DEFAULT_PREFIX,
            help=f"Only dump rows whose parcel_number starts with this (default: {DEFAULT_PREFIX})",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])
        prefix = options["prefix"]

        # PENDING rows are reservations against the monthly budget — an in-flight
        # fetch, not data. parcel=NULL rows are ad-hoc geometry queries that
        # belong to no parcel and so cannot be keyed by parcel_number at all.
        queryset = (
            OpenETCache.objects.filter(parcel__parcel_number__startswith=prefix)
            .exclude(model_name=OpenETCache.PENDING_MARKER)
            .exclude(parcel__isnull=True)
            .select_related("parcel")
        )

        rows, refused = [], []
        for row in queryset:
            found = provenance(row)
            if isinstance(found, str):
                refused.append(found)
                continue
            source, received, items = found
            rows.append(
                {
                    "parcel_number": row.parcel.parcel_number,
                    "start_date": row.start_date.isoformat(),
                    "end_date": row.end_date.isoformat(),
                    "variable": row.variable,
                    "model_name": row.model_name,
                    "source": source,
                    "received": received,
                    "et_data": items,
                }
            )
        if refused:
            refused.sort()
            raise CommandError(
                f"{len(refused)} row(s) cannot say where or when they were received, "
                f"so nothing was written to {output}:\n  "
                + "\n  ".join(refused[:5])
                + ("\n  ..." if len(refused) > 5 else "")
            )
        rows.sort(key=lambda r: (r["parcel_number"], r["variable"], r["start_date"]))

        meta = {
            "prefix": prefix,
            "variables": sorted({r["variable"] for r in rows}),
            "parcel_count": len({r["parcel_number"] for r in rows}),
            "windows": sorted({(r["start_date"], r["end_date"]) for r in rows}),
            "row_count": len(rows),
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w") as handle:
            json.dump(
                {"meta": meta, "rows": rows}, handle, sort_keys=True, indent=1
            )
            handle.write("\n")

        excluded_pending = OpenETCache.objects.filter(
            parcel__parcel_number__startswith=prefix,
            model_name=OpenETCache.PENDING_MARKER,
        ).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {meta['row_count']} rows to {output} "
                f"({meta['parcel_count']} parcels, "
                f"{len(meta['variables'])} variables, "
                f"{len(meta['windows'])} window(s))"
            )
        )
        self.stdout.write(f"  variables: {', '.join(meta['variables'])}")
        for start, end in meta["windows"]:
            self.stdout.write(f"  window: {start} to {end}")
        self.stdout.write(f"  excluded PENDING reservation rows: {excluded_pending}")
