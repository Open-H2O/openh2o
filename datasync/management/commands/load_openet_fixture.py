# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Load the committed OpenET cache fixture back into an empty database.

The other half of ``dump_openet_fixture``. Together they are what lets the
demonstration be rebuilt from the repository without spending OpenET quota on
every rebuild. The figures are the ones OpenET and gridMET sent, each row with
the day the site received them.

**Each row must say where it came from and when it arrived** (``source`` and
``received``, written by the dump). A row without them, with a source that does
not belong to its model, or received before its last month ended, is refused
with nothing written, the same as a missing parcel. Each item is stamped with
the row's received day as a fetch stamps it, so a recorded crop ET month carries
that day.

**It resolves every parcel BEFORE it writes a single row.** If the fixture names
a parcel the database does not have, the command raises ``CommandError`` naming
how many are missing and the first five, and says the fix. This mirrors
``seed_merced._require_frozen_flowlines`` and exists for the reason recorded
there: a half-written database whose error message never mentions the cause
sends the operator debugging the wrong thing.

Resolution is a direct lookup rather than a natural-key manager on ``Parcel``.
``Boundary`` needed a manager because ``loaddata`` had to resolve a foreign key
with no code of its own to run — this loader IS that code, so the model change
and its migration-adjacent risk buy nothing.

Usage:
    python manage.py load_openet_fixture
    python manage.py load_openet_fixture --fixture /tmp/openet_cache.json
"""

import datetime as dt
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from datasync import crop_et
from datasync.management.commands.dump_openet_fixture import SOURCE_OF_MODEL
from datasync.models import OpenETCache
from parcels.models import Parcel

DEFAULT_FIXTURE = "data/merced/openet_cache.json"
DEFAULT_PREFIX = "MER-"


def _provenance_problem(row):
    """Why ``row`` cannot be loaded as a figure its source sent, or None."""
    label = f"{row.get('parcel_number')} {row.get('variable')} from {row.get('start_date')}"
    source, received = row.get("source"), row.get("received")
    if not source or not received:
        return f"{label}: no source or received day"
    if SOURCE_OF_MODEL.get(row.get("model_name")) != source:
        return f"{label}: source {source!r} does not belong to model {row.get('model_name')!r}"
    try:
        day = dt.date.fromisoformat(received)
    except ValueError:
        return f"{label}: received {received!r} is not a day"
    months = [crop_et.month_first(str(item.get("date", ""))[:7]) for item in row.get("et_data") or []]
    if months and day <= crop_et.last_day(max(months)):
        return f"{label}: received {received} before its last month ended"
    return None


class Command(BaseCommand):
    help = (
        "Load data/merced/openet_cache.json into OpenETCache, resolving parcels "
        "by parcel_number. Refuses before writing anything if any parcel is missing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture",
            default=DEFAULT_FIXTURE,
            help=f"Fixture to load (default: {DEFAULT_FIXTURE})",
        )
        parser.add_argument(
            "--prefix",
            default=DEFAULT_PREFIX,
            help=f"For symmetry with dump_openet_fixture (default: {DEFAULT_PREFIX})",
        )

    def handle(self, *args, **options):
        fixture = Path(options["fixture"])
        if not fixture.exists():
            raise CommandError(
                f"Fixture not found: {fixture}\n"
                "  Regenerate it from a database that holds the cache with:\n"
                "    python manage.py dump_openet_fixture"
            )

        payload = json.loads(fixture.read_text())
        rows = payload["rows"]

        # --- Every row's provenance first. Nothing below this block writes. ---
        unproven = [problem for problem in map(_provenance_problem, rows) if problem]
        if unproven:
            raise CommandError(
                f"{len(unproven)} row(s) in {fixture} do not say where or when "
                f"they were received: " + "; ".join(unproven[:5])
                + (" …" if len(unproven) > 5 else "")
                + "\n  Nothing was written. Regenerate the file with:\n"
                "    python manage.py dump_openet_fixture"
            )

        # --- Resolve everything first. Nothing below this block writes. ---
        wanted = {row["parcel_number"] for row in rows}
        parcels = Parcel.objects.in_bulk(wanted, field_name="parcel_number")
        missing = sorted(wanted - set(parcels))
        if missing:
            sample = ", ".join(missing[:5])
            raise CommandError(
                f"{len(missing)} parcel_number(s) in {fixture} are not in this "
                f"database: {sample}"
                + (" …" if len(missing) > 5 else "")
                + "\n  Nothing was written. Seed the parcels first:\n"
                "    python manage.py seed_merced --skip-auto-populate"
            )

        # OpenETCache.geometry is NOT NULL while Parcel.geometry is nullable, so
        # a geometry-less parcel would raise IntegrityError partway through the
        # loop and leave exactly the half-written database the check above
        # exists to prevent. sync_openet_parcels only ever queries parcels with
        # geometry, so a row here without one is a broken seed, not a case to
        # tolerate.
        geometryless = sorted(
            number for number, parcel in parcels.items() if parcel.geometry is None
        )
        if geometryless:
            sample = ", ".join(geometryless[:5])
            raise CommandError(
                f"{len(geometryless)} parcel(s) named in {fixture} carry no "
                f"geometry: {sample}"
                + (" …" if len(geometryless) > 5 else "")
                + "\n  Nothing was written. Every cached ET draw is keyed to a "
                "parcel polygon;\n  re-run the parcel seed before loading:\n"
                "    python manage.py seed_merced --skip-auto-populate"
            )

        created_count = 0
        updated_count = 0
        per_variable = {}

        for row in rows:
            parcel = parcels[row["parcel_number"]]
            # The tuple is the openetcache_one_row_per_parcel_window constraint,
            # so a second run updates in place instead of raising IntegrityError.
            #
            # queried_at is auto_now_add, so a loaded row is stamped "now". That
            # is correct: staleness only governs whether sync_openet_parcels
            # would re-fetch, and a freshly-rebuilt demo has genuinely just
            # acquired its cache.
            _, created = OpenETCache.objects.update_or_create(
                parcel=parcel,
                start_date=row["start_date"],
                end_date=row["end_date"],
                variable=row["variable"],
                model_name=row["model_name"],
                defaults={
                    "geometry": parcel.geometry,
                    "et_data": crop_et.stamp(
                        row["et_data"], dt.date.fromisoformat(row["received"])
                    ),
                    # Loading the fixture spends no OpenET request, so these rows
                    # must not count toward the monthly allowance. Because this is
                    # an upsert on the uniqueness tuple, a re-run also corrects
                    # rows that predate the origin field.
                    "origin": "fixture",
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
            per_variable[row["variable"]] = per_variable.get(row["variable"], 0) + 1
            if row["variable"] == "ET":
                # A month with no record yet is recorded at the loaded figure and
                # the day it was received; a recorded month keeps its figure.
                crop_et.record_fetched_months(
                    parcel, crop_et.months_of(row["et_data"]), model=row["model_name"]
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(rows)} OpenET cache rows from {fixture} "
                f"({created_count} created, {updated_count} updated, "
                f"{len(parcels)} parcels)"
            )
        )
        for variable in sorted(per_variable):
            self.stdout.write(f"  {variable}: {per_variable[variable]}")
