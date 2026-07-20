# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Lab sample-result import engine.

Four UI-independent functions the import views are thin glue over, deliberately
mirroring ``infrastructure/importer.py``'s contract so the codebase has ONE
import idiom:

  parse_upload(file, filename)   -> {"columns": [...], "rows": [...]}
  auto_map_columns(columns)      -> {logical_field: source_column}
  validate_rows(rows, mapping)   -> [{index, data, errors, warnings}]
  commit_rows(valid_results)     -> {"events": n, "results": n, "analytes": n, ...}

**Architecture mirrored, code not shared.** This module imports nothing from
``infrastructure``. A module-scope import of ``infrastructure.importer`` would
make dropping the ``infrastructure`` app crash ``drinking`` — the exact coupling
Phase 77 quarantined. Lab CSVs need none of the GDAL/shapefile machinery
anyway, so this is stdlib ``csv`` only.

The file layout is DDW's *Data Dictionary for SDWIS.CSV Files* (rev 12/2021):
the same columns the state's own SDWIS1/2/3.CSV extracts carry, so a raw DDW
export maps with zero clicks.

Three rules govern what this engine will and will not do.

**Facilities and sampling points are deliberate setup, not import side effects.**
An unknown ``PS Code`` is a ROW ERROR. Inventing a sampling point (and the
facility and water system above it) from a lab file would let a typo silently
manufacture system structure that then looks like a real monitoring location.

**Analytes are the regulator's vocabulary, so the file may extend it.** An
unknown analyte IS created — from the file's own ``Analyte Code`` + ``Analyte
Name``, which is DDW's vocabulary rather than ours — and the preview says so.
78-01 seeded every ``ddw_code`` as NULL because DDW publishes no code list, so
name is the workhorse match and a code arriving in a file is *learned*.

