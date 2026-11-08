# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import water rights from a CSV file, through the Water Rights Import screen's code.

    python manage.py import_water_rights FILE [--column FIELD=COLUMN ...] [--dry-run]

The screen's worker calls ``surface.importer.import_rights``; so does this.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core import import_commands
from surface import importer


class Command(BaseCommand):
    help = (
        "Import water rights from the CSV list of water rights that eWRIMS exports. "
        "The Water Rights Import screen reads the same file."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", help="The path of the CSV file inside the container.")
        parser.add_argument(
            "--column",
            action="append",
            default=[],
            help=(
                "Name the column that holds one of the values OpenH2O reads. "
                "Write OpenH2O's name for the value, an equals sign and the column name, "
                "such as net_acreage=ACRES. Give --column once for each value. "
                "A dry run lists OpenH2O's name for each value and the column "
                "the command reads for it."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report what the import would do. "
                "The command does not save any record during a dry run."
            ),
        )

    def handle(self, *args, **options):
        path = options["file"]
        dry_run = options["dry_run"]
        import_commands.require_file(path)

        try:
            with open(path, "rb") as handle:
                parsed = importer.parse_upload(handle, os.path.basename(path))
        except ImportError as exc:
            raise CommandError(str(exc))

        columns = parsed["columns"]
        fields = [field for field, _label in importer.import_fields()]
        mapping = importer.auto_map_columns(columns)
        overrides = import_commands.column_overrides(options["column"], fields)
        import_commands.check_columns(overrides, columns)
        mapping.update(overrides)

        if dry_run:
            self.stdout.write("[DRY RUN] The command does not save any record.")
        import_commands.write_columns(self.stdout, fields, mapping)

        outcome = importer.import_rights(parsed["rows"], mapping, dry_run=dry_run)
        import_commands.write_rows(self.stdout, outcome["skipped"])
        import_commands.write_rows(self.stdout, outcome["noted"])

        skipped = import_commands.count(len(outcome["skipped"]), "row", "rows")
        if dry_run:
            would = import_commands.count(
                outcome["total"] - len(outcome["skipped"]),
                "water right record",
                "water right records",
            )
            self.stdout.write(f"OpenH2O would create {would} and skip {skipped}.")
        else:
            made = import_commands.count(
                outcome["created"], "water right record", "water right records"
            )
            self.stdout.write(f"OpenH2O created {made} and skipped {skipped}.")

        if outcome["noted"]:
            n = len(outcome["noted"])
            if n == 1:
                self.stdout.write("1 row has a note.")
            else:
                self.stdout.write(f"{n} rows have a note.")
