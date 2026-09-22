# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports SystemProduction rows from a CSV file.

An operator (or the AI operator) runs this to bulk-load a year of the
state's own eAR production export, or the operator's own monthly log,
against a water system. The rules -- layout recognition, unit conversions,
dedup -- live in ``drinking.production_import``, shared with the web upload
(``/drinking/production/import/``) so a file behaves identically through
either door.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from drinking.production_import import import_production_rows, parse_csv
from drinking.models import WaterSystem


class Command(BaseCommand):
    help = (
        "Import production by month and source (the state's eAR export or "
        "the operator's own monthly log) from a CSV file."
    )

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to the CSV file.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate and report only; write nothing.",
        )
        parser.add_argument(
            "--pwsid", type=str, default=None,
            help="The water system's PWSID. Defaults to the deployment's "
                 "only WaterSystem when there is exactly one.",
        )
        parser.add_argument(
            "--unit-for-blank", type=str, default=None,
            help="Unit to use for an eAR row whose own unit column is blank "
                 "(G, MG, AF, or CCF).",
        )
        parser.add_argument(
            "--operator-year", type=int, default=None,
            help="Report year for an operator's-log file, which carries no "
                 "year of its own.",
        )
        parser.add_argument(
            "--operator-unit", type=str, default="G",
            help="Unit for every row of an operator's-log file (default: G, "
                 "gallons).",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]

        if not os.path.exists(file_path):
            raise CommandError(
                f"File not found: {file_path}\n"
                "The web container has no bind mount to your host filesystem. "
                "Copy the file in first: "
                f"docker compose cp {file_path} web:/tmp/, then re-run this "
                "command with the /tmp/ path inside the container."
            )

        if options["pwsid"]:
            try:
                system = WaterSystem.objects.get(pwsid=options["pwsid"])
            except WaterSystem.DoesNotExist:
                raise CommandError(f"No water system with PWSID {options['pwsid']!r}.")
        else:
            count = WaterSystem.objects.count()
            if count != 1:
                raise CommandError(
                    f"This deployment carries {count} water system(s); pass "
                    "--pwsid to say which one."
                )
            system = WaterSystem.objects.get()

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be written."))

        with open(file_path, newline="", encoding="utf-8-sig") as f:
            try:
                columns, rows = parse_csv(f, file_path)
            except ImportError as exc:
                raise CommandError(str(exc))

        try:
            result = import_production_rows(
                columns, rows, system=system,
                unit_for_blank=options["unit_for_blank"],
                operator_year=options["operator_year"],
                operator_unit=options["operator_unit"],
                dry_run=dry_run,
            )
        except ImportError as exc:
            raise CommandError(str(exc))

        action = "Would create" if dry_run else "Created"
        self.stdout.write(f"Layout recognised: {result['layout']}")
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {result['created']} record(s), "
                f"{result['skipped_duplicates']} skipped as duplicates, "
                f"{len(result['errors'])} row(s) with errors, "
                f"{result['duplicate_rows_in_file']} duplicate row(s) within the file"
            )
        )
        for row in result["skipped_rows"]:
            self.stdout.write(f"  Row {row['line']}: {row['label']!r} is not a month; skipped")
        for err in result["errors"]:
            self.stdout.write(self.style.ERROR(f"  Row {err['line']}: {err['message']}"))
