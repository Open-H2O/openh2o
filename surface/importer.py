# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Water rights bulk import engine (146-02 Task 1, door D1).

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
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from surface.models import WaterRight, WaterRightType

MAX_ROWS = 500
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB, same ceiling as the infrastructure importer

#: The state's own rights-LIST unit values. A row carrying a face value or a
#: maximum rate in any other unit is a row error naming the unit found. This
#: importer never converts a unit; it only accepts the one the model assumes.
FACE_VALUE_UNITS_EXPECTED = "Acre-feet per Year"
MAX_DD_UNITS_EXPECTED = "Cubic Feet per Second"


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
        raise ImportError(
            "Water rights import accepts CSV only (the state's own rights "
            "LIST export)."
        )

    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(
            f"File is too large ({size // (1024 * 1024)} MB); the upload cap "
            f"is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")  # tolerate a BOM from Excel exports
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    rows = [{k: ("" if v is None else v) for k, v in row.items()} for row in reader]

    if len(rows) > MAX_ROWS:
        raise ImportError(
            f"File contains {len(rows)} rows, over the {MAX_ROWS}-row import "
            "cap. Please split it into smaller files."
        )
    if not rows:
        raise ImportError("No rows found in the uploaded file.")

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

FIELD_LABELS = {
    "right_id": "Right ID (Application Number)",
    "right_type_name": "Right Type",
    "state_status": "State Status",
    "holder_name": "Holder",
    "source_name": "Source",
    "watershed": "Watershed",
    "face_value_acre_feet": "Face Value (AF)",
    "face_value_units": "Face Value Units",
    "max_rate_cfs": "Max Rate (cfs)",
    "max_rate_units": "Max Rate Units",
    "priority_date": "Priority Date",
    "license_number": "License Number",
    "permit_number": "Permit Number",
    "purpose_of_use": "Purpose of Use",
    "net_acreage": "Net Acreage",
    "direct_season_start_month": "Direct Season Start Month",
    "direct_season_start_day": "Direct Season Start Day",
    "direct_season_end_month": "Direct Season End Month",
    "direct_season_end_day": "Direct Season End Day",
    "storage_season_start_month": "Storage Season Start Month",
    "storage_season_start_day": "Storage Season Start Day",
    "storage_season_end_month": "Storage Season End Month",
    "storage_season_end_day": "Storage Season End Day",
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


def _resolve_right_type(raw_value, type_by_name, errors):
    if not raw_value:
        errors.append("WATER_RIGHT_TYPE is required (blank or unmapped).")
        return None
    key = raw_value.strip().lower()
    match = type_by_name.get(key)
    if match is None:
        alias = _BARE_TYPE_ALIASES.get(key)
        if alias:
            match = type_by_name.get(alias.lower())
    if match is None:
        seeded_names = sorted({t.name for t in type_by_name.values()})
        errors.append(
            f"WATER_RIGHT_TYPE '{raw_value}' matches no seeded water right "
            f"type. Seeded types are: {', '.join(seeded_names)}."
        )
        return None
    return match


def _parse_priority_date(raw_value, errors):
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
        f"PRIORITY_DATE '{raw_value}' is not a recognised date "
        "(expected YYYY-MM-DD or M/D/YYYY)."
    )
    return None


