# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Load the demonstration's figures from OpenET's field list into an empty database.

The file (``data/merced/openet_fields.json``) holds what OpenET's field list sent for the
OpenET fields that overlap the demonstration's use areas: each field's number and acres,
each use area's acres inside each field, and each field's monthly crop ET and rain in
millimetres, exactly as sent, with the day they were received. It carries no outlines.

**Every row must say when it was received.** A field or month without a received day, a
month received before it ended, an overlap naming a use area this database does not have,
or an overlap or month naming a field the file does not list, is refused with nothing
written, and the command says which and how to fix it.

After loading, each use area's months are recorded from its fields
(``datasync.crop_et.record_received_months``): a month with no record yet is recorded at the
use area's share of its fields' crop ET; a recorded month keeps its figure.

Usage:
    python manage.py load_openet_fields_fixture
    python manage.py load_openet_fields_fixture --fixture /path/to/openet_fields.json
"""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from datasync import crop_et
from datasync.models import OpenETField, OpenETFieldMonth, OpenETFieldShare
from parcels.models import Parcel

DEFAULT_FIXTURE = "data/merced/openet_fields.json"


def _day(text):
    try:
        return dt.date.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _problems(payload):
    """Why the file cannot be loaded as what OpenET's field list sent, as a list of sentences."""
    problems = []
    listed = set()
    for row in payload.get("fields", []):
        listed.add(row.get("field_id"))
        if _day(row.get("received_on")) is None:
            problems.append(f"field {row.get('field_id')}: no received day")
    for row in payload.get("months", []):
        label = f"field {row.get('field_id')} {row.get('month')}"
        received = _day(row.get("received_on"))
        if received is None:
            problems.append(f"{label}: no received day")
            continue
        try:
            first = crop_et.month_first(str(row.get("month")))
        except (TypeError, ValueError):
            problems.append(f"{label}: the month is not a month")
            continue
        if received <= crop_et.last_day(first):
            problems.append(f"{label}: received {received} before the month ended")
        if row.get("field_id") not in listed:
            problems.append(f"{label}: the field is not listed in the file")
    for row in payload.get("shares", []):
        if row.get("field_id") not in listed:
            problems.append(
                f"{row.get('parcel_number')} overlap with field {row.get('field_id')}: "
                "the field is not listed in the file"
            )
    return problems


def _depth(value):
    return None if value in (None, "") else Decimal(str(value))


class Command(BaseCommand):
    help = (
        "Load data/merced/openet_fields.json: OpenET's fields, each use area's acres inside "
        "them, and their monthly crop ET and rain. Refuses before writing anything if a row "
        "has no received day or names a use area this database does not have."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture", default=DEFAULT_FIXTURE, help=f"File to load (default: {DEFAULT_FIXTURE})"
        )

    def handle(self, *args, **options):
        fixture = Path(options["fixture"])
        if not fixture.exists():
            raise CommandError(f"File not found: {fixture}")
        payload = json.loads(fixture.read_text())

        # --- Every row checked first. Nothing below this block writes. ---
        problems = _problems(payload)
        if problems:
            raise CommandError(
                f"{len(problems)} row(s) in {fixture} cannot be loaded: "
                + "; ".join(problems[:5])
                + (" …" if len(problems) > 5 else "")
                + "\n  Nothing was written."
            )
        wanted = {row["parcel_number"] for row in payload["shares"]}
        parcels = Parcel.objects.in_bulk(wanted, field_name="parcel_number")
        missing = sorted(wanted - set(parcels))
        if missing:
            raise CommandError(
                f"{len(missing)} use area(s) in {fixture} are not in this database: "
                + ", ".join(missing[:5])
                + (" …" if len(missing) > 5 else "")
                + "\n  Nothing was written. Seed the use areas first:\n"
                "    python manage.py seed_merced --skip-auto-populate"
            )

        with transaction.atomic():
            fields = {}
            for row in payload["fields"]:
                field, _ = OpenETField.objects.update_or_create(
                    field_id=row["field_id"],
                    defaults={
                        "area_acres": _depth(row.get("area_acres")),
                        "received_on": _day(row["received_on"]),
                    },
                )
                fields[row["field_id"]] = field
            for row in payload["shares"]:
                OpenETFieldShare.objects.update_or_create(
                    parcel=parcels[row["parcel_number"]],
                    field=fields[row["field_id"]],
                    defaults={"overlap_acres": Decimal(str(row["overlap_acres"]))},
                )
            months = set()
            for row in payload["months"]:
                first = crop_et.month_first(str(row["month"]))
                OpenETFieldMonth.objects.update_or_create(
                    field=fields[row["field_id"]],
                    month=first,
                    defaults={
                        "et_mm": _depth(row.get("et_mm")),
                        "pr_mm": _depth(row.get("pr_mm")),
                        "received_on": _day(row["received_on"]),
                    },
                )
                months.add(crop_et.month_text(first))
            recorded = 0
            for parcel in sorted(parcels.values(), key=lambda p: p.parcel_number):
                recorded += len(crop_et.record_received_months(parcel, months))

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(fields)} OpenET fields, {len(payload['shares'])} overlaps with "
                f"{len(parcels)} use areas and {len(payload['months'])} field months from {fixture}; "
                f"{recorded} use area months recorded."
            )
        )
