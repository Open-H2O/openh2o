# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports ParcelLedger rows from a CSV file.

An operator runs it to bulk-load supply and use entries against existing
parcels; it validates each row, supports a ``--dry-run`` preview, refuses to
write into a finalized (state-filed) reporting period, and is idempotent so
re-importing the same CSV skips duplicate (parcel, date, source, amount) rows.

The rules themselves live in ``accounting.ledger_import``, shared with the web
upload so a file behaves identically through either door. This command owns only
the CLI surface: arguments, the up-front refusal of an explicitly-named finalized
period, and stdout formatting.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from accounting.ledger_import import import_ledger_rows
from accounting.models import ReportingPeriod


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

        # Everything below the argument handling is the shared import service,
        # so a file behaves identically here and through the web upload (math
        # eval item 3). The per-row finalized-period guard, the sign rule and the
        # dedup all live in accounting.ledger_import.
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            result = import_ledger_rows(
                f,
                reporting_period=reporting_period,
                dry_run=dry_run,
                delimiter=delimiter,
            )

        created_count = result["created_count"]
        skipped_count = result["error_count"]
        skipped_duplicate = result["skipped_duplicate"]
        sign_normalized = result["sign_normalized"]

        # Report errors
        for err in result["errors"]:
            self.stdout.write(
                self.style.ERROR(
                    f"  Line {err['line']}: {'; '.join(err['messages'])}"
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
        if sign_normalized:
            # Surfaced, never silent: the operator needs to know the file's signs
            # did not match the ledger's convention before they trust the totals.
            self.stdout.write(
                self.style.WARNING(
                    f"  {sign_normalized} row(s) had their sign normalized to the "
                    f"ledger convention (usage debits, supply credits)"
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
