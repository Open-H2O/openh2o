# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Water rights bulk import engine.

Mirrors the parse-preview-commit shape ``infrastructure/importer.py`` already
established (read that module first): a pure parse step, a best-guess column
mapping, a per-row validate step that returns writer-ready ``data`` plus
``errors``/``warnings``, and a single-transaction commit with a per-row
savepoint. It is its own module rather than a branch of
``infrastructure.importer`` because a water right's source is always the
state's own **rights LIST export** (a fixed, named header:
``APPLICATION_NUMBER``, ``WATER_RIGHT_TYPE``, ``FACE_VALUE_UNITS``...), never
an operator's arbitrary column names, and the validation is domain-specific
(a unit column that must read one exact value, a type name matched against
the seeded ``WaterRightType`` rows, two date formats) rather than the
generic numeric/geometry coercion the infrastructure engine does. CSV only:
the state does not publish this list as GeoJSON/shapefile/KML, so there is no
shared geometry parsing to reuse.

Four functions the views are thin glue over, matching the infrastructure
engine's own names so a reader who knows one door reads the other for free:

  parse_upload(file, filename)      -> {"columns": [...], "rows": [...]}
  auto_map_columns(columns)         -> {model_field: source_column}
  validate_rows(rows, mapping, existing_right_ids)
                                      -> [{index, data, errors, warnings}]
  commit_rows(valid_results)        -> int (number created)
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from surface.models import WaterRight, WaterRightType

MAX_ROWS = 500
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB, same ceiling as the infrastructure importer

#: The state's own rights-LIST unit values. A face value or a maximum rate in
#: any other unit is left out of the right, with a note naming the unit found.
#: This importer never converts a unit.
FACE_VALUE_UNITS_EXPECTED = "Acre-feet per Year"
MAX_DD_UNITS_EXPECTED = "Cubic Feet per Second"

#: The whole-file messages for both surface water imports
#: diversion_import.py
#: imports these so the two pages say the same thing for the same fault.
NO_FILE_MESSAGE = "Choose a CSV file to upload."
NOT_CSV_MESSAGE = (
    "This page imports CSV files only. Save the file as CSV and upload it again."
)
NO_COLUMNS_MESSAGE = "This file has no column names on its first line."
NO_ROWS_MESSAGE = "This file has column names but no rows below them."
ROWS_NOT_RECEIVED_MESSAGE = (
    "OpenH2O did not receive the file's rows from the preview. "
    "Upload the file again."
)


def too_large_message(size, cap):
    """The size is rounded UP, so a file over the cap never reads as equal to it."""
    mb = 1024 * 1024
    return (
        f"This file is {math.ceil(size / mb)} MB. "
        f"OpenH2O imports files of up to {cap // mb} MB."
    )


def unexpected_error_message(exc):
    return (
        "An unexpected error stopped the import, and OpenH2O saved nothing "
        f"from this file. Details: {type(exc).__name__}: {exc}"
    )


def row_cap_message(row_count):
    return (
        f"This file has {row_count:,} rows, and OpenH2O imports up to "
        f"{MAX_ROWS:,} rows from one file. Split the file and import each part."
    )


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


def parse_upload(file, filename):
    """Parse an uploaded CSV into {"columns": [...], "rows": [dict, ...]}.

    Raises ImportError on: a non-CSV extension, no rows, or > MAX_ROWS rows.
    Same shape ``infrastructure.importer.parse_upload`` raises, so the view
    layer's error handling is identical.
    """
    name = (filename or "").lower()
    if not name.endswith(".csv"):
        raise ImportError(NOT_CSV_MESSAGE)

    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(too_large_message(size, MAX_UPLOAD_BYTES))

    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")  # tolerate a BOM from Excel exports
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    rows = [{k: ("" if v is None else v) for k, v in row.items()} for row in reader]

    if not columns:
        raise ImportError(NO_COLUMNS_MESSAGE)
    if not rows:
        raise ImportError(NO_ROWS_MESSAGE)
    if len(rows) > MAX_ROWS:
        raise ImportError(row_cap_message(len(rows)))

    return {"columns": columns, "rows": rows}


# ---------------------------------------------------------------------------
# auto_map_columns
# ---------------------------------------------------------------------------

