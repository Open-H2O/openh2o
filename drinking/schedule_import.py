# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Import the state's sampling schedule (the Last and Next Sample Report).

One service, two callers: the Import the state's schedule screen
(``drinking/views/schedule_import.py``) and the ``import_schedule`` command.
``import_schedule_rows`` reads the rows, compares them with the schedule and,
unless ``dry_run``, saves the new rows and the changes.

How a file row finds the schedule row it changes: the same sampling point and
either the same analyte, or no analyte and a ``group_label`` equal to the
file's ANALYTE text (ignoring case and outer spaces). The analyte wins when
both exist. A found row changes only ``frequency``, ``last_done``,
``next_due`` and ``next_due_is_month``; its notes and its label are kept.
A schedule row the file leaves out is listed and left alone.
"""
import re
from datetime import datetime

from django.db import transaction

from drinking.models import (
    SCHEDULE_FREQUENCY_CHOICES,
    Analyte,
    SamplingPoint,
    SamplingSchedule,
)
from drinking.production_import import parse_csv  # noqa: F401  (the screen and the command read the file this way)

REQUIRED_COLUMNS = ["PSCODE", "ANALYTE", "FREQ MONTHS", "NEXT SAMPLE DUE"]

#: Months between samples, for the seven frequencies that have a choice of their own.
_FREQUENCY_BY_MONTHS = {
    1: "monthly",
    3: "quarterly",
    12: "annual",
    36: "every_3_years",
    72: "every_6_years",
    108: "every_9_years",
    120: "every_10_years",
}

_FREQUENCY_LABELS = dict(SCHEDULE_FREQUENCY_CHOICES)
_MONTH_FORM = re.compile(r"^(\d{4})/(\d{1,2})$")
_LABEL_LENGTH = SamplingSchedule._meta.get_field("group_label").max_length

#: The fields a found row can change, in the order a change is listed.
CHANGE_FIELDS = [
    ("frequency", "Frequency"),
    ("last_done", "Last done"),
    ("next_due", "Next due"),
]


def missing_columns_sentence(missing):
    """``This file has no PSCODE, ANALYTE or NEXT SAMPLE DUE column.``"""
    listed = missing[0] if len(missing) == 1 else f"{', '.join(missing[:-1])} or {missing[-1]}"
    return f"This file has no {listed} column."


def missing_columns_message(missing):
    """The screen's message: the sentence plus a pointer to the table below it."""
    return f"{missing_columns_sentence(missing)} The table below lists the columns OpenH2O imports."


def _column_map(columns):
    """``{heading: the file's own spelling}``, ignoring case and outer spaces."""
    found = {}
    for column in columns:
        found.setdefault(column.strip().upper(), column)
    return found


def missing_columns(columns):
    """The required headings the file lacks, in the order the table lists them."""
    present = _column_map(columns)
    return [name for name in REQUIRED_COLUMNS if name not in present]


# ---------------------------------------------------------------------------
# Showing a value
# ---------------------------------------------------------------------------


def format_due(value, is_month):
    """``Jul 2035`` for a month, ``Mar 5, 2024`` for a day, ``No date set`` for none."""
    if value is None:
        return "No date set"
    if is_month:
        return f"{value:%b} {value.year}"
    return f"{value:%b} {value.day}, {value.year}"


def format_day(value):
    if value is None:
        return "Not recorded"
    return f"{value:%b} {value.day}, {value.year}"


def frequency_label(key):
    return _FREQUENCY_LABELS.get(key, key)


# ---------------------------------------------------------------------------
# Reading a row
# ---------------------------------------------------------------------------


def _read_day(text):
    for form in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, form).date()
        except ValueError:
            continue
    return None


