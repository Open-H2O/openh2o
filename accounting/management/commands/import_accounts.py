# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import water accounts and their use areas from a CSV file: the Accounts page's
Import accounts, as a command.

    manage.py import_accounts accounts.csv --account-type farm_unit
    manage.py import_accounts accounts.csv --account-type farm_unit --column account_number=Acct

Runs the page's own functions (``accounting/account_import.py``), so it writes what the
page would. Columns are matched by their headings as on the page; ``--column
FIELD=HEADING`` names one that differs (fields: parcel_number, account_number,
account_name, contact_name, contact_email). It prints the preview's lines, then the
result line the page shows.
"""
import os

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from accounting import account_import
from accounting.models import UNIT_KIND_CHOICES


class Command(BaseCommand):
    help = "Import water accounts and the use areas in each from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--account-type", required=True, choices=[value for value, _ in UNIT_KIND_CHOICES])
        parser.add_argument("--column", action="append", default=[])
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = options["path"]
        try:
            with open(path, "rb") as handle:
                read = account_import.read_file(File(handle, name=os.path.basename(path)))
        except (ImportError, OSError) as exc:
            raise CommandError(str(exc))
        mapping = account_import.auto_map(read["columns"])
        fields = {field for field, _, _ in account_import.FIELDS}
        for item in options["column"]:
            field, _, heading = item.partition("=")
            if field not in fields or heading not in read["columns"]:
                raise CommandError(f"--column {item}: {', '.join(sorted(fields))}; {', '.join(read['columns'])}")
            mapping[field] = heading
        plan = account_import.plan_accounts(read["rows"], mapping)
        for count, what, action in account_import.account_lines(plan):
            self.stdout.write(f"{count:,} {what}: {action}")
        if plan["differing"]:
            self.stdout.write(account_import.differing_sentence(plan))
            for item in account_import.differing_items(plan):
                self.stdout.write(f"  {item}")
        if plan["bad_email"]:
            self.stdout.write(account_import.bad_email_sentence(plan))
        for count, what, action, items, _ in account_import.row_lines(plan):
            self.stdout.write(f"{count:,} {what}: {action}")
            for item in items:
                self.stdout.write(f"  {item}")
        if options["dry_run"]:
            self.stdout.write("Dry run: OpenH2O did not save anything.")
            return
        try:
            made, assigned = account_import.write_accounts(plan, options["account_type"])
        except ImportError as exc:
            raise CommandError(str(exc))
        self.stdout.write(account_import.result_sentence(made, assigned))
        if plan["left_out"]:
            self.stdout.write(account_import.left_out_sentence(plan["left_out"]))
