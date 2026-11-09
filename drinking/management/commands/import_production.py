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

from core.import_commands import check_columns, column_overrides, write_columns
from drinking.models import WaterSystem
from drinking.production_import import (
    import_production_rows,
    parse_csv,
    recognise_layout,
)

#: ``--column`` names -> the type of water each one holds (``month`` is the month column).
COLUMN_TYPES = {
    "groundwater": "GW",
    "surface_water": "SW",
    "purchased": "PU",
    "sold": "SO",
    "non_potable": "NP",
    "recycled": "RC",
    "non_potable_sold": "NS",
}
COLUMN_NAMES = ["month", *COLUMN_TYPES]


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
            "--operator-unit", type=str, default=None,
            help="The unit of every figure in a monthly log: G, MG, AF or CCF. "
                 "When --operator-unit is left out, OpenH2O reads a log on the "
                 "eAR template in gallons. A log with its own column headings "
                 "needs --operator-unit.",
        )
        parser.add_argument(
            "--column", action="append", default=None, metavar="NAME=COLUMN",
            help="For a log with its own column headings, give one --column for "
                 "each column you want imported. Write each --column as "
                 "OpenH2O's name for a value, an equals sign and a column name. "
                 "The names are month, groundwater, surface_water, purchased, "
                 "sold, non_potable, recycled and non_potable_sold.",
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

        layout = recognise_layout(columns)
        mapping = None
        if layout == "mapped":
            overrides = column_overrides(options["column"], COLUMN_NAMES)
            if not overrides:
                raise CommandError(
                    "OpenH2O does not know the columns in this file: "
                    + ", ".join(columns)
                    + ". Name the month column and at least one other column "
                    "with --column."
                )
            if not options["operator_unit"]:
                raise CommandError(
                    "A log with its own column headings needs --operator-unit."
                )
            check_columns(overrides, columns)
            write_columns(self.stdout, COLUMN_NAMES, overrides)
            mapping = {
                "month": overrides.get("month", ""),
                "columns": {
                    column: COLUMN_TYPES[name]
                    for name, column in overrides.items()
                    if name != "month"
                },
            }

        try:
            result = import_production_rows(
                columns, rows, system=system, layout=layout,
                unit_for_blank=options["unit_for_blank"],
                operator_year=options["operator_year"],
                operator_unit=options["operator_unit"],
                mapping=mapping,
                dry_run=dry_run,
            )
        except ImportError as exc:
            raise CommandError(str(exc))

        if result["refusals"]:
            raise CommandError("\n".join(result["refusals"]))
        if result["year_missing"]:
            if layout == "mapped":
                raise CommandError(
                    "The month column does not give a year. Pass --operator-year."
                )
            raise CommandError("The log carries no year; pass --operator-year.")

        action = "Would create" if dry_run else "Created"
        # A log with its own headings has no layout name to print: "Columns read:"
        # above already says what the command reads.
        if result["layout"] != "mapped":
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
