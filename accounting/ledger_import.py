# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ONE ledger-CSV import service, shared by the CLI command and the web upload.

Before this module there were two importers with different rules, and the web
one was the weaker of the two (math eval 2026-07-18, item 3). Uploading through
the UI skipped the duplicate check entirely, so re-uploading a file doubled every
row it contained; it could write into a finalized reporting period, rewriting a
number already filed with the state; and its usage-source set omitted
``calculated``, so a positive calculated row passed validation and then failed
against the ParcelLedger sign constraint as a 500 instead of a row error.

Both callers now run this core, so a file behaves identically whichever door it
comes through. The command and the view keep only their own presentation: stdout
formatting for the CLI, the result dict the upload template renders.

Rules enforced here, in order:

1. Required columns, then per-row field validation.
2. SIGN NORMALIZATION. Usage rows debit (<= 0), supply rows credit (> 0). The
   file's magnitudes are trusted; its signs are not. We normalize rather than
   reject because meters read positive, so real district exports carry unsigned
   magnitudes and rejecting them would fail the files this exists to load. Every
   coercion is COUNTED and reported to the operator — normalizing is a judgement
   about the file, and it must never be silent. The web upload's dry-run preview
   surfaces the count before anything is written.
3. FINALIZED-PERIOD GUARD (ISS-029, 147-02). A row dated inside a finalized
   period, or any row when the period picked for the whole file is finalized,
   is refused as a row error in plain words. It runs on every import, the
   preview included, whether or not a period was picked (the web upload with a
   period picked used to skip it entirely). The database refuses the same
   rows anyway (accounting/locks.py); this says which ones before writing.
4. DEDUP (ISS-029 idempotency). The ledger is an append-only journal, so we never
   delete — we skip a row that already exists with the same
   (parcel, effective_date, source_type, amount) and collapse exact duplicates
   within the file. Re-importing the same CSV writes nothing the second time,
   while a genuinely corrected amount (a different key) still lands.

A ledger export from a demonstration site starts with one line saying so
(``DEMONSTRATION_FILE_LINE``). The import skips that line, and only that line,
so the site's own export re-imports as downloaded (2026-10-18).
"""
from __future__ import annotations

import csv
import itertools
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TextIO

from django.db import transaction

from accounting.ledger_words import DEMONSTRATION_FILE_LINE
from accounting.locks import finalized_message
from accounting.models import ReportingPeriod, WaterType
from parcels.models import (
    NON_POSITIVE_SOURCE_TYPES,
    POSITIVE_SOURCE_TYPES,
    Parcel,
    ParcelLedger,
)

REQUIRED_COLUMNS = {
    "parcel_number",
    "effective_date",
    "amount_acre_feet",
    "source_type",
}


def parse_date(date_str):
    """Parse a date string in YYYY-MM-DD or MM/DD/YYYY format, or return None."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _fatal(message):
    return {
        "created_count": 0,
        "error_count": 1,
        "errors": [{"line": 1, "messages": [message]}],
        "preview": [],
        "skipped_duplicate": 0,
        "sign_normalized": 0,
        "sign_normalized_rows": [],
    }


def _open_ledger_reader(
    text_file: TextIO, delimiter: str
) -> tuple[csv.DictReader[str], int]:
    """A DictReader over the file, skipping the demonstration line; plus the first data line number."""
    first_line = text_file.readline()
    first_data_line = 2
    if first_line.lstrip('﻿').strip().strip('"') == DEMONSTRATION_FILE_LINE:
        first_data_line = 3
    elif first_line:
        text_file = itertools.chain([first_line], text_file)
    reader = csv.DictReader(text_file, delimiter=delimiter)
    return reader, first_data_line