#: model field -> the state rights-LIST header name(s) that carry it (read
#: 2026-09-20 off the shape-1 dataset). ``right_type_name`` and the two unit
#: columns are not model fields on their own: they steer ``right_type`` and
#: validate the two numeric columns beside them. They still get a mapping
#: row so the operator can see (and, if the state ever renames a header,
#: correct) which column each check reads.
RIGHT_FIELD_ALIASES = {
    "right_id": {"APPLICATION_NUMBER"},
    "right_type_name": {"WATER_RIGHT_TYPE"},
    "state_status": {"WATER_RIGHT_STATUS"},
    "holder_name": {"PRIMARY_OWNER_NAME"},
    "source_name": {"SOURCE_NAME"},
    "watershed": {"WATERSHED"},
    "face_value_acre_feet": {"FACE_VALUE_AMOUNT"},
    "face_value_units": {"FACE_VALUE_UNITS"},
    "max_rate_cfs": {"MAX_DD_APPL"},
    "max_rate_units": {"MAX_DD_UNITS"},
    "priority_date": {"PRIORITY_DATE"},
    "license_number": {"LICENSE_ID"},
    "permit_number": {"PERMIT_ID"},
    "purpose_of_use": {"USE_CODE"},
    "net_acreage": {"USE_NET_ACREAGE"},
    "direct_season_start_month": {"DIRECT_SEASON_START_MONTH_1"},
    "direct_season_start_day": {"DIRECT_DIV_SEASON_START_DAY_1"},
    "direct_season_end_month": {"DIRECT_DIV_SEASON_END_MONTH_1"},
    "direct_season_end_day": {"DIRECT_DIV_SEASON_END_DAY_1"},
    "storage_season_start_month": {"STORAGE_SEASON_START_MONTH_1"},
    "storage_season_start_day": {"STORAGE_SEASON_START_DAY_1"},
    "storage_season_end_month": {"STORAGE_SEASON_END_MONTH_1"},
    "storage_season_end_day": {"STORAGE_SEASON_END_DAY_1"},
}

#: Sentence case, no parentheses.
FIELD_LABELS = {
    "right_id": "Application number",
    "right_type_name": "Right type",
    "state_status": "Status in eWRIMS",
    "holder_name": "Holder",
    "source_name": "Source",
    "watershed": "Watershed",
    "face_value_acre_feet": "Face value in acre-feet per year",
    "face_value_units": "Face value unit",
    "max_rate_cfs": "Maximum rate in cfs",
    "max_rate_units": "Maximum rate unit",
    "priority_date": "Priority date",
    "license_number": "License number",
    "permit_number": "Permit number",
    "purpose_of_use": "Purpose of use",
    "net_acreage": "Net acreage",
    "direct_season_start_month": "Direct diversion season start month",
    "direct_season_start_day": "Direct diversion season start day",
    "direct_season_end_month": "Direct diversion season end month",
    "direct_season_end_day": "Direct diversion season end day",
    "storage_season_start_month": "Storage season start month",
    "storage_season_start_day": "Storage season start day",
    "storage_season_end_month": "Storage season end month",
    "storage_season_end_day": "Storage season end day",
}

# The keys ``validate_rows`` actually puts in a row's ``data`` dict that are
# real ``WaterRight`` fields, eligible for ``WaterRight.objects.create(**data)``.
# Note: ``right_type`` (the resolved FK), not ``right_type_name`` (the mapping
# key that steers it) -- and the two unit fields never appear here at all,
# since they are validated but never written to the model.
_MODEL_FIELDS = {
    "right_id", "right_type", "state_status", "holder_name",
    "source_name", "watershed", "face_value_acre_feet", "max_rate_cfs",
    "priority_date", "license_number", "permit_number", "purpose_of_use",
    "net_acreage", "direct_season_start_month", "direct_season_start_day",
    "direct_season_end_month", "direct_season_end_day",
    "storage_season_start_month", "storage_season_start_day",
    "storage_season_end_month", "storage_season_end_day",
}

_INT_FIELDS = {
    "direct_season_start_month", "direct_season_start_day",
    "direct_season_end_month", "direct_season_end_day",
    "storage_season_start_month", "storage_season_start_day",
    "storage_season_end_month", "storage_season_end_day",
}


def import_fields():
    """Ordered [(field, label)] the mapping UI offers a column for."""
    return [(field, FIELD_LABELS[field]) for field in RIGHT_FIELD_ALIASES]


def _normalize(col):
    return col.strip().upper()


def auto_map_columns(columns):
    """Best-effort {field: source_column} guess against the state's own
    LIST header names: an exact, case-insensitive match, since these are a
    fixed export format, not free-form operator column names. The mapping
    step still lets the operator override any guess (or a state header
    rename in a future export year)."""
    norm_to_source = {}
    for col in columns:
        norm_to_source.setdefault(_normalize(col), col)

    mapping = {}
    for field, aliases in RIGHT_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in norm_to_source:
                mapping[field] = norm_to_source[alias]
                break
    return mapping


# ---------------------------------------------------------------------------
# validate_rows
# ---------------------------------------------------------------------------

