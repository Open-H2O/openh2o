# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk diversion-volume import against a point of diversion (146-03 Task 4, D4).

Mirrors ``accounting/ledger_import.py``'s shape (read that module first): one
service, two callers (the web upload and the management command), every
coercion counted and named per row. It is its own module rather than a branch
of ``surface/importer.py`` because that module resolves *points and rights*
from the state's fixed LIST headers; this one resolves *monthly volumes*
against a point already on file, in either of two layouts, with unit
conversions and a report-year-to-calendar-month crosswalk neither of the
other importers needs.

Two layouts, recognised by header (``recognise_layout``):

* **The state's Water Use Reported layout** -- one row per ``APPL_ID``,
  ``YEAR``, ``MONTH``, ``DIVERSION_TYPE`` (DIRECT, STORAGE, USE; COMBINED
  before 2015), ``AMOUNT`` in acre-feet. ``MONTH`` is the calendar month
  number (1 = January, 10 = October) -- the source is
  ``six-shapes-2026-09/datasets/shape-1-surface-diverter/PROVENANCE.md``
  lines 121-129. When the file carries its own ``calendar_month`` column
  (``YYYY-MM``), that column is trusted outright; otherwise the calendar
  month is computed from ``SiteConfig.diversion_report_year_rule`` (M2).
* **The operator's book layout** -- a point-ish column (``point``,
  ``local_name``, ``headgate``, ``name`` -- ``headgate`` is an alias of
  ``local_name``), a month source (``date``, first of its month, or
  ``month``), and either a volume-ish column (``volume``, ``acre_feet``,
  ``af``) or, absent that, ``flow_cfs`` and ``hours`` together (rate times
  duration, 1.9835 acre-feet per cfs-day, M... the memo's own conversion
  block). ``acre_feet``/``af`` are already acre-feet and need no factor
  named; ``volume`` needs a paired ``unit`` column (af / gallons / gal /
  ccf / mg / cfs_hours) to know which factor applies.

Conversions named on every row that needed one: gallons to acre-feet at
325,851 gallons per acre-foot; CCF to gallons at 748.05; MG at 1,000,000
gallons; cfs-hours to acre-feet at 1.9835 acre-feet per cfs-day (the memo's
M1 and M7).

Rules enforced here, in order:

1. Layout recognition, then per-row field validation.
2. TYPE MAPPING. DIRECT -> direct_use, STORAGE -> to_storage, COMBINED is a
   row error naming the year (pre-2015 files never file it). USE has no
   product type of its own -- the USE rule decides whether it is dropped
   (counted, never written), added to the matching DIRECT row's
   ``returned_af`` (USE minus DIRECT, floored at zero and capped at the
   diverted volume), or treated as its own direct_use row. The rule comes
   from the ``use_rule`` keyword when the caller passes one (146-03 Task 6:
   the import screen's own mapping-step question, shown only when the file
   has USE rows); otherwise it falls back to the deployment's remembered
   default, ``SiteConfig.diversion_use_type_rule``.
3. WITHIN-FILE COMBINE. Two or more rows landing on the same (point, month,
   diversion type) -- a book of deliveries often carries two or more
   deliveries a month at one headgate -- are summed into ONE record, never
   written as two. Reported as "N rows combined into one month" per group.
4. POINT RESOLUTION, in order: the state's own ``APPL_POD`` column; else the
   right (``APPL_ID``) when it has exactly one point on file; else a
   point-ish column (local_name / headgate / point / name); else the
   whole-file point chosen in the mapping step. A row that resolves to none
   of these is UNRESOLVED -- reported and never written, kept apart from a
   row error because nothing about the row itself is wrong.
5. VALIDATION. Every candidate row is checked against
   ``DiversionRecord.clean()`` (returned cannot exceed the diverted volume)
   before anything is written.
6. DEDUP (skip and count, never overwrite). A candidate whose
   (point, month, diversion_type) already exists in the database is skipped
   and counted -- re-importing the same file writes nothing the second time.
7. COMMIT. One outer transaction; each surviving row gets its own savepoint,
   so one row's unexpected failure does not lose every other row already
   validated.  The reporting period covering each row's month is attached
   the same way ``surface/views.py::diversion_record_create`` does.
