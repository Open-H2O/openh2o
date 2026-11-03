# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import water levels from a CSV file: DWR's groundwater level export or a field sheet.

The page (``wells/views.py``) saves the upload through ``core/pending_imports.py``
(kind ``water_levels``) and this module does the two jobs the page needs:

* ``parse_csv`` and ``auto_map`` read the file and guess which column holds
  which field, from DWR's column names and a few plain ones;
* ``plan_rows`` decides, for every row, whether it is a new level, a level
  already on file, or an error with a sentence, and ``commit_stored_water_levels``
  writes the new ones. The preview and the commit run the same ``plan_rows``,
  so what the preview counts is what Import writes.

A row is one of two things, like the well page's form: a depth, or a visit
where no depth could be read and a reason says why. DWR's quality column is a
reason for no measurement on some rows and a note about a measured row on
others, so a reason beside a depth is kept in the notes, never refused.
"""
import csv
import datetime as dt
import io
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import pending_imports
from core.geofiles import MAX_UPLOAD_BYTES, too_large_message
from measurements.models import (
    NO_MEASUREMENT_REASONS,
    WATER_LEVEL_METHODS,
    WaterMeasurement,
)
from standards.models import ObservedProperty
from wells.forms import DEPTH_PROPERTY_KEY, level_moment
from wells.models import Well

NO_FILE_MESSAGE = "Choose a file to upload."
NOT_CSV_MESSAGE = "This page imports CSV files only. Save the file as CSV and upload it again."
NO_COLUMNS_MESSAGE = "This file has no column names on its first line."
NO_ROWS_MESSAGE = "This file has column names but no rows below them."
MAPPING_REFUSAL = (
    "Match a column to Well and Date, and to Depth or Reason, then press Import."
)

#: The fields a file can carry, in the order the matching step lists them.
FIELDS = (
    ("well", "Well"),
    ("date", "Date"),
    ("depth", "Depth"),
    ("reason", "Reason"),
    ("method", "Method"),
    ("notes", "Notes"),
)

#: The column names each field is matched from, lower case, best guess first.
#: DWR's own export names lead each list.
ALIASES = {
    "well": ("well_name", "well", "name", "state_well_number", "wcr_number"),
    "date": ("msmt_date", "date", "measurement_date"),
    "depth": ("gse_gwe", "depth", "depth_to_water"),
    "reason": ("wlm_qa_desc", "wlm_qa_detail", "reason", "no_measurement_reason"),
    "method": ("wlm_desc", "wlm_mthd_desc", "method"),
    "notes": ("msmt_cmt", "notes"),
}

#: How many of a message's rows the Row errors table lists before it stops.
ROW_ERROR_FIRST_ROWS = 5

_REASONS = {value.casefold(): value for value, _label in NO_MEASUREMENT_REASONS}
_METHODS = {value.casefold(): value for value, _label in WATER_LEVEL_METHODS}

_ISO_DATE = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[T ]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$"
)
_US_DATE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})"
    r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*([AaPp])[Mm])?)?$"
)
_FOUR_PLACES = Decimal("0.0001")
#: Any depth at or above this rounds past what the column holds (14 digits, 4 after the point).
_LARGEST_DEPTH = Decimal("9999999999.99995")


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


def parse_csv(file, filename=""):
    """``(columns, rows)`` of an uploaded or stored CSV; rows are dicts of strings.

    Raises ImportError with the sentence the page shows for a file that is not
    a CSV, is over the size ceiling, has no column names or has no rows.
    """
    name = (filename or "").lower()
    if name and not name.endswith(".csv"):
        raise ImportError(NOT_CSV_MESSAGE)
    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(too_large_message(size))
    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    if not columns:
        raise ImportError(NO_COLUMNS_MESSAGE)
    rows = [{k: ("" if v is None else v) for k, v in row.items()} for row in reader]
    if not rows:
        raise ImportError(NO_ROWS_MESSAGE)
    return columns, rows


def auto_map(columns):
    """``{field: column}`` guessed from the column names, case and spaces aside."""
    mapping = {}
    for field, _label in FIELDS:
        for alias in ALIASES[field]:
            match = next((c for c in columns if c and c.strip().lower() == alias), None)
            if match is not None:
                mapping[field] = match
                break
    return mapping


def posted_mapping(data):
    """The ``map:<field>`` values a form posted, for the columns it named."""
    mapping = {}
    for field, _label in FIELDS:
        column = data.get(f"map:{field}", "")
        if column:
            mapping[field] = column
    return mapping


def mapping_refusal(mapping):
    """One sentence when the mapping cannot make a level, else an empty string."""
    if not mapping.get("well") or not mapping.get("date"):
        return MAPPING_REFUSAL
    if not mapping.get("depth") and not mapping.get("reason"):
        return MAPPING_REFUSAL
    return ""


# ---------------------------------------------------------------------------
# Reading a cell
# ---------------------------------------------------------------------------


def parse_moment(text):
    """The aware date and time of ``text``: YYYY-MM-DD or M/D/YYYY, with or without a time.

    A time is kept in the site's time zone; a date alone is noon. Raises
    ValueError for anything else, including a day that is not on the calendar.
    """
    text = text.strip()
    match = _ISO_DATE.match(text)
    if match:
        year, month, day, hour, minute, second = match.groups()
        ampm = None
    else:
        match = _US_DATE.match(text)
        if not match:
            raise ValueError(text)
        month, day, year, hour, minute, second, ampm = match.groups()
    if hour is None:
        return level_moment(dt.date(int(year), int(month), int(day)))
    hour = int(hour)
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError(text)
        hour = hour % 12 + (12 if ampm.lower() == "p" else 0)
    naive = dt.datetime(int(year), int(month), int(day), hour, int(minute), int(second or 0))
    return timezone.make_aware(naive)


def _canonical(table, text):
    return table.get(text.strip().replace("’", "'").casefold())


def _cell(row, mapping, field):
    column = mapping.get(field)
    if not column:
        return ""
    return (row.get(column) or "").strip()


# ---------------------------------------------------------------------------
# Deciding what each row is
# ---------------------------------------------------------------------------


def _well_lookup():
    """``(by_key, labels)``: well ids for each name, state well number or WCR number, and each well's record name."""
    by_key = {}
    labels = {}
    for pk, name, registration_id, state_number, wcr_number in Well.objects.values_list(
        "pk", "name", "well_registration_id", "state_well_number", "wcr_number"
    ):
        labels[pk] = f"{registration_id or name} depth to water"
        for key in (name, state_number, wcr_number):
            if key and key.strip():
                by_key.setdefault(key.strip().casefold(), set()).add(pk)
    return by_key, labels


