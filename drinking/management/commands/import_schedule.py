# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import the state's sampling schedule through the Import the state's schedule screen's code.

    python manage.py import_schedule FILE [--dry-run] [--pwsid PWSID]

The screen's preview and its worker call ``drinking.schedule_import.import_schedule_rows``;
so does this.
"""
from django.core.management.base import BaseCommand, CommandError

from core import import_commands
from drinking import schedule_import
from drinking.models import WaterSystem


class Command(BaseCommand):
    help = (
        "Import the state's sampling schedule from its Last and Next Sample "
        "Report as a CSV file. The import screen at /drinking/schedule/import/ "
        "does the same import."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", help="The path to the CSV file inside the container.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "List what the import would add and change. "
                "The command does not save any row during a dry run."
            ),
        )
        parser.add_argument(
            "--pwsid",
            default=None,
            help=(
                "The water system's PWSID. Leave it out when the site keeps "
                "one water system."
            ),
        )

    def handle(self, *args, **options):
        path = options["file"]
        dry_run = options["dry_run"]
        import_commands.require_file(path)

        if options["pwsid"]:
            try:
                system = WaterSystem.objects.get(pwsid=options["pwsid"])
            except WaterSystem.DoesNotExist:
                raise CommandError(f"No water system with PWSID {options['pwsid']!r}.")
        else:
            systems = WaterSystem.objects.count()
            if systems != 1:
                raise CommandError(
                    f"This deployment carries {systems} water system(s); pass "
                    "--pwsid to say which one."
                )
            system = WaterSystem.objects.get()

        try:
            with open(path, "rb") as handle:
                columns, rows = schedule_import.parse_csv(handle, path)
            plan = schedule_import.import_schedule_rows(
                columns, rows, system=system, dry_run=dry_run
            )
        except ImportError as exc:
            raise CommandError(str(exc))

        # The spreadsheet's row number, the column names being row 1.
        import_commands.write_rows(
            self.stdout,
            [{"index": e["line"] - 2, "errors": e["messages"]} for e in plan["errors"]],
        )
        for entry in plan["changed"]:
            item, row = entry["item"], entry["existing"]
            for field, old, new in entry["changes"]:
                self.stdout.write(
                    f"Row {item['index'] + 2}: {row.label} at "
                    f"{schedule_import.point_text(row)}. {field}: {old} to {new}."
                )
        for row in plan["left_out"]:
            self.stdout.write(
                f"Not in this file: {row.label} at {schedule_import.point_text(row)}. "
                "OpenH2O leaves it as it is."
            )
        if plan["unchanged"]:
            self.stdout.write(
                f"{import_commands.count(plan['unchanged'], 'row', 'rows')} "
                + ("is" if plan["unchanged"] == 1 else "are")
                + " already on the schedule with the same frequency and dates."
            )

        added = import_commands.count(plan["added"], "row", "rows")
        changed = import_commands.count(plan["changed_count"], "row", "rows")
        if dry_run:
            self.stdout.write(
                f"OpenH2O would add {added} to the schedule and change {changed}."
            )
        else:
            skipped = import_commands.count(plan["error_row_count"], "row", "rows")
            self.stdout.write(
                f"OpenH2O added {added} to the schedule, changed {changed} and "
                f"skipped {skipped} with errors."
            )