def _header_failure(reader: csv.DictReader[str]) -> dict[str, Any] | None:
    """The fatal result when the file has no headers or lacks a required column, else None."""
    if reader.fieldnames is None:
        return _fatal("CSV file appears empty or has no headers.")

    actual_columns = {c.strip().lower() for c in reader.fieldnames if c}
    missing = REQUIRED_COLUMNS - actual_columns
    if missing:
        return _fatal(f"Missing required columns: {', '.join(sorted(missing))}")
    return None


def _lookup_parcel(
    parcel_number: str,
    parcel_cache: dict[str, Parcel | None],
    row_errors: list[str],
) -> Parcel | None:
    """The parcel for this row (cached per file), recording an error when missing or unknown."""
    parcel = None
    if not parcel_number:
        row_errors.append("missing parcel_number")
    else:
        if parcel_number not in parcel_cache:
            try:
                parcel_cache[parcel_number] = Parcel.objects.get(
                    parcel_number=parcel_number
                )
            except Parcel.DoesNotExist:
                parcel_cache[parcel_number] = None
        parcel = parcel_cache[parcel_number]
        if parcel is None:
            row_errors.append(f"unknown parcel_number: {parcel_number}")
    return parcel


def _parse_amount(amount_raw: str, row_errors: list[str]) -> Decimal | None:
    """The row's amount as a Decimal, recording an error when missing or invalid."""
    amount = None
    if not amount_raw:
        row_errors.append("missing amount_acre_feet")
    else:
        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            row_errors.append(f"invalid amount: {amount_raw}")
    return amount


def _normalized_sign(
    amount: Decimal,
    source_type: str,
    line_num: int,
    sign_normalized_rows: list[dict[str, Any]],
) -> Decimal:
    """The amount with the sign its source type requires, noting each coerced row."""
    if source_type in NON_POSITIVE_SOURCE_TYPES and amount > 0:
        before = amount
        amount = -amount
        sign_normalized_rows.append(
            {
                "row": line_num,
                "source_type": source_type,
                "before": before,
                "after": amount,
            }
        )
    elif source_type in POSITIVE_SOURCE_TYPES and amount < 0:
        before = amount
        amount = -amount
        sign_normalized_rows.append(
            {
                "row": line_num,
                "source_type": source_type,
                "before": before,
                "after": amount,
            }
        )
    return amount


def _finalized_period_error(
    effective_date: date | None,
    effective_date_raw: str,
    finalized_spans: list[tuple[date, date, str]],
    reporting_period: ReportingPeriod | None,
    picked_is_finalized: bool,
) -> str | None:
    """The refusal message when the row's date or the picked period is finalized, else None."""
    # Finalized-period guard: the row's own date, then the period picked
    # for the whole file.
    hit = None
    if effective_date is not None:
        hit = next(
            (n for (s, e, n) in finalized_spans if s <= effective_date <= e),
            None,
        )
    if hit is None and picked_is_finalized:
        hit = reporting_period.name
    if hit:
        return (
            f"effective_date {effective_date or effective_date_raw}: "
            f"{finalized_message(hit)}"
        )
    return None


def _lookup_water_type(
    water_type_code: str,
    water_type_cache: dict[str, WaterType | None],
    row_errors: list[str],
) -> WaterType | None:
    """The optional water type for this row (cached per file), recording an error when unknown."""
    water_type = None
    if water_type_code:
        if water_type_code not in water_type_cache:
            try:
                water_type_cache[water_type_code] = WaterType.objects.get(
                    code=water_type_code
                )
            except WaterType.DoesNotExist:
                water_type_cache[water_type_code] = None
        water_type = water_type_cache[water_type_code]
        if water_type is None:
            row_errors.append(f"unknown water_type_code: {water_type_code}")
    return water_type