def _on_file(well_ids):
    """The keys of the levels already on these wells: well, local date, depth or reason."""
    keys = set()
    rows = (
        WaterMeasurement.objects.current().filter(well_id__in=well_ids)
        .filter(
            Q(observed_property__key=DEPTH_PROPERTY_KEY)
            | Q(measurement_type="groundwater_level")
        )
        .values_list("well_id", "measurement_date", "value", "no_measurement_reason")
    )
    for well_id, when, value, reason in rows:
        day = timezone.localtime(when).date()
        if value is not None:
            keys.add((well_id, day, "depth", value.quantize(_FOUR_PLACES)))
        elif reason:
            keys.add((well_id, day, "reason", reason))
    return keys


def plan_rows(rows, mapping):
    """What importing ``rows`` with ``mapping`` would do, row by row.

    Returns ``{"new": [...], "duplicates": n, "errors": [...]}``. Each new
    level is a dict ready to save; each error is ``{"line", "message"}`` with
    ``line`` the row's number as a spreadsheet counts it (the header is row 1).
    A level whose well, local date and depth (or reason) are already on file,
    or repeat an earlier row of the same file, is counted in ``duplicates``
    and left out of ``new``.
    """
    by_key, labels = _well_lookup()
    parsed = []
    errors = []
    for index, row in enumerate(rows):
        line = index + 2
        outcome = _read_row(row, mapping, by_key)
        if isinstance(outcome, str):
            errors.append({"line": line, "message": outcome})
        else:
            outcome["line"] = line
            parsed.append(outcome)

    seen = _on_file({level["well_id"] for level in parsed})
    new = []
    duplicates = 0
    for level in parsed:
        day = timezone.localtime(level["moment"]).date()
        if level["value"] is not None:
            key = (level["well_id"], day, "depth", level["value"])
        else:
            key = (level["well_id"], day, "reason", level["reason"])
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        level["name"] = labels[level["well_id"]]
        new.append(level)
    return {"new": new, "duplicates": duplicates, "errors": errors}