**Prepare, never determine.** The DDW layout carries ``MCL`` and ``DLR``
columns. This importer deliberately reads neither: a limit stored on the result
row beside the value is one template change away from a compliance verdict, and
``RegulatoryLimit`` is the versioned home for what a limit was on a given date.
"""

import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.dateparse import parse_date, parse_time

from drinking.models import (
    RESULT_KIND_NUMERIC,
    RESULT_KIND_PRESENCE_ABSENCE,
    SAMPLE_TYPE_CHOICES,
    Analyte,
    SampleEvent,
    SampleResult,
    SamplingPoint,
)

# Hard cap on a single import. Higher than infrastructure's 500 for the same
# small-VPS rationale: one well is one row, but one sample event is a dozen-plus
# analyte rows, so a single quarter of routine monitoring is already hundreds of
# rows. 5000 keeps a realistic annual lab extract in one file while still
# bounding the work.
MAX_ROWS = 5000

# Raw-upload byte ceiling, mirroring infrastructure's rationale: MAX_ROWS is
# only checked AFTER a full parse, so it is no defense against a 5GB file.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

# Result-column tokens meaning "present" / "absent".
#
# NOTE: the DDW dictionary documents `Result` as "Numerical result of analysis"
# and defines NO presence/absence convention — microbiological P/A findings
# arrive by lab convention, not by published spec. These tokens are therefore an
# honest best-effort read of what labs actually write, not a transcription of a
# valid-value table. Anything outside these sets and outside numeric parsing is
# a row ERROR, never coerced to zero.
_PRESENT_TOKENS = {"p", "present", "pos", "positive", "detected"}
_ABSENT_TOKENS = {"a", "absent", "neg", "negative", "nd", "non-detect"}

_SAMPLE_TYPES = {code for code, _label in SAMPLE_TYPE_CHOICES}


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


def parse_upload(file, filename):
    """Parse an uploaded lab CSV into {"columns": [...], "rows": [dict, ...]}.

    CSV only — a lab result file is tabular by nature and the spatial formats
    the infrastructure importer accepts have no meaning here.

    Raises ImportError on: oversize upload, unsupported extension, no rows, or
    more than MAX_ROWS rows.
    """
    name = (filename or "").lower()

    # Reject an oversized file before parsing it. (Django's
    # DATA_UPLOAD_MAX_MEMORY_SIZE does not cover file uploads.)
    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(
            f"File is too large ({size // (1024 * 1024)} MB); the upload cap is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB. Please split it into "
            "smaller files."
        )

    if not name.endswith(".csv"):
        raise ImportError(
            "Unsupported format. Lab results import from a .csv file — the "
            "layout the state's own SDWIS.CSV extracts use."
        )

    rows, columns = _parse_csv(file)

    if len(rows) > MAX_ROWS:
        raise ImportError(
            f"File contains {len(rows)} rows, over the {MAX_ROWS}-row import "
            "cap. Please split it into smaller files."
        )
    if not rows:
        raise ImportError("No rows found in the uploaded file.")

    return {"columns": columns, "rows": rows}


def _parse_csv(file):
    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")  # tolerate a BOM from Excel exports
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    rows = []
    for row in reader:
        # Normalize None values (short rows) to empty strings, and drop the
        # None key DictReader uses for surplus cells on a long row.
        rows.append(
            {k: ("" if v is None else v) for k, v in row.items() if k is not None}
        )
    return rows, columns


# ---------------------------------------------------------------------------
# auto_map_columns
# ---------------------------------------------------------------------------

# Logical field -> accepted source-column spellings, matched case- and
# punctuation-insensitively. The FIRST alias of each is the exact DDW
# SDWIS.CSV header, so a raw state export maps with no manual assignment; the
# rest accommodate the spellings commercial labs actually ship.
ALIASES = {
    "ps_code": {"ps code", "ps_code", "pscode", "sampling point id", "station"},
    "sampling_point_name": {"sampling point name", "sample point name"},
    "sample_date": {"sample date", "collection date", "date sampled", "sampled"},
    "sample_time": {"sample time", "collection time", "time sampled"},
    "sample_type": {"sample type", "type of sample"},
    "analysis_date": {"analysis date", "analyzed date", "date analyzed"},
    "lab_cert_no": {"elap cert#", "elap cert", "elap cert no", "lab cert", "cert no"},
    "lab_name": {"lab name", "laboratory", "laboratory name"},
    "ddw_code": {"analyte code", "analyte_code", "storet", "storet code"},
    "analyte_name": {"analyte name", "analyte", "parameter", "constituent"},
    "result": {"result", "result value", "finding", "concentration"},
    "counting_error": {"counting error (±)", "counting error", "count error"},
    "unit": {"units of measure", "units", "unit", "uom"},
    "less_than_rl": {
        "less than reporting level",
        "less than rl",
        "lt rl",
        "non-detect",
    },
    "reporting_level": {"reporting level", "rl", "reporting limit"},
    "method": {"method", "analytical method", "method code"},
    "collector": {"collector", "sampled by", "collected by"},
}

# Human-readable labels for the preview's "columns we recognised" summary.
FIELD_LABELS = {
    "ps_code": "PS Code",
    "sampling_point_name": "Sampling point name",
    "sample_date": "Sample date",
    "sample_time": "Sample time",
    "sample_type": "Sample type",
    "analysis_date": "Analysis date",
    "lab_cert_no": "ELAP cert #",
    "lab_name": "Lab name",
    "ddw_code": "Analyte code",
    "analyte_name": "Analyte name",
    "result": "Result",
    "counting_error": "Counting error",
    "unit": "Units of measure",
    "less_than_rl": "Less than reporting level",
    "reporting_level": "Reporting level",
    "method": "Method",
    "collector": "Collector",
}

# Without these four a row cannot become a result at all.
REQUIRED_FIELDS = ["ps_code", "sample_date", "analyte_name", "result"]


def import_fields():
    """Ordered [(logical_field, label)] this importer understands."""
    return [(field, FIELD_LABELS.get(field, field)) for field in ALIASES]


def _normalize(col):
    """Lowercase, strip, collapse any run of non-alphanumerics to single '_'."""
    out = []
    prev_us = False
    for ch in col.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def auto_map_columns(columns):
    """Best-effort {logical_field: source_column}; unmatched fields absent.

    Deterministic: iterates the alias table in definition order and, for each
    field, takes the first source column whose normalized form matches one of
    that field's aliases.
    """
    norm_to_source = {}
    for col in columns:
        norm = _normalize(col)
        norm_to_source.setdefault(norm, col)  # first spelling wins, deterministic

    mapping = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            norm_alias = _normalize(alias)
            if norm_alias in norm_to_source:
                mapping[field] = norm_to_source[norm_alias]
                break
    return mapping


def missing_required(mapping):
    """Required logical fields the mapping does not cover, as labels."""
    return [
        FIELD_LABELS[field] for field in REQUIRED_FIELDS if not mapping.get(field)
    ]


# ---------------------------------------------------------------------------
# validate_rows
# ---------------------------------------------------------------------------


def _decimal_or_none(raw):
    """Decimal from a lab-formatted number, or None if it is not one.

    Tolerates thousands separators and a leading '+' — both appear in real lab
    exports. Deliberately does NOT strip a '<': the caller handles non-detects
    explicitly, because silently dropping the operator turns a bound into a
    measurement.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").lstrip("+")
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def _parse_result(raw_result, raw_lt_rl, raw_rl, errors):
    """Read one Result cell into the model's honest shape.

    Returns a dict of SampleResult fields, or None when the cell is neither a
    number nor a recognised presence/absence token — in which case an error is
    appended. Nothing is ever coerced to zero: "we could not read this" and
    "the lab measured zero" are different claims.
    """
    text = (raw_result or "").strip()
    lt_flag = (raw_lt_rl or "").strip().lower() in {"y", "yes", "true", "1"}
    reporting_level = _decimal_or_none(raw_rl)

    if not text:
        errors.append("Result is blank.")
        return None

    # --- presence / absence -------------------------------------------------
    token = text.lower()
    if token in _PRESENT_TOKENS or token in _ABSENT_TOKENS:
        # 'ND' / 'non-detect' is a chemistry non-detect, not a microbiological
        # absence, so it only reads as "absent" when nothing numeric is in play.
        return {
            "result_kind": RESULT_KIND_PRESENCE_ABSENCE,
            "presence": token in _PRESENT_TOKENS,
            "result_value": None,
            # A presence/absence row may not carry the non-detect flag: "absent"
            # is not "below reporting level". The DB CheckConstraint enforces
            # this too; we simply never set it.
            "less_than_rl": False,
            "reporting_level": None,
        }

    # --- numeric non-detect: "<0.5", or the LT-RL column set -----------------
    explicit_lt = text.startswith("<")
    number = _decimal_or_none(text[1:] if explicit_lt else text)

    if number is None:
        errors.append(
            f"Result '{text}' is neither a number nor a presence/absence value."
        )
        return None

    if explicit_lt or lt_flag:
        # A non-detect is a BOUND, not a value. `result_value` stays NULL: the
        # number on a non-detect row is the level the lab could report down to,
        # not a concentration anybody measured. Storing it as a value would
        # invent data, and `_result_value.html` renders "< {reporting_level}"
        # precisely so a bound never reads as a measurement.
        return {
            "result_kind": RESULT_KIND_NUMERIC,
            "presence": None,
            "result_value": None,
            "less_than_rl": True,
            # Prefer the file's own Reporting Level column; fall back to the
            # number carried on the result cell itself.
            "reporting_level": reporting_level if reporting_level is not None else number,
        }

    return {
        "result_kind": RESULT_KIND_NUMERIC,
        "presence": None,
        "result_value": number,
        "less_than_rl": False,
        "reporting_level": reporting_level,
    }