def _read_due(text):
    """``(date, is_month)`` or None."""
    match = _MONTH_FORM.match(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and year >= 1:
            return datetime(year, month, 1).date(), True
        return None
    day = _read_day(text)
    return (day, False) if day else None


def _lookups(system):
    points = {
        ps_code: pk
        for ps_code, pk in SamplingPoint.objects.filter(
            facility__system=system
        ).values_list("ps_code", "pk")
    }
    by_code, by_name = {}, {}
    for pk, code, name in Analyte.objects.values_list("pk", "ddw_code", "name"):
        if code:
            by_code[code] = pk
        by_name[name.strip().lower()] = pk
    return points, by_code, by_name


def build_rows(columns, rows, system):
    """Read every file row. One dict per row, in file order.

    Each has ``index`` (0-based; the spreadsheet's row is ``index + 2``),
    ``errors`` (sentences) and, when there are none, the values to save:
    ``point_id``, ``analyte_id``, ``name``, ``frequency``, ``months``,
    ``last_done``, ``next_due``, ``next_due_is_month`` and ``notes``.
    """
    present = _column_map(columns)
    points, by_code, by_name = _lookups(system)

    def cell(row, heading):
        column = present.get(heading)
        return (row.get(column) or "").strip() if column else ""

    built = []
    for index, row in enumerate(rows):
        errors = []
        item = {"index": index, "errors": errors}

        ps_code = cell(row, "PSCODE")
        point_id = points.get(ps_code)
        if not ps_code:
            errors.append("PSCODE is blank.")
        elif point_id is None:
            errors.append(
                f"No sampling point on file has the PS Code {ps_code}. Add the "
                "sampling point first, or correct the code in the file."
            )

        name = cell(row, "ANALYTE")
        code = cell(row, "ANALYTE CODE")
        analyte_id = None
        if not name:
            errors.append("ANALYTE is blank.")
        else:
            analyte_id = by_code.get(code) if code else None
            if analyte_id is None:
                analyte_id = by_name.get(name.lower())

        months_text = cell(row, "FREQ MONTHS")
        months = int(months_text) if re.fullmatch(r"\d+", months_text) else 0
        if months < 1:
            errors.append(
                f"OpenH2O cannot read '{months_text}' in FREQ MONTHS as a number of months."
            )

        last_text = cell(row, "LAST SAMPLE")
        last_done = None
        if last_text:
            last_done = _read_day(last_text)
            if last_done is None:
                errors.append(
                    f"OpenH2O cannot read the date '{last_text}' in LAST SAMPLE. "
                    "OpenH2O reads a date in the form M/D/YYYY."
                )

        due_text = cell(row, "NEXT SAMPLE DUE")
        due = _read_due(due_text) if due_text else None
        if due is None:
            errors.append(
                f"OpenH2O cannot read the month '{due_text}' in NEXT SAMPLE DUE. "
                "OpenH2O reads a month in the form YYYY/MM."
            )

        if not errors:
            frequency = _FREQUENCY_BY_MONTHS.get(months, "other")
            lines = []
            if frequency == "other":
                lines.append(f"Every {months} months")
            if cell(row, "GROUP"):
                lines.append(f"Group: {cell(row, 'GROUP')}")
            if cell(row, "NOTES"):
                lines.append(cell(row, "NOTES"))
            item.update(
                point_id=point_id,
                point=ps_code,
                analyte_id=analyte_id,
                name=name[:_LABEL_LENGTH],
                frequency=frequency,
                last_done=last_done,
                next_due=due[0],
                next_due_is_month=due[1],
                notes="\n".join(lines),
            )
        built.append(item)
    return built


# ---------------------------------------------------------------------------
# Comparing with the schedule
# ---------------------------------------------------------------------------


def _label_key(text):
    return " ".join(text.split()).lower()


def _find_existing(item, by_analyte, by_label):
    """The schedule row this file row changes, or None. The analyte wins."""
    if item["analyte_id"] is not None:
        found = by_analyte.get((item["point_id"], item["analyte_id"]))
        if found is not None:
            return found
    return by_label.get((item["point_id"], _label_key(item["name"])))


def _changes(existing, item):
    """``[(field label, old text, new text)]`` for what the file changes."""
    changes = []
    if existing.frequency != item["frequency"]:
        changes.append((
            "Frequency", frequency_label(existing.frequency),
            frequency_label(item["frequency"]),
        ))
    # A blank date in the file changes nothing: the office's own date stays.
    if item["last_done"] is not None and existing.last_done != item["last_done"]:
        changes.append((
            "Last done", format_day(existing.last_done), format_day(item["last_done"]),
        ))
    if item["next_due"] is not None and (existing.next_due, existing.next_due_is_month) != (
        item["next_due"], item["next_due_is_month"]
    ):
        changes.append((
            "Next due",
            format_due(existing.next_due, existing.next_due_is_month),
            format_due(item["next_due"], item["next_due_is_month"]),
        ))
    return changes


def plan_rows(built, system):
    """Compare the read rows with the schedule. Saves nothing.

    Returns a dict: ``new`` (items), ``changed`` (dicts with ``item``,
    ``existing``, ``changes``), ``unchanged`` (count), ``errors``
    (``{"line", "messages"}``), ``repeats`` (count), ``left_out`` (schedule
    rows no file row named).
    """
    schedule = list(
        SamplingSchedule.objects.filter(system=system)
        .select_related("analyte", "sampling_point")
        .order_by("pk")
    )
    by_analyte, by_label = {}, {}
    for row in schedule:
        if row.sampling_point_id is None:
            continue
        if row.analyte_id is not None:
            by_analyte.setdefault((row.sampling_point_id, row.analyte_id), row)
        else:
            by_label.setdefault(
                (row.sampling_point_id, _label_key(row.group_label)), row
            )

    plan = {
        "new": [], "changed": [], "unchanged": 0, "errors": [],
        "repeats": 0, "left_out": [],
    }
    seen = set()
    named = set()
    for item in built:
        if item["errors"]:
            plan["errors"].append(
                {"line": item["index"] + 2, "messages": item["errors"]}
            )
            continue
        key = (
            (item["point_id"], "analyte", item["analyte_id"])
            if item["analyte_id"] is not None
            else (item["point_id"], "label", _label_key(item["name"]))
        )
        if key in seen:
            plan["repeats"] += 1
            continue
        seen.add(key)
        existing = _find_existing(item, by_analyte, by_label)
        if existing is None:
            plan["new"].append(item)
            continue
        named.add(existing.pk)
        changes = _changes(existing, item)
        if changes:
            plan["changed"].append(
                {"item": item, "existing": existing, "changes": changes}
            )
        else:
            plan["unchanged"] += 1
    plan["left_out"] = [row for row in schedule if row.pk not in named]
    return plan


def commit_plan(plan, system):
    """Save the new rows and the changes. Returns ``(added, changed)``."""
    with transaction.atomic():
        for item in plan["new"]:
            SamplingSchedule.objects.create(
                system=system,
                sampling_point_id=item["point_id"],
                analyte_id=item["analyte_id"],
                group_label="" if item["analyte_id"] is not None else item["name"],
                frequency=item["frequency"],
                last_done=item["last_done"],
                next_due=item["next_due"],
                next_due_is_month=item["next_due_is_month"],
                notes=item["notes"],
            )
        for entry in plan["changed"]:
            row, item = entry["existing"], entry["item"]
            row.frequency = item["frequency"]
            if item["last_done"] is not None:
                row.last_done = item["last_done"]
            if item["next_due"] is not None:
                row.next_due = item["next_due"]
                row.next_due_is_month = item["next_due_is_month"]
            row.save(update_fields=[
                "frequency", "last_done", "next_due", "next_due_is_month",
                "updated_at",
            ])
    return len(plan["new"]), len(plan["changed"])


def point_text(row):
    """A schedule row's sampling point for a list."""
    return row.sampling_point.ps_code if row.sampling_point_id else "Not set"


def import_schedule_rows(columns, rows, *, system, dry_run=False):
    """Read, compare and (unless ``dry_run``) save. The one function both callers use.

    Raises ImportError with the missing-column sentence when the file lacks a
    required heading. Returns the plan plus ``row_count``, ``added`` and
    ``changed`` (the counts a dry run would save, or did save).
    """
    missing = missing_columns(columns)
    if missing:
        raise ImportError(missing_columns_sentence(missing))
    built = build_rows(columns, rows, system)
    plan = plan_rows(built, system)
    plan["row_count"] = len(rows)
    plan["error_row_count"] = len(plan["errors"])
    if dry_run:
        plan["added"], plan["changed_count"] = len(plan["new"]), len(plan["changed"])
    else:
        plan["added"], plan["changed_count"] = commit_plan(plan, system)
    return plan