def _read_row(row, mapping, by_key):
    """A level dict for a good row, or the sentence that says what is wrong with it."""
    well_text = _cell(row, mapping, "well")
    if not well_text:
        return "This row has no well."
    wells = by_key.get(well_text.casefold(), set())
    if not wells:
        return f"{well_text} does not match a well on file."
    if len(wells) > 1:
        return f"{well_text} matches more than one well on file."
    (well_id,) = wells

    date_text = _cell(row, mapping, "date")
    if not date_text:
        return "This row has no date."
    try:
        moment = parse_moment(date_text)
    except ValueError:
        return f"{date_text} is not a date OpenH2O can read."

    depth_text = _cell(row, mapping, "depth")
    reason_text = _cell(row, mapping, "reason")
    notes = [_cell(row, mapping, "notes")]
    value = None
    reason = ""
    if depth_text:
        try:
            value = Decimal(depth_text)
        except InvalidOperation:
            return f"{depth_text} is not a number."
        if not value.is_finite():
            return f"{depth_text} is not a number."
        if abs(value) >= _LARGEST_DEPTH:
            return f"{depth_text} is too large."
        value = value.quantize(_FOUR_PLACES)
        if reason_text:
            notes.append(f"DWR quality: {reason_text}")
    elif not reason_text:
        return "This row has no depth and no reason."
    else:
        reason = _canonical(_REASONS, reason_text)
        if reason is None:
            return f"{reason_text} is not one of the reasons on the well page."

    method_text = _cell(row, mapping, "method")
    method = _canonical(_METHODS, method_text) if method_text else ""
    if method is None:
        method = ""
        notes.append(f"Method: {method_text}")

    return {
        "well_id": well_id,
        "moment": moment,
        "value": value,
        "reason": reason,
        "method": method,
        "notes": "\n".join(part for part in notes if part),
    }


def group_errors(errors):
    """The row errors one entry per distinct message, in the order first met.

    Each entry is ``{"message", "count", "first_rows", "more"}``: how many rows
    carry the message and the lowest of their row numbers.
    """
    groups = {}
    for error in errors:
        groups.setdefault(error["message"], []).append(error["line"])
    return [
        {
            "message": message,
            "count": len(lines),
            "first_rows": sorted(lines)[:ROW_ERROR_FIRST_ROWS],
            "more": len(lines) > ROW_ERROR_FIRST_ROWS,
        }
        for message, lines in groups.items()
    ]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def commit_stored_water_levels(pending):
    """Write the new levels of the stored file with the confirmed column matches.

    Runs in the import worker (``core/pending_imports.py``); returns the
    context the result block shows.
    """
    with pending_imports.stored_file(pending) as file:
        _columns, rows = parse_csv(file, pending.original_name)
    mapping = pending.settings.get("mapping", {})
    plan = plan_rows(rows, mapping)
    prop = ObservedProperty.objects.filter(key=DEPTH_PROPERTY_KEY).first()
    levels = [
        WaterMeasurement(
            name=level["name"],
            measurement_type="groundwater_level",
            observed_property=prop,
            value=level["value"],
            unit="ft",
            measurement_date=level["moment"],
            well_id=level["well_id"],
            source="imported",
            recorded_by_id=pending.user_id,
            notes=level["notes"],
            method=level["method"],
            no_measurement_reason=level["reason"],
        )
        for level in plan["new"]
    ]
    with transaction.atomic():
        WaterMeasurement.objects.bulk_create(levels, batch_size=1000)
    groups, not_listed = pending_imports.cap_error_rows(group_errors(plan["errors"]))
    return {
        "created": len(levels),
        "skipped_duplicates": plan["duplicates"],
        "error_count": len(plan["errors"]),
        "error_groups": groups,
        "error_groups_not_listed": not_listed,
    }