def validate_rows(rows, mapping):
    """Validate + coerce a batch into writer-ready `data` dicts.

    Returns a list of {index, data, errors, warnings}. A row with any errors is
    skipped by commit_rows; warnings never block a commit.

    Warning taxonomy the preview surfaces:
      - "new analyte"  -> this file will extend the analyte vocabulary
      - "duplicate"    -> an identical result already exists (or repeats within
                          this same file); committing will skip it
    """
    results = []

    # Everything the batch needs from the DB, fetched once rather than per row.
    known_points = {
        code: pk
        for pk, code in SamplingPoint.objects.values_list("pk", "ps_code")
    }
    known_analytes_by_name = {
        name.strip().lower(): pk
        for pk, name in Analyte.objects.values_list("pk", "name")
    }
    known_analytes_by_code = {
        code: pk
        for pk, code in Analyte.objects.exclude(ddw_code__isnull=True)
        .exclude(ddw_code="")
        .values_list("pk", "ddw_code")
    }

    # Existing results, keyed the way the duplicate guard keys them.
    existing_keys = {
        (event_id, analyte_id, (method or "").strip().lower())
        for event_id, analyte_id, method in SampleResult.objects.values_list(
            "event_id", "analyte_id", "method"
        )
    }
    existing_events = {
        (point_id, date, time, stype): pk
        for pk, point_id, date, time, stype in SampleEvent.objects.values_list(
            "pk", "sampling_point_id", "sample_date", "sample_time", "sample_type"
        )
    }

    # Within-batch bookkeeping: a file that repeats a row is as much a duplicate
    # as one that repeats what is already stored.
    seen_in_batch = set()
    new_analyte_names = set()

    for index, row in enumerate(rows):
        errors = []
        warnings = []
        data = {}

        def src(field):
            col = mapping.get(field)
            if not col:
                return ""
            return (row.get(col) or "").strip()

        # --- sampling point: must already exist -----------------------------
        ps_code = src("ps_code")
        if not ps_code:
            errors.append("PS Code is required (blank or unmapped).")
        elif ps_code not in known_points:
            errors.append(
                f"PS Code '{ps_code}' is not a known sampling point. Add the "
                "facility and sampling point first — a lab file does not create "
                "system structure."
            )
        else:
            data["sampling_point_id"] = known_points[ps_code]
        data["ps_code"] = ps_code

        # --- event identity -------------------------------------------------
        raw_date = src("sample_date")
        sample_date = parse_date(raw_date) if raw_date else None
        if not raw_date:
            errors.append("Sample date is required (blank or unmapped).")
        elif sample_date is None:
            errors.append(f"Sample date '{raw_date}' is not a date (use YYYY-MM-DD).")
        data["sample_date"] = sample_date

        raw_time = src("sample_time")
        sample_time = parse_time(raw_time) if raw_time else None
        if raw_time and sample_time is None:
            warnings.append(f"Sample time '{raw_time}' was not readable; ignored.")
        data["sample_time"] = sample_time

        sample_type = src("sample_type").lower() or "routine"
        if sample_type not in _SAMPLE_TYPES:
            warnings.append(
                f"Sample type '{sample_type}' is not a standard type; recorded "
                "as routine."
            )
            sample_type = "routine"
        data["sample_type"] = sample_type
        data["collector"] = src("collector")

        # --- analyte --------------------------------------------------------
        analyte_name = src("analyte_name")
        ddw_code = src("ddw_code")
        data["analyte_name"] = analyte_name
        data["ddw_code"] = ddw_code

        if not analyte_name:
            errors.append("Analyte name is required (blank or unmapped).")
        else:
            key = analyte_name.lower()
            analyte_pk = known_analytes_by_code.get(ddw_code) if ddw_code else None
            if analyte_pk is None:
                analyte_pk = known_analytes_by_name.get(key)
            if analyte_pk is not None:
                data["analyte_id"] = analyte_pk
            else:
                # Not an error. DDW's own file is the vocabulary source; we
                # record that the file is extending it so the operator sees it
                # before committing.
                if key not in new_analyte_names:
                    new_analyte_names.add(key)
                warnings.append(
                    f"'{analyte_name}' is a new analyte and will be added to the "
                    "vocabulary from this file."
                )

        # --- the finding itself ---------------------------------------------
        parsed = _parse_result(
            src("result"), src("less_than_rl"), src("reporting_level"), errors
        )
        if parsed:
            data.update(parsed)

        data["unit"] = src("unit")
        data["method"] = src("method")
        data["lab_name"] = src("lab_name")
        data["lab_cert_no"] = src("lab_cert_no")
        data["counting_error"] = _decimal_or_none(src("counting_error"))

        raw_analysis = src("analysis_date")
        analysis_date = parse_date(raw_analysis) if raw_analysis else None
        if raw_analysis and analysis_date is None:
            warnings.append(
                f"Analysis date '{raw_analysis}' was not readable; ignored."
            )
        data["analysis_date"] = analysis_date

        # --- duplicate guard -------------------------------------------------
        # Keyed on (event, analyte, method) so re-importing the same file is a
        # no-op rather than a doubling. Checked against both the DB and the rest
        # of this batch.
        if not errors and data.get("analyte_id") is not None:
            event_pk = existing_events.get(
                (
                    data.get("sampling_point_id"),
                    sample_date,
                    sample_time,
                    sample_type,
                )
            )
            method_key = data["method"].strip().lower()
            if event_pk is not None:
                if (event_pk, data["analyte_id"], method_key) in existing_keys:
                    data["is_duplicate"] = True
                    warnings.append(
                        "This result is already recorded; it will be skipped."
                    )

        if not errors:
            batch_key = (
                data.get("sampling_point_id"),
                sample_date,
                sample_time,
                sample_type,
                data.get("analyte_id"),
                analyte_name.lower(),
                data.get("method", "").strip().lower(),
            )
            if batch_key in seen_in_batch:
                data["is_duplicate"] = True
                warnings.append(
                    "This row repeats an earlier row in this file; it will be "
                    "skipped."
                )
            seen_in_batch.add(batch_key)

        results.append(
            {"index": index, "data": data, "errors": errors, "warnings": warnings}
        )

    return results


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


