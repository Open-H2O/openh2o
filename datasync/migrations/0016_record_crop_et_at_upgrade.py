# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record each month's crop ET from the depth its last calculation used; move no number.

Until this version a month's crop ET lived only in the OpenET cache, and each
calculation read whatever was fetched last. From now on the calculation reads the
month's recorded figure (``datasync/crop_et.py``). This step records one figure per
use area and month that has fetched crop ET:

* the depth the month's last calculation used (its stored crop ET step), so the
  next calculation reads exactly what the last one read;
* for a month never calculated, or a calculation that stored no depth, the newest
  fetched figure, read the way the calculation read the cache.

Never an ET estimate entry's depth: an entry rounds the depth and may have been
typed by hand. The fetch date is empty and the note says "Recorded at upgrade".
A month inside a finalized water year is recorded through the recorded override,
with that note as the reason. This step writes no ledger entry and no calculation,
so no balance, total, worksheet or state file moves. It prints four counts: months
recorded (and how many in finalized years), months whose newest fetch now differs
from the record, ET estimate entries that differ from their month's record, and
months skipped, with why.
"""

import datetime as dt
import sys
from decimal import Decimal

from django.db import migrations

RECORDED_AT_UPGRADE = "Recorded at upgrade"
PENDING_MARKER = "__PENDING__"
DIFFERENT_MM = Decimal("0.01")


def _month_text(day):
    return f"{day.year}-{day.month:02d}"


def _first(period):
    return dt.date(int(period[:4]), int(period[5:7]), 1)


def _newest_mm(rows, period):
    """The month's newest fetched depth across ``rows`` (oldest first), as the calculation read it."""
    from accounting.steps import _item_in_span

    by_date = {}
    for row in rows:
        for item in row.et_data or []:
            if not isinstance(item, dict):
                continue
            item_date = str(item.get("date", ""))
            if item_date and not _item_in_span(item_date, row.start_date, row.end_date):
                continue
            if item_date.startswith(period) and item.get("et") is not None:
                by_date[item_date] = Decimal(str(item["et"]))
    if not by_date:
        return None
    return sum(by_date.values(), Decimal("0"))


def _run_depth(runs, parcel_id, period, model):
    """The crop ET depth the month's last calculation used, when it stored one."""
    run = runs.objects.filter(parcel_id=parcel_id, period=period).order_by("-created_at", "-pk").first()
    if run is None:
        return None
    for step in run.breakdown or []:
        if not isinstance(step, dict) or step.get("step_type") != "et_gross":
            continue
        detail = step.get("detail") or {}
        if detail.get("model", "Ensemble") != model or detail.get("et_mm") in (None, ""):
            return None
        return Decimal(str(detail["et_mm"]))
    return None


def record_months(apps, out=None):
    """Record the months; return the counts (also printed to ``out``)."""
    from accounting.locks import override
    from accounting.services import et_mm_to_acre_feet

    out = out if out is not None else sys.stdout
    cache = apps.get_model("datasync", "OpenETCache")
    figures = apps.get_model("datasync", "CropETFigure")
    runs = apps.get_model("accounting", "CalculationRun")
    ledger = apps.get_model("parcels", "ParcelLedger")
    periods = apps.get_model("accounting", "ReportingPeriod")
    finalized = list(periods.objects.filter(is_finalized=True).values_list("start_date", "end_date"))

    counts = {
        "recorded": 0, "recorded_finalized": 0, "newer": 0, "entries_differ": 0,
        "skipped": 0, "skipped_reasons": {},
    }
    rows = (
        cache.objects.filter(variable="ET", parcel__isnull=False)
        .exclude(model_name=PENDING_MARKER)
        .order_by("queried_at", "pk")
    )
    grouped = {}
    for row in rows:
        grouped.setdefault((row.parcel_id, row.model_name), []).append(row)

    for (parcel_id, model), parcel_rows in sorted(grouped.items()):
        months = sorted({
            str(item.get("date", ""))[:7]
            for row in parcel_rows
            for item in row.et_data or []
            if isinstance(item, dict) and item.get("et") is not None and len(str(item.get("date", ""))) >= 7
        })
        for period in months:
            try:
                first = _first(period)
            except ValueError:
                counts["skipped"] += 1
                counts["skipped_reasons"]["a month that is not a date"] = (
                    counts["skipped_reasons"].get("a month that is not a date", 0) + 1
                )
                continue
            current = figures.objects.filter(
                parcel_id=parcel_id, month=first, variable="ET", model_name=model,
                voided_at__isnull=True, replaced_at__isnull=True,
            )
            if current.exists():
                continue
            newest = _newest_mm(parcel_rows, period)
            depth = _run_depth(runs, parcel_id, period, model)
            if depth is None:
                depth = newest
            if depth is None:
                reason = "no fetched figure inside its cache window"
                counts["skipped"] += 1
                counts["skipped_reasons"][reason] = counts["skipped_reasons"].get(reason, 0) + 1
                continue
            closed = any(start <= first <= end for start, end in finalized)
            fields = {
                "parcel_id": parcel_id, "month": first, "variable": "ET", "model_name": model,
                "depth_mm": depth, "fetched_on": None, "note": RECORDED_AT_UPGRADE,
            }
            if closed:
                with override(RECORDED_AT_UPGRADE):
                    figures.objects.create(**fields)
                counts["recorded_finalized"] += 1
            else:
                figures.objects.create(**fields)
            counts["recorded"] += 1
            if newest is not None and abs(newest - depth) >= DIFFERENT_MM:
                counts["newer"] += 1
            entry = (
                ledger.objects.filter(
                    parcel_id=parcel_id, source_type="et_estimate",
                    effective_date__year=first.year, effective_date__month=first.month,
                    voided_at__isnull=True, replaced_at__isnull=True,
                )
                .select_related("parcel")
                .first()
            )
            if entry is not None:
                recorded = abs(et_mm_to_acre_feet(depth, entry.parcel.area_acres or Decimal("0")))
                if f"{abs(entry.amount_acre_feet):.2f}" != f"{recorded:.2f}":
                    counts["entries_differ"] += 1

    out.write(
        "\n  Crop ET recorded for {recorded} use-area months ({recorded_finalized} in finalized "
        "water years). OpenET now reports a different figure for {newer}. ET estimate entries "
        "that differ from their month's record: {entries_differ}. Skipped: {skipped}.\n".format(**counts)
    )
    for reason, number in sorted(counts["skipped_reasons"].items()):
        out.write(f"    skipped {number}: {reason}\n")
    return counts


def forwards(apps, schema_editor):
    record_months(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0015_cropetfigure"),
        ("accounting", "0046_second_language_pass_labels"),
        ("parcels", "0027_irrigation_method_from_a_month"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