def validate_rows(rows, mapping, existing_right_ids):
    """Validate + coerce a batch into writer-ready `data` dicts.

    Returns a list of {index, data, errors, warnings}, the same shape
    ``infrastructure.importer.validate_rows`` returns. A row with any errors
    is skipped by ``commit_rows``. Dedup on ``right_id`` is enforced here
    (against both the database and earlier rows in this same file) so a
    second import of the same file, or a file with an internal repeat, is a
    named skip rather than a silent overwrite. This importer never updates
    an existing right.
    """
    type_by_name = {t.name.lower(): t for t in WaterRightType.objects.all()}
    existing = {r for r in (existing_right_ids or set())}
    seen_in_batch = set()

    results = []
    for index, row in enumerate(rows):
        errors = []
        warnings = []
        data = {}

        def src(field):
            col = mapping.get(field)
            if not col:
                return ""
            return (row.get(col) or "").strip()

        right_id = src("right_id")
        if not right_id:
            errors.append("APPLICATION_NUMBER is required (blank or unmapped).")
        elif right_id in existing or right_id in seen_in_batch:
            errors.append(
                f"a water right with id '{right_id}' already exists; import "
                "never overwrites, so this row was skipped."
            )
        else:
            seen_in_batch.add(right_id)
        data["right_id"] = right_id

        right_type = _resolve_right_type(src("right_type_name"), type_by_name, errors)
        if right_type is not None:
            data["right_type"] = right_type

        holder_name = src("holder_name")
        if not holder_name:
            errors.append("PRIMARY_OWNER_NAME is required (blank or unmapped).")
        data["holder_name"] = holder_name

        for field in ("state_status", "source_name", "watershed", "license_number",
                      "permit_number", "purpose_of_use"):
            val = src(field)
            if val:
                data[field] = val

        # --- face value + its unit ---
        face_value_raw = src("face_value_acre_feet")
        if face_value_raw:
            units = src("face_value_units")
            if units and units != FACE_VALUE_UNITS_EXPECTED:
                errors.append(
                    f"FACE_VALUE_UNITS '{units}' is not "
                    f"'{FACE_VALUE_UNITS_EXPECTED}'; this importer does not "
                    "convert units."
                )
            else:
                try:
                    data["face_value_acre_feet"] = Decimal(face_value_raw)
                except (InvalidOperation, ValueError):
                    errors.append(
                        f"FACE_VALUE_AMOUNT is not a number: '{face_value_raw}'."
                    )

        # --- max rate + its unit ---
        rate_raw = src("max_rate_cfs")
        if rate_raw:
            units = src("max_rate_units")
            if units and units != MAX_DD_UNITS_EXPECTED:
                errors.append(
                    f"MAX_DD_UNITS '{units}' is not "
                    f"'{MAX_DD_UNITS_EXPECTED}'; this importer does not "
                    "convert units."
                )
            else:
                try:
                    data["max_rate_cfs"] = Decimal(rate_raw)
                except (InvalidOperation, ValueError):
                    errors.append(f"MAX_DD_APPL is not a number: '{rate_raw}'.")

        net_acreage_raw = src("net_acreage")
        if net_acreage_raw:
            try:
                data["net_acreage"] = Decimal(net_acreage_raw)
            except (InvalidOperation, ValueError):
                errors.append(f"USE_NET_ACREAGE is not a number: '{net_acreage_raw}'.")

        data["priority_date"] = _parse_priority_date(src("priority_date"), errors)

        for field in _INT_FIELDS:
            val = src(field)
            if val:
                try:
                    data[field] = int(Decimal(val))
                except (InvalidOperation, ValueError):
                    errors.append(f"{FIELD_LABELS[field]} is not a number: '{val}'.")

        results.append(
            {"index": index, "data": data, "errors": errors, "warnings": warnings}
        )

    return results


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


def commit_rows(valid_results):
    """Create a WaterRight from the coerced `data` of every error-free row.

    One outer transaction with a per-row savepoint, the same shape
    ``infrastructure.importer.commit_rows`` uses: a single bad row (a unique
    constraint slipping past the dedup check under a race, say) is rolled
    back and reported, never allowed to poison the whole batch.
    """
    clean = [r for r in valid_results if not r["errors"]]
    created = 0

    with transaction.atomic():
        for result in clean:
            data = {k: v for k, v in result["data"].items() if k in _MODEL_FIELDS}
            try:
                with transaction.atomic():
                    WaterRight.objects.create(**data)
                created += 1
            except Exception as exc:
                result["errors"].append(f"could not be saved: {exc}")

    return created