def commit_rows(valid_results):
    """Create events + results from the coerced `data` of error-free rows.

    Returns {"events", "results", "analytes", "duplicates", "skipped"}.

    Wrapped in a single transaction: a lab file lands whole or not at all. Rows
    carrying errors, and rows flagged as duplicates, are skipped.
    """
    clean = [
        r
        for r in valid_results
        if not r["errors"] and not r["data"].get("is_duplicate")
    ]

    counts = {
        "events": 0,
        "results": 0,
        "analytes": 0,
        "duplicates": sum(
            1 for r in valid_results if r["data"].get("is_duplicate")
        ),
        "skipped": sum(1 for r in valid_results if r["errors"]),
    }

    # Caches so a 5000-row file does not re-query per row.
    analyte_cache = {}
    event_cache = {}

    with transaction.atomic():
        for result in clean:
            data = result["data"]

            # --- analyte: match, or learn from the file's own vocabulary ----
            analyte_id = data.get("analyte_id")
            if analyte_id is None:
                key = data["analyte_name"].strip().lower()
                if key in analyte_cache:
                    analyte_id = analyte_cache[key]
                else:
                    analyte, made = Analyte.objects.get_or_create(
                        name=data["analyte_name"].strip(),
                        defaults={"ddw_code": data.get("ddw_code") or None},
                    )
                    if made:
                        counts["analytes"] += 1
                    analyte_id = analyte.pk
                    analyte_cache[key] = analyte_id

            # 78-01 seeded every ddw_code NULL because DDW publishes no code
            # list. When a file carries a code for an analyte we already know
            # by name, LEARN it — but only if no other analyte already holds
            # that code, because ddw_code is unique.
            code = data.get("ddw_code")
            if code:
                Analyte.objects.filter(pk=analyte_id, ddw_code__isnull=True).exclude(
                    pk__in=Analyte.objects.filter(ddw_code=code).values("pk")
                ).update(ddw_code=code)

            # --- event: one per (point, date, time, type) -------------------
            event_key = (
                data["sampling_point_id"],
                data["sample_date"],
                data["sample_time"],
                data["sample_type"],
            )
            if event_key in event_cache:
                event_id = event_cache[event_key]
            else:
                event, made = SampleEvent.objects.get_or_create(
                    sampling_point_id=data["sampling_point_id"],
                    sample_date=data["sample_date"],
                    sample_time=data["sample_time"],
                    sample_type=data["sample_type"],
                    defaults={"collector": data.get("collector", "")},
                )
                if made:
                    counts["events"] += 1
                event_id = event.pk
                event_cache[event_key] = event_id

            # --- the result --------------------------------------------------
            # Per-row savepoint: one row that trips a CheckConstraint is rolled
            # back and reported, not allowed to poison the whole file.
            try:
                with transaction.atomic():
                    SampleResult.objects.create(
                        event_id=event_id,
                        analyte_id=analyte_id,
                        result_kind=data["result_kind"],
                        result_value=data["result_value"],
                        presence=data["presence"],
                        unit=data["unit"],
                        less_than_rl=data["less_than_rl"],
                        reporting_level=data["reporting_level"],
                        counting_error=data["counting_error"],
                        analysis_date=data["analysis_date"],
                        method=data["method"],
                        lab_name=data["lab_name"],
                        lab_cert_no=data["lab_cert_no"],
                    )
                counts["results"] += 1
            except Exception:
                result["errors"].append("could not be saved (invalid result data).")
                counts["skipped"] += 1

    return counts