#: A handful of eWRIMS LIST spellings that carry no pre-/post-1914 qualifier
#: even though the seeded ``WaterRightType`` rows are split that way (no new
#: type rows are added for this door, see the plan's own ruling). Mapped
#: case-insensitively AFTER an exact-name match fails. "Appropriative" alone
#: maps to the post-1914 (permitted) row because the state's permit and
#: license system exists only for post-1914 rights: a pre-1914 claim
#: predates that system and is never issued a PERMIT_ID or a LICENSE_ID; this
#: is a data-crosswalk judgment call (no pre-1914 sample seen yet in the
#: shape-1 dataset), flagged in the evidence file and ISSUES.md for review
#: against a real pre-1914 export row.
_BARE_TYPE_ALIASES = {
    "appropriative": "Post-1914 Appropriative",
    "federally reserved": "Federal Reserved",
    "statutory": "Statutory Small Domestic",
    "statutory registration": "Statutory Small Domestic",
}


def _column(mapping, field):
    """The file column a message names for ``field``: the one the person
    matched, else the state's own header."""
    return mapping.get(field) or sorted(RIGHT_FIELD_ALIASES[field])[0]


def _resolve_right_type(raw_value, type_by_name):
    """The WaterRightType for ``raw_value``, or the name to add on commit.

    Returns ``(type_or_None, new_name_or_None)``. A type the seeded rows do
    not carry is no longer an error (only "Appropriative" used to
    import, 29,755 of the 84,833 rows of the state's list): ``commit_rows`` adds it the first time a file carries it,
    named as eWRIMS writes it. No calculation reads a right's type.
    """
    key = raw_value.strip().lower()
    match = type_by_name.get(key)
    if match is None:
        alias = _BARE_TYPE_ALIASES.get(key)
        if alias:
            match = type_by_name.get(alias.lower())
    if match is None:
        return None, raw_value.strip()
    return match, None


def _parse_priority_date(raw_value, column, errors):
    """ISO (YYYY-MM-DD) or m/d/yyyy (crosswalk M5); blank stays null."""
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw_value, fmt).date()
        except ValueError:
            continue
    errors.append(
        f"{column} '{raw_value}' is not a date written YYYY-MM-DD or M/D/YYYY."
    )
    return None


def validate_rows(rows, mapping, existing_right_ids):
    """Validate + coerce a batch into writer-ready `data` dicts.

    Returns a list of {index, data, errors, warnings}, the same shape
    ``infrastructure.importer.validate_rows`` returns. A row with any errors
    is skipped by ``commit_rows``; a row with only warnings is created, and
    its warnings are listed under "Imported with a note". Dedup on
    ``right_id`` is enforced here (against both the database and earlier rows
    in this same file) so a second import of the same file, or a file with an
    internal repeat, is a named skip rather than a silent overwrite. This
    importer never updates an existing right.
    """
    type_by_name = {t.name.lower(): t for t in WaterRightType.objects.all()}
    existing = {r for r in (existing_right_ids or set())}
    seen_in_batch: set[str] = set()

    return [
        _validate_row(index, row, mapping, type_by_name, existing, seen_in_batch)
        for index, row in enumerate(rows)
    ]


def _src(row: dict[str, Any], mapping: dict[str, str], field: str) -> str:
    """The row's stripped value for ``field`` through the column mapping, or "" when unmapped or blank."""
    col = mapping.get(field)
    if not col:
        return ""
    return (row.get(col) or "").strip()


def _blank(errors: list[str], mapping: dict[str, str], field: str) -> None:
    """Add the "blank or not matched to a column" error for ``field``."""
    errors.append(f"{_column(mapping, field)} is blank or not matched to a column.")


def _validate_row(
    index: int,
    row: dict[str, Any],
    mapping: dict[str, str],
    type_by_name: dict[str, WaterRightType],
    existing: set[str],
    seen_in_batch: set[str],
) -> dict[str, Any]:
    """Validate one row into {index, data, errors, warnings}."""
    errors: list[str] = []
    warnings: list[str] = []
    data: dict[str, Any] = {}

    _read_identity(row, mapping, type_by_name, existing, seen_in_batch, data, errors)
    _read_quantities(row, mapping, data, errors, warnings)

    return {"index": index, "data": data, "errors": errors, "warnings": warnings}


def _read_identity(
    row: dict[str, Any],
    mapping: dict[str, str],
    type_by_name: dict[str, WaterRightType],
    existing: set[str],
    seen_in_batch: set[str],
    data: dict[str, Any],
    errors: list[str],
) -> None:
    """Read the right id (deduped), type, holder and plain text fields into ``data``."""
    right_id = _src(row, mapping, "right_id")
    if not right_id:
        _blank(errors, mapping, "right_id")
    elif right_id in existing:
        errors.append(
            f"Water right {right_id} is already on file. OpenH2O does not "
            "overwrite a water right on import."
        )
    elif right_id in seen_in_batch:
        errors.append(f"Water right {right_id} appears earlier in this file.")
    else:
        seen_in_batch.add(right_id)
    data["right_id"] = right_id

    type_raw = _src(row, mapping, "right_type_name")
    if not type_raw:
        _blank(errors, mapping, "right_type_name")
    else:
        right_type, new_type_name = _resolve_right_type(type_raw, type_by_name)
        if right_type is not None:
            data["right_type"] = right_type
        else:
            data["new_right_type_name"] = new_type_name

    holder_name = _src(row, mapping, "holder_name")
    if not holder_name:
        _blank(errors, mapping, "holder_name")
    data["holder_name"] = holder_name

    for field in ("state_status", "source_name", "watershed", "license_number",
                  "permit_number", "purpose_of_use"):
        val = _src(row, mapping, field)
        if val:
            data[field] = val


