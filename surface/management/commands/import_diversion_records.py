# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports DiversionRecord rows from a CSV file.

An operator (or the AI operator, ISS-190) runs this to bulk-load a year of
the state's own Water Use Reported figures, or a ditch tender's own book,
against a point of diversion. The rules -- layout recognition, unit
conversions, the USE-type rule, dedup -- live in ``surface.diversion_import``,
shared with the web upload (``/surface/diversion/import/``) so a file behaves
identically through either door.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from surface.diversion_import import import_diversion_rows, parse_csv
from surface.models import PointOfDiversion


class Command(BaseCommand):
    help = "Import diversion records (the state's Water Use Reported layout or a ditch tender's book) from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to the CSV file.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate and report only; write nothing.",
        )
        parser.add_argument(
            "--point", type=int, default=None,
            help="Point of diversion pk to use for a row that has no other "
                 "way to resolve one (the whole-file point).",
        )
        parser.add_argument(
            "--method", type=str, default="",
            help="Method for every created record (blank = not stated).",
        )
        parser.add_argument(
            "--data-state", type=str, default="provisional",
            help="Data state for every created record (default: provisional).",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]
        method = options["method"]
        data_state = options["data_state"]

        if not os.path.exists(file_path):
            # ISS-190: a bare path only ever resolves inside the container --
            # every prior importer's docs learned this the hard way. Named
            # here so a CommandError alone is never the whole story again.
            raise CommandError(
                f"File not found: {file_path}\n"
                "The web container has no bind mount to your host filesystem. "
                "Copy the file in first: "
                f"docker compose cp {file_path} web:/tmp/, then re-run this "
                "command with the /tmp/ path inside the container."
            )

        whole_file_point = None
        if options["point"] is not None:
            try:
                whole_file_point = PointOfDiversion.objects.get(pk=options["point"])
            except PointOfDiversion.DoesNotExist:
                raise CommandError(f"No point of diversion with pk {options['point']}.")

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be written."))

        with open(file_path, newline="", encoding="utf-8-sig") as f:
            try:
                columns, rows = parse_csv(f, file_path)
            except ImportError as exc:
                raise CommandError(str(exc))

        try:
            result = import_diversion_rows(
                columns, rows,
                whole_file_point=whole_file_point,
                method=method,
                data_state=data_state,
                dry_run=dry_run,
            )
        except ImportError as exc:
            raise CommandError(str(exc))

        action = "Would create" if dry_run else "Created"
        self.stdout.write(f"Layout recognised: {result['layout']}")
        self.stdout.write(result["rule_sentence"])
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {result['created']} record(s), "
                f"{result['skipped_duplicates']} skipped as duplicates, "
                f"{len(result['errors'])} row(s) with errors, "
                f"{len(result['unresolved_rows'])} row(s) unresolved"
            )
        )
        if result["use_rows_dropped"]:
            self.stdout.write(
                f"  {result['use_rows_dropped']} USE row(s) dropped "
                "(diversion_use_type_rule = drop)"
            )
        for row in result["combined_rows"]:
            self.stdout.write(
                f"  {row['point']} {row['month']} {row['diversion_type']}: "
                f"{row['row_count']} rows combined into one month "
                f"(source rows {row['rows']})"
            )
        for conv in result["conversions"]:
            self.stdout.write(
                f"  Row {conv['line']}: {conv['from']} -> {conv['to']} "
                f"({conv['factor']}) = {conv['value']}"
            )
        for row in result["unresolved_rows"]:
            self.stdout.write(self.style.WARNING(f"  Row {row['line']}: {row['reason']}"))
        for err in result["errors"]:
            self.stdout.write(self.style.ERROR(f"  Row {err['line']}: {err['message']}"))
        for period_name, count in result["periods_attached"].items():
            self.stdout.write(f"  {count} record(s) attached to '{period_name}'")