"""
import calendar
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.locks import finalized_message
from accounting.models import ReportingPeriod
from core.models import SiteConfig
from surface.estimate import discard_estimate
from surface.importer import (
    NO_COLUMNS_MESSAGE,
    NO_ROWS_MESSAGE,
    NOT_CSV_MESSAGE,
    too_large_message,
)
from surface.models import DiversionRecord, PointOfDiversion, WaterRight

MAX_ROWS = 2000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB, the same ceiling every other importer uses

#: The import screen's own USE-row question (146-03 Task 6): same three values as
#: ``SiteConfig.DIVERSION_USE_TYPE_RULE_CHOICES``, but the copy is aimed at
#: someone looking at the rows in THIS file, not at a deployment-wide
#: default -- so the wording differs and lives here, not on the model.
USE_RULE_CHOICES = [
    ("drop", "Ignore them"),
    ("returned", "Count the difference as water returned to the stream"),
    ("as_direct", "Count them as direct diversion"),
]

#: The state's own Water Use Reported header, upper-cased for comparison
#: (recognise_layout). Presence of all five, in any column order, is what
#: marks a file as the state layout.
_STATE_REQUIRED = {"APPL_ID", "YEAR", "MONTH", "DIVERSION_TYPE", "AMOUNT"}

#: Book-layout column aliases, lower-cased. "headgate" is the ditch tender's
#: own word for a local_name; this is the one place it is accepted.
_POINT_COLUMNS = ("local_name", "headgate", "point", "name")
_VOLUME_COLUMNS = ("acre_feet", "af")

#: M1, M7: the memo's own conversion factors, named on every row that uses
#: them so a reader never has to trust an unlabeled number.
GALLONS_PER_ACRE_FOOT = Decimal("325851")
GALLONS_PER_CCF = Decimal("748.05")
GALLONS_PER_MG = Decimal("1000000")
#: 1 cfs-day = 1.9835 acre-feet; a cfs-hour is that figure divided by 24.
ACRE_FEET_PER_CFS_DAY = Decimal("1.9835")

_FOUR_PLACES = Decimal("0.0001")

#: Whole-file problems (bad extension, no headers, unrecognised layout) raise
#: the plain builtin ``ImportError`` -- the same convention ``surface/importer.py``
#: already uses for the same purpose, so both importers' views catch it the
#: same way.

# ---------------------------------------------------------------------------
# parse_csv / recognise_layout
# ---------------------------------------------------------------------------


def parse_csv(file_obj, filename=""):
    """Parse an uploaded (or opened) CSV into (columns, rows).

    ``rows`` is a list of raw string dicts, exactly as the file wrote them --
    layout recognition and coercion happen later. Raises ImportError on a
    non-CSV extension, an oversized file, no headers, or no data rows.
    """
    name = (filename or "").lower()
    if name and not name.endswith(".csv"):
        raise ImportError(NOT_CSV_MESSAGE)

    size = getattr(file_obj, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(too_large_message(size, MAX_UPLOAD_BYTES))

    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    if not columns:
        raise ImportError(NO_COLUMNS_MESSAGE)
    rows = [{k: ("" if v is None else v) for k, v in row.items()} for row in reader]
    if not rows:
        raise ImportError(NO_ROWS_MESSAGE)
    if len(rows) > MAX_ROWS:
        raise ImportError(row_cap_message(len(rows)))
    return columns, rows


def row_cap_message(row_count):
    """Split by point or by year: a split that puts one point's month in two
    files loses the second part's volume, because the second import skips
    that point, month and type as already on file (commit_rows)."""
    return (
        f"This file has {row_count:,} rows, and OpenH2O imports up to "
        f"{MAX_ROWS:,} rows from one file. Split the file by point or by year "
        "and import each part."
    )


def recognise_layout(columns):
    """'state' or 'book', by header alone. Raises ImportError naming the

    headers seen when neither is recognised -- never a silent guess.
    """
    upper = {c.strip().upper() for c in columns if c}
    if _STATE_REQUIRED <= upper:
        return "state"

    lower = {c.strip().lower() for c in columns if c}
    has_point = any(col in lower for col in _POINT_COLUMNS)
    has_month = bool({"date", "month"} & lower)
    has_volume = any(col in lower for col in _VOLUME_COLUMNS) or "volume" in lower
    has_flow_hours = {"flow_cfs", "hours"} <= lower
    # A book with no point column (one headgate) is a book: its rows take the
    # point chosen for the whole file on the preview.
    if (has_point or has_month) and (has_volume or has_flow_hours):
        return "book"

    # The import page adds "The tables below list the columns OpenH2O
    # imports." (surface/views.py LAYOUT_TABLES_SENTENCE).
    raise ImportError(
        "OpenH2O does not recognize the columns in this file: " + ", ".join(columns) + "."
    )


# ---------------------------------------------------------------------------
# Conversions -- named on every row that uses one
# ---------------------------------------------------------------------------


def _cfs_hours_to_af(flow_cfs, hours):
    return (flow_cfs * hours / Decimal("24")) * ACRE_FEET_PER_CFS_DAY


def _convert_generic_volume(amount, unit, line_num):
    """('volume' + 'unit' book rows) -> (af, conversion-dict-or-None) | (None, error).

    A blank unit is an error: it used
    to be read as acre-feet with no note, so a book kept in gallons imported
    325,851 times its water.
    """
    written = (unit or "").strip()
    unit = written.lower()
    if not unit:
        return None, "The unit is blank. Enter af, gallons, ccf, mg or cfs_hours."
    if unit in ("af", "acre_feet", "acre-feet", "acre-ft", "ac-ft", "acre feet", "acre ft"):
        return amount, None
    if unit in ("gallons", "gal", "g"):
        af = amount / GALLONS_PER_ACRE_FOOT
        return af, {
            "line": line_num, "from": f"{amount} gallons", "to": "acre-feet",
            "factor": f"{GALLONS_PER_ACRE_FOOT} gallons per acre-foot",
            "value": str(af.quantize(_FOUR_PLACES)),
        }
    if unit == "ccf":
        gallons = amount * GALLONS_PER_CCF
        af = gallons / GALLONS_PER_ACRE_FOOT
        return af, {
            "line": line_num, "from": f"{amount} CCF", "to": "acre-feet",
            "factor": f"{GALLONS_PER_CCF} gallons per CCF, "
                      f"{GALLONS_PER_ACRE_FOOT} gallons per acre-foot",
            "value": str(af.quantize(_FOUR_PLACES)),
        }
    if unit == "mg":
        gallons = amount * GALLONS_PER_MG
        af = gallons / GALLONS_PER_ACRE_FOOT
        return af, {
            "line": line_num, "from": f"{amount} MG", "to": "acre-feet",
            "factor": f"1 MG = {GALLONS_PER_MG} gallons, "
                      f"{GALLONS_PER_ACRE_FOOT} gallons per acre-foot",
            "value": str(af.quantize(_FOUR_PLACES)),
        }
    if unit == "cfs_hours":
        af = amount * (ACRE_FEET_PER_CFS_DAY / Decimal("24"))
        return af, {
            "line": line_num, "from": f"{amount} cfs-hours", "to": "acre-feet",
            "factor": f"{ACRE_FEET_PER_CFS_DAY} acre-feet per cfs-day "
                      f"({ACRE_FEET_PER_CFS_DAY}/24 per cfs-hour)",
            "value": str(af.quantize(_FOUR_PLACES)),
        }
    return None, (
        f"OpenH2O does not recognize the unit '{written}'. "
        "Use af, gallons, ccf, mg or cfs_hours."
    )


# ---------------------------------------------------------------------------
# Point resolution
# ---------------------------------------------------------------------------


def resolve_point(row_l, whole_file_point, *, right_cache, right_points_cache):
    """Resolve one row's point of diversion.

    Order: APPL_POD; else the right (APPL_ID) when it has exactly one point
    on file; else a point-ish column (local_name / headgate / point / name);
    else the whole-file point chosen in the mapping step. A right not on file
    falls through to the point column and the whole-file point.
    Returns (PointOfDiversion, None) or
    (None, reason).
    """
    choose = "choose one point of diversion for the whole file on the preview."
    appl_pod = row_l.get("appl_pod", "").strip()
    if appl_pod:
        point = PointOfDiversion.objects.filter(name=appl_pod).first()
        if point:
            return point, None
        return None, (
            f"No point of diversion on file is named '{appl_pod}'. "
            "Add the point first, or correct the name in the file."
        )

    appl_id = row_l.get("appl_id", "").strip()
    right = None
    if appl_id:
        if appl_id not in right_cache:
            right_cache[appl_id] = WaterRight.objects.filter(right_id=appl_id).first()
        right = right_cache[appl_id]
        if right is not None:
            if right.pk not in right_points_cache:
                right_points_cache[right.pk] = list(
                    PointOfDiversion.objects.filter(water_right=right)
                )
            points = right_points_cache[right.pk]
            if len(points) == 1:
                return points[0], None
        # Not on file, or 0 or several points: fall through to a point
        # column, then the whole-file point.

    for key in _POINT_COLUMNS:
        value = row_l.get(key, "").strip()
        if value:
            point = PointOfDiversion.objects.filter(local_name=value).first()
            if point is None:
                point = PointOfDiversion.objects.filter(name=value).first()
            if point:
                return point, None
            return None, (
                f"No point of diversion on file has the name or local name '{value}'. "
                "Add the point first, or correct the name in the file."
            )

    if whole_file_point is not None:
        return whole_file_point, None

    if appl_id and right is None:
        return None, (
            f"No water right on file has the application number {appl_id}. "
            f"Import the water right, or {choose}"
        )
    if appl_id:
        n = len(right_points_cache[right.pk])
        if n == 0:
            return None, (
                f"Water right {appl_id} has no point of diversion on file. "
                f"{choose[0].upper()}{choose[1:]}"
            )
        return None, (
            f"Water right {appl_id} has {n} points of diversion, so OpenH2O cannot "
            f"tell which one this row belongs to. Add an APPL_POD column, or {choose}"
        )
    return None, (
        "This row does not name a point of diversion. Add a point column to the file, "
        f"or {choose}"
    )


# ---------------------------------------------------------------------------
# Report-year to calendar month (M2)
# ---------------------------------------------------------------------------


def _report_year_to_calendar_month(year, month_num, site_config):
    """(date, None) or (None, error) -- the rule stated in the preview names

    which branch ran (rule_sentence, below).
    """
    rule = site_config.diversion_report_year_rule
    if rule == "calendar_year":
        return date(year, month_num, 1), None
    if rule == "season":
        start = site_config.season_start_month
        if not start:
            return None, SEASON_WITHOUT_START
    else:
        start = 10  # water_year: October fixed.
    calendar_year = year - 1 if month_num >= start else year
    return date(calendar_year, month_num, 1), None


#: Delivery Settings now refuses it.
SEASON_WITHOUT_START = (
    "The report year on Delivery Settings is a season with no starting month. "
    "Enter the starting month on Delivery Settings."
)


def rule_sentence(site_config):
    """How YEAR and MONTH become a calendar month, said above the preview's
    settings for a Water Use Reported file only. A season is read as ending in YEAR, as a water year is.
    """
    rule = site_config.diversion_report_year_rule
    if rule == "calendar_year":
        return "OpenH2O reads YEAR and MONTH as the calendar year and month."
    if rule == "season":
        start = site_config.season_start_month
        if not start:
            return SEASON_WITHOUT_START
        start_name = calendar.month_name[start]
        if start == 1:
            span = f"a season starting in {start_name} and ending in December"
        else:
            span = (
                f"a season starting in {start_name} and ending the next "
                f"{calendar.month_name[start - 1]}"
            )
        return (
            f"OpenH2O reads YEAR as {span}, so MONTH {start} through 12 fall in "
            "the calendar year before YEAR."
        )
    return (
        "OpenH2O reads YEAR as the water year ending in September, so MONTH 10, "
        "11 and 12 fall in the calendar year before YEAR."
    )


# ---------------------------------------------------------------------------
# Row processors
# ---------------------------------------------------------------------------

_STATE_TYPE_MAP = {"DIRECT": "direct_use", "STORAGE": "to_storage", "USE": "use"}


def _lower_row(row):
    return {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}


def _process_state_row(line_num, row, *, whole_file_point, right_cache,
                        right_points_cache, site_config):
    row_l = _lower_row(row)
    errors = []

    appl_id = row_l.get("appl_id", "")
    if not appl_id:
        errors.append("APPL_ID is blank.")

    year = None
    year_raw = row_l.get("year", "")
    try:
        year = int(year_raw)
    except ValueError:
        errors.append(f"YEAR '{year_raw}' is not a year.")

    month_num = None
    month_raw = row_l.get("month", "")
    try:
        month_num = int(month_raw)
        if not (1 <= month_num <= 12):
            raise ValueError
    except ValueError:
        errors.append(f"MONTH '{month_raw}' is not a month number from 1 to 12.")

    dtype_written = row_l.get("diversion_type", "").strip()
    dtype_raw = dtype_written.upper()
    # The state writes it "Combined (Direct + Storage)" (its data dictionary;
    # message B row 4), so match the word, not the whole value.
    if dtype_raw.startswith("COMBINED"):
        errors.append(
            "OpenH2O does not import Combined (Direct + Storage) rows. Direct "
            "diversion and storage need separate rows."
        )
    elif dtype_raw not in _STATE_TYPE_MAP:
        errors.append(
            f"OpenH2O does not recognize the diversion type '{dtype_written}'. "
            "Use DIRECT, STORAGE or USE."
        )

    amount = None
    amount_raw = row_l.get("amount", "")
    if not amount_raw:
        errors.append("AMOUNT is blank.")
    else:
        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            errors.append(f"AMOUNT '{amount_raw}' is not a number.")

    if errors:
        return {"line": line_num, "errors": errors}

    note = None
    calendar_month_raw = row_l.get("calendar_month", "")
    if calendar_month_raw:
        try:
            cal_year_s, cal_month_s = calendar_month_raw.split("-")
            month_date = date(int(cal_year_s), int(cal_month_s), 1)
            note = f"calendar_month column trusted ({calendar_month_raw})"
        except (ValueError, TypeError):
            return {
                "line": line_num,
                "errors": [f"calendar_month '{calendar_month_raw}' is not written YYYY-MM."],
            }
    else:
        month_date, rule_error = _report_year_to_calendar_month(year, month_num, site_config)
        if rule_error:
            return {"line": line_num, "errors": [rule_error]}

    point, point_reason = resolve_point(
        row_l, whole_file_point, right_cache=right_cache,
        right_points_cache=right_points_cache,
    )

    return {
        "line": line_num,
        "point": point,
        "point_reason": point_reason,
        "month": month_date,
        "kind": _STATE_TYPE_MAP[dtype_raw],
        "amount_af": amount,
        "returned_af": Decimal("0"),
        "max_flow_cfs": None,
        "conversions": [],
        "note": note,
        "errors": [],
    }


def _parse_book_month(raw):
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().replace(day=1)
        except ValueError:
            continue
    return None


_BOOK_TYPE_MAP = {
    "direct": "direct_use", "direct_use": "direct_use",
    "storage": "to_storage", "to_storage": "to_storage",
    "use": "use",
}


def _process_book_row(line_num, row, *, whole_file_point, right_cache, right_points_cache):
    row_l = _lower_row(row)
    errors = []

    month_date = None
    month_source = None
    for key in ("date", "month"):
        raw = row_l.get(key, "")
        if raw:
            month_source = key
            month_date = _parse_book_month(raw)
            if month_date is None:
                errors.append(
                    f"The {key} '{raw}' is not written YYYY-MM-DD, YYYY-MM or M/D/YYYY."
                )
            break
    if month_source is None:
        errors.append("This row has no date or month.")

    type_written = row_l.get("type", "").strip()
    type_raw = type_written.lower()
    if not type_raw:
        kind = "direct_use"
    elif type_raw in _BOOK_TYPE_MAP:
        kind = _BOOK_TYPE_MAP[type_raw]
    else:
        errors.append(
            f"OpenH2O does not recognize the diversion type '{type_written}'. "
            "Use direct, storage or use."
        )
        kind = None

    conversions = []
    amount = None
    acre_feet_col = "acre_feet" if row_l.get("acre_feet", "") else "af"
    acre_feet_raw = row_l.get(acre_feet_col, "")
    volume_raw = row_l.get("volume", "")
    flow_cfs_raw = row_l.get("flow_cfs", "")
    hours_raw = row_l.get("hours", "")

    if acre_feet_raw:
        try:
            amount = Decimal(acre_feet_raw)
        except InvalidOperation:
            errors.append(f"The {acre_feet_col} value '{acre_feet_raw}' is not a number.")
    elif volume_raw:
        try:
            raw_amount = Decimal(volume_raw)
        except InvalidOperation:
            raw_amount = None
            errors.append(f"The volume value '{volume_raw}' is not a number.")
        if raw_amount is not None:
            unit = row_l.get("unit", "")
            converted, conv = _convert_generic_volume(raw_amount, unit, line_num)
            if converted is None:
                errors.append(conv)
            else:
                amount = converted
                if conv is not None:
                    conversions.append(conv)
    elif flow_cfs_raw and hours_raw:
        flow_cfs = hours = None
        try:
            flow_cfs = Decimal(flow_cfs_raw)
        except InvalidOperation:
            errors.append(f"The flow_cfs value '{flow_cfs_raw}' is not a number.")
        try:
            hours = Decimal(hours_raw)
        except InvalidOperation:
            errors.append(f"The hours value '{hours_raw}' is not a number.")
        if flow_cfs is not None and hours is not None:
            amount = _cfs_hours_to_af(flow_cfs, hours)
            conversions.append({
                "line": line_num,
                "from": f"{flow_cfs} cfs x {hours} hr",
                "to": "acre-feet",
                "factor": f"{ACRE_FEET_PER_CFS_DAY} acre-feet per cfs-day "
                          f"({ACRE_FEET_PER_CFS_DAY}/24 per cfs-hour)",
                "value": str(amount.quantize(_FOUR_PLACES)),
            })
    else:
        errors.append(
            "This row has no volume. Fill in the acre_feet, af or volume column, "
            "or both the flow_cfs and hours columns."
        )

    returned = Decimal("0")
    returned_raw = row_l.get("returned", "")
    if returned_raw:
        try:
            returned = Decimal(returned_raw)
        except InvalidOperation:
            errors.append(f"The returned value '{returned_raw}' is not a number.")

    max_flow_cfs = None
    if flow_cfs_raw:
        try:
            max_flow_cfs = Decimal(flow_cfs_raw)
        except InvalidOperation:
            max_flow_cfs = None

    if errors:
        return {"line": line_num, "errors": errors}

    point, point_reason = resolve_point(
        row_l, whole_file_point, right_cache=right_cache,
        right_points_cache=right_points_cache,
    )

    return {
        "line": line_num,
        "point": point,
        "point_reason": point_reason,
        "month": month_date,
        "kind": kind,
        "amount_af": amount,
        "returned_af": returned,
        "max_flow_cfs": max_flow_cfs,
        "conversions": conversions,
        "note": None,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# build_rows -- pure (read-only queries for point/right resolution only)
# ---------------------------------------------------------------------------


def build_rows(columns, rows, layout, *, whole_file_point=None, method="",
                data_state="provisional", site_config=None, use_rule=None):
    """Turn raw CSV rows into candidate DiversionRecord field-sets.

    ``use_rule``, when given (146-03 Task 6: chosen on the import screen's
    mapping step), overrides the deployment's remembered
    ``SiteConfig.diversion_use_type_rule`` for this file only; ``None``
    (the default) falls back to the stored value exactly as before.

    Returns a dict: candidates, combined_rows, unresolved_rows, errors,
    conversions, notes, use_rows_present, use_rows_dropped, rule_sentence,
    settings. Writes nothing; ``commit_rows`` below does the dedup check and
    the save.
    """
    site_config = site_config or _default_site_config()
    right_cache = {}
    right_points_cache = {}

    # Every row the FILE types USE, counted off the raw rows before any of
    # them is resolved to a point. The import screen's own USE question is
    # shown on this count, and a row whose point is not yet chosen still
    # means the file has USE rows in it (146-03 Task 6; the first version
    # counted only rows that had already reached a point, so the question
    # stayed hidden on the first render of exactly the file it is about).
    use_rows_present = 0
    if layout == "state":
        for raw_row in rows:
            if _lower_row(raw_row).get("diversion_type", "").strip().upper() == "USE":
                use_rows_present += 1

    errors = []
    unresolved = []
    conversions = []
    notes = []
    use_rows_dropped = 0
    groups = {}       # (point.pk, month, kind) -> group dict
    use_groups = {}    # (point.pk, month) -> group dict

    for line_num, row in enumerate(rows, start=2):
        if layout == "state":
            entry = _process_state_row(
                line_num, row, whole_file_point=whole_file_point,
                right_cache=right_cache, right_points_cache=right_points_cache,
                site_config=site_config,
            )
        else:
            entry = _process_book_row(
                line_num, row, whole_file_point=whole_file_point,
                right_cache=right_cache, right_points_cache=right_points_cache,
            )

        if entry.get("errors"):
            errors.append({"line": line_num, "message": " ".join(entry["errors"])})
            continue

        conversions.extend(entry["conversions"])
        if entry["note"]:
            notes.append({"line": line_num, "note": entry["note"]})

        if entry["point"] is None:
            unresolved.append({"line": line_num, "reason": entry["point_reason"]})
            continue

        point = entry["point"]
        month = entry["month"]
        kind = entry["kind"]

        if kind == "use":
            g = use_groups.setdefault(
                (point.pk, month),
                {"point": point, "month": month, "amount": Decimal("0"), "lines": []},
            )
            g["amount"] += entry["amount_af"]
            g["lines"].append(line_num)
            continue

        g = groups.setdefault(
            (point.pk, month, kind),
            {
                "point": point, "month": month, "kind": kind,
                "amount": Decimal("0"), "returned": Decimal("0"),
                "lines": [], "max_flow": None,
            },
        )
        g["amount"] += entry["amount_af"]
        g["returned"] += entry["returned_af"]
        g["lines"].append(line_num)
        if entry["max_flow_cfs"] is not None:
            g["max_flow"] = (
                entry["max_flow_cfs"] if g["max_flow"] is None
                else max(g["max_flow"], entry["max_flow_cfs"])
            )

    # The USE rule (J3): drop, returned, or as_direct. An explicit `use_rule`
    # (146-03 Task 6: the import screen's own question) overrides the
    # deployment's remembered default on SiteConfig.
    applied_use_rule = use_rule if use_rule is not None else site_config.diversion_use_type_rule
    for (pt_pk, month), use_group in use_groups.items():
        if applied_use_rule == "drop":
            use_rows_dropped += len(use_group["lines"])
            continue
        if applied_use_rule == "as_direct":
            g = groups.setdefault(
                (pt_pk, month, "direct_use"),
                {
                    "point": use_group["point"], "month": month, "kind": "direct_use",
                    "amount": Decimal("0"), "returned": Decimal("0"),
                    "lines": [], "max_flow": None,
                },
            )
            g["amount"] += use_group["amount"]
            g["lines"].extend(use_group["lines"])
            continue
        # returned: USE minus DIRECT (floored at zero, capped at the diverted
        # volume) becomes returned_af on the matching direct_use record.
        direct_key = (pt_pk, month, "direct_use")
        if direct_key not in groups:
            errors.append({
                "line": use_group["lines"][0],
                "message": (
                    f"{use_group['point']} has a USE row for {month:%Y-%m} and no "
                    "DIRECT row, so OpenH2O cannot calculate the water returned "
                    "to the stream."
                ),
            })
            continue
        direct_group = groups[direct_key]
        delta = use_group["amount"] - direct_group["amount"]
        returned_amount = max(delta, Decimal("0"))
        returned_amount = min(returned_amount, direct_group["amount"])
        direct_group["returned"] += returned_amount
        direct_group["lines"].extend(use_group["lines"])

    combined_rows = []
    candidates = []
    total_af = Decimal("0")
    for (_pt_pk, month, kind), g in groups.items():
        if len(g["lines"]) > 1:
            combined_rows.append({
                "point": str(g["point"]),
                "month": f"{month:%Y-%m}",
                "diversion_type": kind,
                "row_count": len(g["lines"]),
                "rows": sorted(g["lines"]),
            })
        volume = g["amount"].quantize(_FOUR_PLACES)
        total_af += volume
        candidates.append({
            "point": g["point"],
            "month": month,
            "diversion_type": kind,
            "volume_acre_feet": volume,
            "returned_af": g["returned"].quantize(_FOUR_PLACES),
            "max_flow_rate_cfs": g["max_flow"],
            "source_lines": sorted(g["lines"]),
        })

    return {
        "candidates": candidates,
        "total_af": total_af.quantize(_FOUR_PLACES),
        "combined_rows": combined_rows,
        "unresolved_rows": unresolved,
        "errors": errors,
        "conversions": conversions,
        "notes": notes,
        "use_rows_present": use_rows_present,
        "use_rows_dropped": use_rows_dropped,
        "rule_sentence": rule_sentence(site_config),
        "settings": {
            "method": method,
            "data_state": data_state,
            "diversion_use_type_rule": applied_use_rule,
            "diversion_report_year_rule": site_config.diversion_report_year_rule,
            "season_start_month": site_config.season_start_month,
        },
    }


# ---------------------------------------------------------------------------
# commit_rows -- dedup, validate, save
# ---------------------------------------------------------------------------


def commit_rows(built, *, method="", data_state="provisional", dry_run=False):
    """Dedup against the database, validate, and (unless dry_run) save.

    Dedup is skip-and-count, never overwrite (146-03 Task 4's own rule): a
    candidate whose (point, month, diversion_type) already exists is skipped.
    Validation runs in both modes, so a dry-run preview shows the same
    errors a real commit would refuse -- only the ``.save()`` is skipped.
    """
    candidates = built["candidates"]
    errors = list(built["errors"])
    skipped_duplicates = 0

    point_ids = {c["point"].pk for c in candidates}
    existing = set()
    if point_ids:
        # An estimate (149-02) is not a person's record: a file's volume for
        # that month replaces it, so it never counts as a duplicate.
        existing = set(
            DiversionRecord.objects.filter(point_of_diversion_id__in=point_ids)
            .exclude(method="estimated_from_use")
            .values_list("point_of_diversion_id", "month", "diversion_type")
        )

    # A month inside a finalized water year is refused as a row error in
    # plain words (147-02), in the preview as well as on commit, so the
    # preview never counts a row the commit would refuse. The database lock
    # (accounting/locks.py) refuses the same rows anyway.
    finalized_spans = list(
        ReportingPeriod.objects.filter(is_finalized=True).values_list(
            "start_date", "end_date", "name"
        )
    )

    survivors = []
    for c in candidates:
        key = (c["point"].pk, c["month"], c["diversion_type"])
        if key in existing:
            skipped_duplicates += 1
            continue
        locked = next(
            (n for (start, end, n) in finalized_spans if start <= c["month"] <= end),
            None,
        )
        if locked:
            errors.append({
                "line": ", ".join(str(n) for n in c["source_lines"]),
                "message": finalized_message(locked),
            })
            continue
        record = DiversionRecord(
            point_of_diversion=c["point"],
            month=c["month"],
            volume_acre_feet=c["volume_acre_feet"],
            returned_af=c["returned_af"],
            max_flow_rate_cfs=c["max_flow_rate_cfs"],
            diversion_type=c["diversion_type"],
            method=method,
            data_state=data_state,
        )
        try:
            record.clean()
        except ValidationError as exc:
            errors.append({
                "line": ", ".join(str(n) for n in c["source_lines"]),
                "message": "; ".join(exc.messages),
            })
            continue
        survivors.append((c, record))

    if dry_run:
        return {
            "created": len(survivors),
            "skipped_duplicates": skipped_duplicates,
            "periods_attached": {},
            "months_created": [],
            "replaced_estimates": [],
            "errors": errors,
        }

    created = 0
    periods_attached = {}
    months_created = set()
    replaced_estimates = set()
    with transaction.atomic():
        for c, record in survivors:
            try:
                with transaction.atomic():
                    period = ReportingPeriod.objects.filter(
                        start_date__lte=c["month"], end_date__gte=c["month"],
                    ).first()
                    record.reporting_period = period
                    # 149-02: a volume a person supplies replaces the estimate
                    # the platform made for that point and month.
                    replaced = discard_estimate(
                        c["point"], c["month"], c["diversion_type"]
                    )
                    if replaced is not None:
                        replaced_estimates.add(f"{replaced:%B %Y}")
                    record.save()
                    created += 1
                    months_created.add(f"{c['month']:%Y-%m}")
                    period_name = period.name if period else "No water year assigned"
                    periods_attached[period_name] = periods_attached.get(period_name, 0) + 1
            except Exception as exc:
                errors.append({
                    "line": ", ".join(str(n) for n in c["source_lines"]),
                    "message": (
                        "An unexpected error stopped OpenH2O from saving this "
                        f"record. Details: {type(exc).__name__}: {exc}"
                    ),
                })

    return {
        "created": created,
        "skipped_duplicates": skipped_duplicates,
        "periods_attached": periods_attached,
        "months_created": sorted(months_created),
        "replaced_estimates": sorted(replaced_estimates),
        "errors": errors,
    }


def _default_site_config():
    """The saved SiteConfig, or an unsaved one carrying only the model's own

    defaults -- read-only use, never .save()d.
    """
    return SiteConfig.objects.first() or SiteConfig()


# ---------------------------------------------------------------------------
# import_diversion_rows -- the one entry point both callers use
# ---------------------------------------------------------------------------


def import_diversion_rows(columns, rows, *, layout=None, whole_file_point=None,
                           method="", data_state="provisional", dry_run=False,
                           site_config=None, use_rule=None):
    """Parse-to-commit in one call: what both the view and the command use.

    ``use_rule``, when given, overrides the deployment's remembered
    ``SiteConfig.diversion_use_type_rule`` for this file only (146-03
    Task 6); ``None`` (the default) uses the stored value, exactly as
    before.

    Returns the full report dict: layout, created, skipped_duplicates,
    combined_rows, unresolved_rows, errors, conversions, notes,
    use_rows_present, use_rows_dropped, rule_sentence, settings,
    periods_attached, dry_run.
    """
    if layout is None:
        layout = recognise_layout(columns)
    site_config = site_config or _default_site_config()

    built = build_rows(
        columns, rows, layout, whole_file_point=whole_file_point,
        method=method, data_state=data_state, site_config=site_config,
        use_rule=use_rule,
    )
    committed = commit_rows(built, method=method, data_state=data_state, dry_run=dry_run)

    return {
        "layout": layout,
        "created": committed["created"],
        "skipped_duplicates": committed["skipped_duplicates"],
        "combined_rows": built["combined_rows"],
        "unresolved_rows": built["unresolved_rows"],
        "errors": committed["errors"],
        "conversions": built["conversions"],
        "notes": built["notes"],
        "use_rows_present": built["use_rows_present"],
        "use_rows_dropped": built["use_rows_dropped"],
        "rule_sentence": built["rule_sentence"],
        "settings": built["settings"],
        "periods_attached": committed["periods_attached"],
        "months_created": committed["months_created"],
        "replaced_estimates": committed["replaced_estimates"],
        "total_af": built["total_af"],
        "dry_run": dry_run,
    }