def _read_quantities(
    row: dict[str, Any],
    mapping: dict[str, str],
    data: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Read face value, maximum rate, acreage, priority date and whole-number fields into ``data``."""
    # --- face value + its unit ---
    # A face value in another unit leaves the right in, without the face
    # value.
    face_value_raw = _src(row, mapping, "face_value_acre_feet")
    if face_value_raw:
        units = _src(row, mapping, "face_value_units")
        if units and units != FACE_VALUE_UNITS_EXPECTED:
            warnings.append(
                "OpenH2O imported this right without its face value, which "
                f"the file gives in {units}. OpenH2O records a face value in "
                "acre-feet per year."
            )
        else:
            try:
                data["face_value_acre_feet"] = Decimal(face_value_raw)
            except (InvalidOperation, ValueError):
                errors.append(
                    f"{_column(mapping, 'face_value_acre_feet')} "
                    f"'{face_value_raw}' is not a number."
                )

    # --- max rate + its unit --- (message E row 6)
    rate_raw = _src(row, mapping, "max_rate_cfs")
    if rate_raw:
        units = _src(row, mapping, "max_rate_units")
        if units and units != MAX_DD_UNITS_EXPECTED:
            warnings.append(
                "OpenH2O imported this right without its maximum rate, which "
                f"the file gives in {units}. OpenH2O records a maximum rate in "
                "cubic feet per second."
            )
        else:
            try:
                data["max_rate_cfs"] = Decimal(rate_raw)
            except (InvalidOperation, ValueError):
                errors.append(
                    f"{_column(mapping, 'max_rate_cfs')} '{rate_raw}' is not a number."
                )

    net_acreage_raw = _src(row, mapping, "net_acreage")
    if net_acreage_raw:
        try:
            data["net_acreage"] = Decimal(net_acreage_raw)
        except (InvalidOperation, ValueError):
            errors.append(
                f"{_column(mapping, 'net_acreage')} '{net_acreage_raw}' is not a number."
            )

    data["priority_date"] = _parse_priority_date(
        _src(row, mapping, "priority_date"), _column(mapping, "priority_date"), errors
    )

    for field in _INT_FIELDS:
        val = _src(row, mapping, field)
        if val:
            try:
                data[field] = int(Decimal(val))
            except (InvalidOperation, ValueError):
                errors.append(f"{_column(mapping, field)} '{val}' is not a number.")


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


def _type_code_for(name):
    """A unique WaterRightType.code (max 20) for a type added from a file."""
    base = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:20] or "TYPE"
    code, n = base, 2
    while WaterRightType.objects.filter(code=code).exists():
        suffix = f"_{n}"
        code = base[: 20 - len(suffix)] + suffix
        n += 1
    return code


def _right_type_named(name):
    """The type named ``name`` (case-insensitive), added if none exists."""
    existing = WaterRightType.objects.filter(name__iexact=name).first()
    if existing is not None:
        return existing
    return WaterRightType.objects.create(
        name=name[:100], code=_type_code_for(name)
    )


def commit_rows(valid_results):
    """Create a WaterRight from the coerced `data` of every error-free row.

    One outer transaction with a per-row savepoint, the same shape
    ``infrastructure.importer.commit_rows`` uses: a single bad row (a unique
    constraint slipping past the dedup check under a race, say) is rolled
    back and reported, never allowed to poison the whole batch. A water right
    type the file names and OpenH2O does not carry yet is added inside the
    row's savepoint, named as the file writes it.
    """
    clean = [r for r in valid_results if not r["errors"]]
    created = 0

    with transaction.atomic():
        for result in clean:
            data = {k: v for k, v in result["data"].items() if k in _MODEL_FIELDS}
            try:
                with transaction.atomic():
                    new_type_name = result["data"].get("new_right_type_name")
                    if new_type_name:
                        data["right_type"] = _right_type_named(new_type_name)
                    WaterRight.objects.create(**data)
                created += 1
            except Exception as exc:
                result["errors"].append(
                    "An unexpected error stopped OpenH2O from saving this water "
                    f"right. Details: {type(exc).__name__}: {exc}"
                )

    return created
