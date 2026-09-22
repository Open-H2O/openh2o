# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Production-by-month bulk import (146-04 Task 2, D7, ISS-184).

Mirrors ``surface/diversion_import.py``'s shape, which itself mirrors
``accounting/ledger_import.py``: one service, two callers (the web upload and
the management command), every coercion counted and named. Two real-world
layouts, recognised by header:

* **The state's eAR export** -- one row per PWSID, Year, Month, TypeCode
  (``GW``, ``SW``, ``Purchased``, ``Sold``, ``Recycled``, ``NonPotable``,
  ``NonPotableSold``), Units of Measure As Reported (``G``, ``MG``, ``AF``,
  ``CCF``, or blank), Quantity as in Units Reported. ``NonPotableSold`` has
  no column on this product's model -- it is the state's seventh code and
  this product tracks six -- so a row typed that way is a row error naming
  it, never silently dropped or folded into ``NonPotable``. A blank unit is
  a row error until the mapping step's "unit for blank rows" is set.
* **The operator's monthly log** -- the Small Water System eAR template's own
  Section 5 layout: a ``Date/Month`` column carrying the twelve month names,
  plus ``Maximum Day``, ``Annual Total`` and ``Percent Treated`` rows, none of
  them a month and each skipped and named rather than misread as a
  thirteenth month. One column per source ("Water Produced from Groundwater
  (Wells)", "...Surface Water", "Finished Water Purchased...", "Water Sold
  to Another PWS", "Non-potable...", "Recycled"); "Total Amount of Potable
  Water" is a computed total on the printed form, never a source, and is
  never read as one. The file carries no PWSID, no year and no per-row unit
  -- the report year and the whole-file unit (default gallons) are the
  mapping step's own questions.

Conversions: 1,000,000 gallons per MG, 748.05 gallons per CCF, 325,851
gallons per acre-foot -- the same figures ``drinking.models.SystemProduction``
computes at save, and the same figures ``surface/diversion_import.py`` carries
for its own domain (module independence means the constant is restated, not
shared -- see ``drinking/models.py``'s comment on this).

Dedup: a candidate whose (system, year, month, type_code, facility) already
exists is skipped and counted, never overwritten -- re-importing the same
file writes nothing the second time. Repeated keys WITHIN one file (the eAR's
own M9: a key can repeat up to five times, always as an exact copy) are
collapsed the same way, counted separately as ``duplicate_rows_in_file``.
"""
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from drinking.models import PRODUCTION_UNIT_CHOICES, SystemProduction

MAX_ROWS = 2000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB, the ceiling every importer here uses

_UNIT_CODES = {code for code, _label in PRODUCTION_UNIT_CHOICES}

#: The eAR's own TypeCode -> this product's type_code. NonPotableSold is
#: deliberately absent: it is the state's seventh code and this product
#: tracks six, so a row typed that way is a row error, not a silent drop.
_EAR_TYPE_MAP = {
    "GW": "GW",
    "SW": "SW",
    "Purchased": "PU",
    "Sold": "SO",
    "Recycled": "RC",
    "NonPotable": "NP",
}

#: The operator log's own column headers -> this product's type_code.
#: "Total Amount of Potable Water" is a computed total on the printed form
#: (groundwater plus surface plus purchased) and is deliberately absent --
#: reading it as a source would double the GW/SW/PU figures it already sums.
_OPERATOR_SOURCE_COLUMNS = {
    "Water Produced from Groundwater (Wells)": "GW",
    "Water Produced from Surface Water": "SW",
    "Finished Water Purchased or Received from another PWS": "PU",
    "Water Sold to Another PWS": "SO",
    "Non-potable (exclude recycled)": "NP",
    "Recycled": "RC",
}

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

#: Headers that mark a file as the state's eAR layout. Presence of all five,
#: in any column order, is what recognise_layout keys on.
_EAR_REQUIRED = {"PWSID", "Year", "Month", "TypeCode", "Quantity as in Units Reported"}


# ---------------------------------------------------------------------------
# parse_csv / recognise_layout
# ---------------------------------------------------------------------------


def parse_csv(file_obj, filename=""):
    """Parse an uploaded (or opened) CSV into (columns, rows).

    ``rows`` is a list of raw string dicts, exactly as the file wrote them --
    layout recognition and coercion happen later. Raises ImportError on a
    non-CSV extension, an oversized file, no headers, no data rows, or more
    rows than MAX_ROWS.
    """
    name = (filename or "").lower()
    if name and not name.endswith(".csv"):
        raise ImportError("Production import accepts CSV only.")

    size = getattr(file_obj, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(
            f"File is too large ({size // (1024 * 1024)} MB); the upload cap "
            f"is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    if not columns:
        raise ImportError("CSV file appears empty or has no headers.")
    rows = [{k: ("" if v is None else v) for k, v in row.items() if k is not None} for row in reader]
    if not rows:
        raise ImportError("CSV file has headers but no data rows.")
    if len(rows) > MAX_ROWS:
        raise ImportError(
            f"Import is {len(rows)} rows, over the {MAX_ROWS}-row cap. "
            "Re-upload a smaller file."
        )
    return columns, rows


def recognise_layout(columns):
    """'ear' or 'operator_log', by header alone.

    Raises ImportError naming the headers seen when neither is recognised --
    never a silent guess.
    """
    present = {c.strip() for c in columns if c}
    if _EAR_REQUIRED <= present:
        return "ear"

    if "Date/Month" in present and any(col in present for col in _OPERATOR_SOURCE_COLUMNS):
        return "operator_log"

    raise ImportError(
        "Unrecognised file layout; headers seen: " + ", ".join(columns)
    )


# ---------------------------------------------------------------------------
# Row processors -- pure, no queries, no writes
# ---------------------------------------------------------------------------


def _process_ear_row(line_num, row, *, system, unit_for_blank):
    errors = []

    pwsid = (row.get("PWSID") or "").strip().upper()
    if not pwsid:
        errors.append("missing PWSID")
    elif pwsid != system.pwsid.strip().upper():
        errors.append(
            f"PWSID {pwsid!r} does not match this deployment's system "
            f"({system.pwsid})"
        )

    year = None
    year_raw = (row.get("Year") or "").strip()
    if not year_raw:
        errors.append("missing Year")
    else:
        try:
            year = int(year_raw)
        except ValueError:
            errors.append(f"invalid Year: {year_raw!r}")

    month_raw = (row.get("Month") or "").strip().lower()
    month_num = _MONTH_NAMES.get(month_raw)
    if month_num is None:
        # Fall back to DateStartOfMonth (M/D/YYYY, the eAR's own date column)
        # -- the same order of precedence the state's own file would need if
        # its Month column were ever absent or unreadable.
        date_raw = (row.get("DateStartOfMonth") or "").strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                month_num = datetime.strptime(date_raw, fmt).month
                break
            except ValueError:
                continue
        if month_num is None:
            errors.append(
                f"unreadable Month/DateStartOfMonth: {month_raw!r} / {date_raw!r}"
            )

    type_raw = (row.get("TypeCode") or "").strip()
    type_code = _EAR_TYPE_MAP.get(type_raw)
    if type_code is None:
        errors.append(
            f"TypeCode {type_raw!r} is not one of the six this product "
            "tracks (GW, SW, Purchased, Sold, Recycled, NonPotable)"
        )

    unit_raw = (row.get("Units of Measure As Reported") or "").strip().upper()
    unit = None
    if not unit_raw:
        if unit_for_blank:
            unit = unit_for_blank
        else:
            errors.append(
                "Units of Measure As Reported is blank; choose the unit for "
                "blank rows in the mapping step below"
            )
    elif unit_raw in _UNIT_CODES:
        unit = unit_raw
    else:
        errors.append(f"unrecognised unit: {unit_raw!r}")

    volume = None
    qty_raw = (row.get("Quantity as in Units Reported") or "").strip()
    if not qty_raw:
        errors.append("missing Quantity as in Units Reported")
    else:
        try:
            volume = Decimal(qty_raw.replace(",", ""))
        except InvalidOperation:
            errors.append(f"invalid Quantity as in Units Reported: {qty_raw!r}")

    if errors:
        return {"line": line_num, "errors": errors}

    return {
        "line": line_num,
        "year": year,
        "month": month_num,
        "type_code": type_code,
        "unit": unit,
        "volume": volume,
        "errors": [],
    }


def _process_operator_log_row(line_num, row, *, year, unit):
    label = (row.get("Date/Month") or "").strip()
    month_num = _MONTH_NAMES.get(label.lower())
    if month_num is None:
        # "Maximum Day", "Annual Total", "Percent Treated" -- none of them a
        # month. Skipped and named, never guessed at as a thirteenth month.
        return {"line": line_num, "skipped": label or "(blank)"}

    entries = []
    errors = []
    for column, type_code in _OPERATOR_SOURCE_COLUMNS.items():
        raw = row.get(column)
        if raw is None:
            continue
        raw = raw.strip()
        if raw == "":
            continue
        try:
            volume = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            errors.append(f"invalid {column}: {raw!r}")
            continue
        entries.append(
            {
                "year": year,
                "month": month_num,
                "type_code": type_code,
                "unit": unit,
                "volume": volume,
            }
        )

    return {"line": line_num, "entries": entries, "errors": errors}


# ---------------------------------------------------------------------------
# build_rows -- pure (no writes); commit_rows -- dedup, save
# ---------------------------------------------------------------------------


def build_rows(columns, rows, layout, *, system, unit_for_blank=None,
                operator_year=None, operator_unit="G"):
    """Turn raw CSV rows into candidate SystemProduction field-sets.

    Returns a dict: candidates, skipped_rows, duplicate_rows_in_file, errors.
    Writes nothing -- ``commit_rows`` below does the dedup check and the
    save. ``candidates`` carries plain dicts keyed the same way the model's
    own fields are named, so ``commit_rows`` needs no second mapping.
    """
    errors = []
    skipped_rows = []
    candidates_by_key = {}
    duplicate_rows_in_file = 0

    if layout == "ear":
        for line_num, row in enumerate(rows, start=2):
            entry = _process_ear_row(line_num, row, system=system, unit_for_blank=unit_for_blank)
            if entry.get("errors"):
                errors.append({"line": line_num, "message": "; ".join(entry["errors"])})
                continue
            key = (entry["year"], entry["month"], entry["type_code"])
            if key in candidates_by_key:
                # M9: repeated eAR keys are exact duplicates within the file
                # itself -- collapsed and counted, the first occurrence kept.
                duplicate_rows_in_file += 1
                continue
            candidates_by_key[key] = {
                "year": entry["year"],
                "month": entry["month"],
                "type_code": entry["type_code"],
                "unit_as_reported": entry["unit"],
                "volume_as_reported": entry["volume"],
                "source_lines": [line_num],
            }
    else:
        if operator_year is None:
            errors.append(
                {"line": 1, "message": "The operator's log carries no year; "
                 "choose the report year in the mapping step below."}
            )
        else:
            for line_num, row in enumerate(rows, start=2):
                entry = _process_operator_log_row(
                    line_num, row, year=operator_year, unit=operator_unit
                )
                if "skipped" in entry:
                    skipped_rows.append({"line": line_num, "label": entry["skipped"]})
                    continue
                if entry["errors"]:
                    errors.append(
                        {"line": line_num, "message": "; ".join(entry["errors"])}
                    )
                    continue
                for item in entry["entries"]:
                    key = (item["year"], item["month"], item["type_code"])
                    if key in candidates_by_key:
                        duplicate_rows_in_file += 1
                        continue
                    candidates_by_key[key] = {
                        "year": item["year"],
                        "month": item["month"],
                        "type_code": item["type_code"],
                        "unit_as_reported": item["unit"],
                        "volume_as_reported": item["volume"],
                        "source_lines": [line_num],
                    }

    # Annual-in-January (the model's own field): a January row for a
    # (year, type_code) that has no other month present in THIS FILE at all
    # stands for the whole year, not one month of it.
    months_present = {}
    for key in candidates_by_key:
        year, month, type_code = key
        months_present.setdefault((year, type_code), set()).add(month)
    for key, candidate in candidates_by_key.items():
        year, month, type_code = key
        if month == 1 and months_present.get((year, type_code)) == {1}:
            candidate["annual_in_january"] = True
        else:
            candidate["annual_in_january"] = False

    return {
        "candidates": list(candidates_by_key.values()),
        "skipped_rows": skipped_rows,
        "duplicate_rows_in_file": duplicate_rows_in_file,
        "errors": errors,
    }


def commit_rows(built, *, system, provenance, dry_run=False):
    """Dedup against the database, and (unless dry_run) save.

    Dedup is skip-and-count, never overwrite: a candidate whose
    (system, year, month, type_code, facility) already exists is skipped.
    ``facility`` is always None in this task -- neither layout names one.
    """
    candidates = built["candidates"]
    errors = list(built["errors"])
    skipped_duplicates = 0

    existing = set(
        SystemProduction.objects.filter(system=system).values_list(
            "year", "month", "type_code", "facility_id"
        )
    )

    survivors = []
    for c in candidates:
        key = (c["year"], c["month"], c["type_code"], None)
        if key in existing:
            skipped_duplicates += 1
            continue
        survivors.append(c)

    if dry_run:
        return {
            "created": len(survivors),
            "skipped_duplicates": skipped_duplicates,
            "errors": errors,
        }

    created = 0
    with transaction.atomic():
        for c in survivors:
            try:
                with transaction.atomic():
                    SystemProduction.objects.create(
                        system=system,
                        year=c["year"],
                        month=c["month"],
                        type_code=c["type_code"],
                        facility=None,
                        volume_as_reported=c["volume_as_reported"],
                        unit_as_reported=c["unit_as_reported"],
                        provenance=provenance,
                        annual_in_january=c.get("annual_in_january", False),
                    )
                    created += 1
            except Exception as exc:
                errors.append({
                    "line": ", ".join(str(n) for n in c["source_lines"]),
                    "message": f"{type(exc).__name__}: {exc}",
                })

    return {
        "created": created,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
    }


def import_production_rows(columns, rows, *, system, layout=None,
                            unit_for_blank=None, operator_year=None,
                            operator_unit="G", dry_run=False):
    """Parse-to-commit in one call: what both the view and the command use.

    Returns the full report dict: layout, created, skipped_duplicates,
    skipped_rows, duplicate_rows_in_file, errors, dry_run.
    """
    if layout is None:
        layout = recognise_layout(columns)

    provenance = "ear_export" if layout == "ear" else "operator_log"

    built = build_rows(
        columns, rows, layout, system=system, unit_for_blank=unit_for_blank,
        operator_year=operator_year, operator_unit=operator_unit,
    )
    committed = commit_rows(built, system=system, provenance=provenance, dry_run=dry_run)

    return {
        "layout": layout,
        "created": committed["created"],
        "skipped_duplicates": committed["skipped_duplicates"],
        "skipped_rows": built["skipped_rows"],
        "duplicate_rows_in_file": built["duplicate_rows_in_file"],
        "errors": committed["errors"],
        "dry_run": dry_run,
    }
