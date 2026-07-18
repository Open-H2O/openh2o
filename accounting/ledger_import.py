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
3. FINALIZED-PERIOD GUARD (ISS-029). A row dated inside a finalized period is
   refused, because that period is a number already filed with the state.
4. DEDUP (ISS-029 idempotency). The ledger is an append-only journal, so we never
   delete — we skip a row that already exists with the same
   (parcel, effective_date, source_type, amount) and collapse exact duplicates
   within the file. Re-importing the same CSV writes nothing the second time,
   while a genuinely corrected amount (a different key) still lands.
"""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

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
    }


def import_ledger_rows(
    text_file,
    *,
    reporting_period=None,
    dry_run=False,
    delimiter=",",
):
    """Validate and import ledger rows from an open text-mode CSV file.

    ``reporting_period`` is assigned to every created row when given. When it is
    None, rows carry no period and the finalized-period guard runs per row by
    date instead. ``dry_run`` validates and reports without writing.

    Returns a dict: created_count, error_count, errors (list of
    {"line", "messages"}), preview (first 5 rows), skipped_duplicate,
    sign_normalized.
    """
    valid_source_types = {choice[0] for choice in ParcelLedger.SOURCE_TYPE_CHOICES}
    parcel_cache = {}
    water_type_cache = {}

    errors = []
    entries_to_create = []
    preview = []
    sign_normalized = 0

    reader = csv.DictReader(text_file, delimiter=delimiter)

    if reader.fieldnames is None:
        return _fatal("CSV file appears empty or has no headers.")

    actual_columns = {c.strip().lower() for c in reader.fieldnames if c}
    missing = REQUIRED_COLUMNS - actual_columns
    if missing:
        return _fatal(f"Missing required columns: {', '.join(sorted(missing))}")

    # Finalized periods are loaded once. Only needed when no explicit period was
    # given — an explicit finalized period is refused by the caller up front.
    finalized_spans = []
    if reporting_period is None and not dry_run:
        finalized_spans = list(
            ReportingPeriod.objects.filter(is_finalized=True).values_list(
                "start_date", "end_date", "name"
            )
        )

    for line_num, row in enumerate(reader, start=2):
        row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        row_errors = []
        parcel_number = row.get("parcel_number", "")
        effective_date_raw = row.get("effective_date", "")
        amount_raw = row.get("amount_acre_feet", "")
        source_type = row.get("source_type", "")
        water_type_code = row.get("water_type_code", "")
        description = row.get("description", "")
        transaction_date_raw = row.get("transaction_date", "")

        # Parcel
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
                row_errors.append(f"parcel not found: {parcel_number}")

        # Amount
        amount = None
        if not amount_raw:
            row_errors.append("missing amount_acre_feet")
        else:
            try:
                amount = Decimal(amount_raw)
            except InvalidOperation:
                row_errors.append(f"invalid amount: {amount_raw}")

        # Source type
        if not source_type:
            row_errors.append("missing source_type")
        elif source_type not in valid_source_types:
            row_errors.append(f"invalid source_type: {source_type}")

        # Sign rule (see module docstring). Runs only on an otherwise-parseable
        # amount and a known source_type, so a garbage row reports its real
        # problem instead of a confusing sign message.
        if amount is not None and source_type in valid_source_types:
            if source_type in NON_POSITIVE_SOURCE_TYPES and amount > 0:
                amount = -amount
                sign_normalized += 1
            elif source_type in POSITIVE_SOURCE_TYPES and amount < 0:
                amount = -amount
                sign_normalized += 1

        # Effective date
        effective_date = None
        if not effective_date_raw:
            row_errors.append("missing effective_date")
        else:
            effective_date = parse_date(effective_date_raw)
            if effective_date is None:
                row_errors.append(f"invalid effective_date: {effective_date_raw}")

        # Finalized-period guard
        if effective_date is not None and finalized_spans:
            hit = next(
                (n for (s, e, n) in finalized_spans if s <= effective_date <= e),
                None,
            )
            if hit:
                row_errors.append(
                    f"effective_date {effective_date} falls inside finalized "
                    f"reporting period '{hit}' — that number is already filed"
                )

        # Optional water type
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
                row_errors.append(f"water_type not found: {water_type_code}")

        # Optional transaction date
        transaction_date = None
        if transaction_date_raw:
            transaction_date = parse_date(transaction_date_raw)
            if transaction_date is None:
                row_errors.append(
                    f"invalid transaction_date: {transaction_date_raw}"
                )

        if row_errors:
            errors.append({"line": line_num, "messages": row_errors})
            continue

        if transaction_date is None:
            transaction_date = effective_date

        # Quantize to the column's 4dp so the dedup key matches what the DB
        # stores (a re-run's parsed value lines up with the stored one).
        amount_q = amount.quantize(Decimal("0.0001"))
        key = (parcel.id, effective_date, source_type, amount_q)
        entries_to_create.append(
            (
                key,
                ParcelLedger(
                    parcel=parcel,
                    transaction_date=transaction_date,
                    effective_date=effective_date,
                    amount_acre_feet=amount_q,
                    water_type=water_type,
                    source_type=source_type,
                    description=description,
                    reporting_period=reporting_period,
                ),
            )
        )

        if len(preview) < 5:
            preview.append(
                {
                    "parcel_number": parcel_number,
                    "effective_date": effective_date,
                    "amount": amount_q,
                    "source_type": source_type,
                }
            )

    # Dedup against what is already stored, and within the file itself.
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

    # One transaction so a mid-import failure can't leave a half-written ledger.
    if not dry_run and survivors:
        batch_size = 500
        with transaction.atomic():
            for i in range(0, len(survivors), batch_size):
                ParcelLedger.objects.bulk_create(survivors[i : i + batch_size])

    return {
        "created_count": len(survivors),
        "error_count": len(errors),
        "errors": errors,
        "preview": preview,
        "skipped_duplicate": skipped_duplicate,
        "sign_normalized": sign_normalized,
    }