def _check_row(
    row: dict[str, str],
    line_num: int,
    *,
    valid_source_types: set[str],
    parcel_cache: dict[str, Parcel | None],
    water_type_cache: dict[str, WaterType | None],
    finalized_spans: list[tuple[date, date, str]],
    reporting_period: ReportingPeriod | None,
    picked_is_finalized: bool,
    sign_normalized_rows: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Validate one CSV row; returns ``(row_errors, fields)`` with the parsed values."""
    row_errors: list[str] = []
    parcel_number = row.get("parcel_number", "")
    effective_date_raw = row.get("effective_date", "")
    amount_raw = row.get("amount_acre_feet", "")
    source_type = row.get("source_type", "")
    water_type_code = row.get("water_type_code", "")
    description = row.get("description", "")
    transaction_date_raw = row.get("transaction_date", "")

    parcel = _lookup_parcel(parcel_number, parcel_cache, row_errors)
    amount = _parse_amount(amount_raw, row_errors)

    # Source type
    if not source_type:
        row_errors.append("missing source_type")
    elif source_type not in valid_source_types:
        row_errors.append(f"invalid source_type: {source_type}")

    # Sign rule (see module docstring). Runs only on an otherwise-parseable
    # amount and a known source_type, so a garbage row reports its real
    # problem instead of a confusing sign message.
    if amount is not None and source_type in valid_source_types:
        amount = _normalized_sign(amount, source_type, line_num, sign_normalized_rows)

    # Effective date
    effective_date = None
    if not effective_date_raw:
        row_errors.append("missing effective_date")
    else:
        effective_date = parse_date(effective_date_raw)
        if effective_date is None:
            row_errors.append(f"invalid effective_date: {effective_date_raw}")

    finalized_error = _finalized_period_error(
        effective_date, effective_date_raw, finalized_spans,
        reporting_period, picked_is_finalized,
    )
    if finalized_error:
        row_errors.append(finalized_error)

    water_type = _lookup_water_type(water_type_code, water_type_cache, row_errors)

    # Optional transaction date
    transaction_date = None
    if transaction_date_raw:
        transaction_date = parse_date(transaction_date_raw)
        if transaction_date is None:
            row_errors.append(
                f"invalid transaction_date: {transaction_date_raw}"
            )

    return row_errors, {
        "parcel": parcel,
        "parcel_number": parcel_number,
        "amount": amount,
        "source_type": source_type,
        "effective_date": effective_date,
        "water_type": water_type,
        "description": description,
        "transaction_date": transaction_date,
    }


def _new_entry(
    fields: dict[str, Any], reporting_period: ReportingPeriod | None
) -> tuple[tuple[int, date, str, Decimal], ParcelLedger]:
    """The dedup key and the unsaved ledger row for one valid CSV row."""
    parcel = fields["parcel"]
    effective_date = fields["effective_date"]
    source_type = fields["source_type"]
    transaction_date = fields["transaction_date"]
    if transaction_date is None:
        transaction_date = effective_date

    # Quantize to the column's 4dp so the dedup key matches what the DB
    # stores (a re-run's parsed value lines up with the stored one).
    amount_q = fields["amount"].quantize(Decimal("0.0001"))
    key = (parcel.id, effective_date, source_type, amount_q)
    return (
        key,
        ParcelLedger(
            parcel=parcel,
            transaction_date=transaction_date,
            effective_date=effective_date,
            amount_acre_feet=amount_q,
            water_type=fields["water_type"],
            source_type=source_type,
            description=fields["description"],
            reporting_period=reporting_period,
        ),
    )


def _drop_duplicates(
    entries_to_create: list[tuple[tuple[int, date, str, Decimal], ParcelLedger]],
) -> tuple[list[ParcelLedger], int]:
    """Dedup against what is already stored, and within the file itself."""
    skipped_duplicate = 0
    survivors = []
    if entries_to_create:
        parcel_ids = {key[0] for key, _entry in entries_to_create}
        existing = set(
            ParcelLedger.objects.filter(parcel_id__in=parcel_ids).values_list(
                "parcel_id", "effective_date", "source_type", "amount_acre_feet"
            )
        )
        seen = set()
        for key, entry in entries_to_create:
            if key in existing or key in seen:
                skipped_duplicate += 1
                continue
            seen.add(key)
            survivors.append(entry)
    return survivors, skipped_duplicate


def _finalized_spans() -> list[tuple[date, date, str]]:
    """The ``(start, end, name)`` of every finalized reporting period."""
    # Finalized periods are loaded once, for every import (147-02): with or
    # without a period picked, and for the preview as well as the commit, so
    # the preview never counts a row the commit would refuse.
    return list(
        ReportingPeriod.objects.filter(is_finalized=True).values_list(
            "start_date", "end_date", "name"
        )
    )


def import_ledger_rows(
    text_file,
    *,
    reporting_period=None,
    dry_run=False,
    delimiter=",",
):
    """Validate and import ledger rows from an open text-mode CSV file.

    ``reporting_period`` is assigned to every created row when given; a
    finalized one refuses every row. The finalized-period guard also runs per
    row by date, either way. ``dry_run`` validates and reports without writing.

    Returns a dict: created_count, error_count, errors (list of
    {"line", "messages"}), preview (first 5 rows), skipped_duplicate,
    sign_normalized, sign_normalized_rows.
    """
    valid_source_types = {choice[0] for choice in ParcelLedger.SOURCE_TYPE_CHOICES}
    parcel_cache: dict[str, Parcel | None] = {}
    water_type_cache: dict[str, WaterType | None] = {}

    errors = []
    entries_to_create = []
    preview = []
    # ISS-196: the count alone never named which rows it touched. One entry
    # per coerced row -- the line number, the source_type that decided the
    # sign, and the value before and after -- printed by the CLI and listed
    # by the web upload, so "10 row(s) had their sign normalized" is never
    # the whole story on any door again.
    sign_normalized_rows: list[dict[str, Any]] = []

    reader, first_data_line = _open_ledger_reader(text_file, delimiter)
    failure = _header_failure(reader)
    if failure is not None:
        return failure

    finalized_spans = _finalized_spans()
    picked_is_finalized = bool(reporting_period and reporting_period.is_finalized)

    for line_num, row in enumerate(reader, start=first_data_line):
        row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
        row_errors, fields = _check_row(
            row, line_num,
            valid_source_types=valid_source_types,
            parcel_cache=parcel_cache,
            water_type_cache=water_type_cache,
            finalized_spans=finalized_spans,
            reporting_period=reporting_period,
            picked_is_finalized=picked_is_finalized,
            sign_normalized_rows=sign_normalized_rows,
        )
        if row_errors:
            errors.append({"line": line_num, "messages": row_errors})
            continue

        key, entry = _new_entry(fields, reporting_period)
        entries_to_create.append((key, entry))

        if len(preview) < 5:
            preview.append(
                {
                    "parcel_number": fields["parcel_number"],
                    "effective_date": fields["effective_date"],
                    "amount": key[3],
                    "source_type": fields["source_type"],
                }
            )

    survivors, skipped_duplicate = _drop_duplicates(entries_to_create)

    # One transaction so a mid-import failure can't leave a half-written ledger.
    if not dry_run and survivors:
        batch_size = 500
        with transaction.atomic():
            for i in range(0, len(survivors), batch_size):
                ParcelLedger.objects.bulk_create(survivors[i : i + batch_size])

    # 149-01: the months a hand-or-file delivery row landed in, so the screen
    # that saved them can start the recalculation for exactly those months.
    surface_months = sorted(
        {
            f"{entry.effective_date:%Y-%m}"
            for entry in survivors
            if entry.source_type == "surface_diversion"
        }
    )

    return {
        "surface_diversion_months": surface_months,
        "created_count": len(survivors),
        "error_count": len(errors),
        "errors": errors,
        "preview": preview,
        "skipped_duplicate": skipped_duplicate,
        "sign_normalized": len(sign_normalized_rows),
        "sign_normalized_rows": sign_normalized_rows,
    }
