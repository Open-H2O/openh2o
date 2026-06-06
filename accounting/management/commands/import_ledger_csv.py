# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports ParcelLedger rows from a CSV file.

An operator runs it to bulk-load supply and use entries against existing
parcels; it validates each row, supports a ``--dry-run`` preview, refuses to
write into a finalized (state-filed) reporting period, and is idempotent so
re-importing the same CSV skips duplicate (parcel, date, source, amount) rows.
"""
import csv
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.models import ReportingPeriod, WaterType
from parcels.models import Parcel, ParcelLedger


class Command(BaseCommand):
    help = "Import ledger entries from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the CSV file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate only, do not create records.",
        )
        parser.add_argument(
            "--reporting-period",
            type=str,
            default=None,
            help="Name of the reporting period to assign to all entries.",
        )
        parser.add_argument(
            "--delimiter",
            type=str,
            default=",",
            help="CSV delimiter (default: comma).",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]
        period_name = options["reporting_period"]
        delimiter = options["delimiter"]

        if not os.path.exists(file_path):
            raise CommandError(f"File not found: {file_path}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("[DRY RUN] No records will be written.")
            )

        # Resolve reporting period if specified
        reporting_period = None
        if period_name:
            try:
                reporting_period = ReportingPeriod.objects.get(name=period_name)
            except ReportingPeriod.DoesNotExist:
                raise CommandError(
                    f"Reporting period not found: {period_name}"
                )

        # ISS-029 finalized-period write guard. A finalized ReportingPeriod is a
        # number already filed with the state; importing into it would silently
        # rewrite a filed figure. Mirror the run_calculations guard: refuse up
        # front when the operator explicitly targets a finalized period. dry_run
        # is never blocked (it writes nothing). When NO period is named, rows
        # carry reporting_period=None, so instead guard per-row by date below.
        if (
            reporting_period is not None
            and reporting_period.is_finalized
            and not dry_run
        ):
            filed = (
                f" (filed {reporting_period.finalized_at:%Y-%m-%d})"
                if reporting_period.finalized_at
                else ""
            )
            raise CommandError(
                f"Refusing to import into reporting period "
                f"'{reporting_period.name}': it is finalized{filed}. Importing "
                f"would overwrite a number already filed with the state."
            )

        # When no period is named, protect any finalized period by date: a row
        # whose effective_date falls inside a finalized period is refused (and
        # reported as a row error), so a re-import can't slip rows into a filed
        # month. Loaded once; empty list = no per-row check.
        finalized_spans = []
        if reporting_period is None and not dry_run:
            finalized_spans = list(
                ReportingPeriod.objects.filter(is_finalized=True).values_list(
                    "start_date", "end_date", "name"
                )
            )

        # Cache lookups
        parcel_cache = {}
        water_type_cache = {}
        valid_source_types = {
            choice[0] for choice in ParcelLedger.SOURCE_TYPE_CHOICES
        }

        created_count = 0
        skipped_count = 0
        error_rows = []
        entries_to_create = []

        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=delimiter)

            # Validate required columns
            required_columns = {
                "parcel_number",
                "effective_date",
                "amount_acre_feet",
                "source_type",
            }
            if reader.fieldnames is None:
                raise CommandError("CSV file appears empty or has no headers.")
            actual_columns = {c.strip().lower() for c in reader.fieldnames}
            missing = required_columns - actual_columns
            if missing:
                raise CommandError(
                    f"Missing required columns: {', '.join(sorted(missing))}"
                )

            for line_num, row in enumerate(reader, start=2):
                # Normalize keys
                row = {k.strip().lower(): v.strip() for k, v in row.items()}

                errors = []
                parcel_number = row.get("parcel_number", "")
                effective_date_raw = row.get("effective_date", "")
                amount_raw = row.get("amount_acre_feet", "")
                source_type = row.get("source_type", "")
                water_type_code = row.get("water_type_code", "")
                description = row.get("description", "")
                transaction_date_raw = row.get("transaction_date", "")

                # Validate parcel
                parcel = None
                if not parcel_number:
                    errors.append("missing parcel_number")
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
                        errors.append(f"parcel not found: {parcel_number}")

                # Validate amount
                amount = None
                if not amount_raw:
                    errors.append("missing amount_acre_feet")
                else:
                    try:
                        amount = Decimal(amount_raw)
                    except InvalidOperation:
                        errors.append(f"invalid amount: {amount_raw}")

                # Validate effective_date
                effective_date = None
                if not effective_date_raw:
                    errors.append("missing effective_date")
                else:
                    effective_date = self._parse_date(effective_date_raw)
                    if effective_date is None:
                        errors.append(
                            f"invalid effective_date: {effective_date_raw}"
                        )

                # ISS-029: refuse a row dated inside a finalized period (only
                # checked when no explicit --reporting-period was given).
                if effective_date is not None and finalized_spans:
                    hit = next(
                        (
                            n
                            for (s, e, n) in finalized_spans
                            if s <= effective_date <= e
                        ),
                        None,
                    )
                    if hit:
                        errors.append(
                            f"effective_date {effective_date} is inside "
                            f"finalized period '{hit}'; refusing to write to a "
                            f"filed period"
                        )

                # Validate source_type
                if not source_type:
                    errors.append("missing source_type")
                elif source_type not in valid_source_types:
                    errors.append(f"invalid source_type: {source_type}")

                # Validate water_type_code (optional)
                water_type = None
                if water_type_code:
                    if water_type_code not in water_type_cache:
                        try:
                            water_type_cache[water_type_code] = (
                                WaterType.objects.get(code=water_type_code)
                            )
                        except WaterType.DoesNotExist:
                            water_type_cache[water_type_code] = None
                    water_type = water_type_cache[water_type_code]
                    if water_type is None:
                        errors.append(
                            f"water_type not found: {water_type_code}"
                        )

                # Parse optional transaction_date
                transaction_date = None
                if transaction_date_raw:
                    transaction_date = self._parse_date(transaction_date_raw)
                    if transaction_date is None:
                        errors.append(
                            f"invalid transaction_date: {transaction_date_raw}"
                        )

                if errors:
                    error_rows.append((line_num, errors))
                    skipped_count += 1
                    continue

                # Use effective_date as fallback for transaction_date
                if transaction_date is None:
                    transaction_date = effective_date

                # Quantize to the column's 4dp so the dedup key matches what the
                # DB stores (a re-run's parsed value lines up with the stored one).
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

        # ISS-029 idempotency (dedup-skip). The ledger is an append-only journal,
        # not authoritative state for a key, so we never delete — we skip a row
        # that already exists with the same (parcel, effective_date, source_type,
        # amount) and collapse exact duplicates within this file. Re-importing the
        # same CSV writes nothing the second time, while a genuinely corrected
        # amount (a different key) still lands. Keying on amount is the 44-AUDIT
        # recommendation. One query loads the existing keys for the file's parcels.
        skipped_duplicate = 0
        survivors = []
        if entries_to_create:
            parcel_ids = {key[0] for key, _entry in entries_to_create}
            existing = set(
                ParcelLedger.objects.filter(
                    parcel_id__in=parcel_ids
                ).values_list(
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

        # Bulk create the survivors in batches, in one transaction so a mid-import
        # failure can't leave a half-written ledger.
        if not dry_run and survivors:
            batch_size = 500
            with transaction.atomic():
                for i in range(0, len(survivors), batch_size):
                    batch = survivors[i : i + batch_size]
                    ParcelLedger.objects.bulk_create(batch)
        created_count = len(survivors)

        # Report errors
        for line_num, errs in error_rows:
            self.stdout.write(
                self.style.ERROR(
                    f"  Line {line_num}: {'; '.join(errs)}"
                )
            )

        action = "Would create" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {created_count} entries, "
                f"{skipped_count} skipped with errors, "
                f"{skipped_duplicate} skipped as duplicates"
            )
        )

    @staticmethod
    def _parse_date(date_str):
        """Parse a date string in YYYY-MM-DD or MM/DD/YYYY format."""
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None
