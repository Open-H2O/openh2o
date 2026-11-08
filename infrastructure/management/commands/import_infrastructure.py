# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import wells, points of diversion, storage ponds or recharge sites from a file.

    python manage.py import_infrastructure FILE --type TYPE [--column FIELD=COLUMN ...] [--dry-run]

The screen's worker calls ``infrastructure.importer.import_infrastructure``; so does this.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core import import_commands
from infrastructure import importer
from infrastructure.views import UNSUPPORTED_IMPORT_TYPE_MESSAGE, supported_add_types

NOUNS = {
    "well": ("well", "wells"),
    "diversion": ("point of diversion", "points of diversion"),
    "storage": ("storage pond", "storage ponds"),
    "recharge_site": ("recharge site", "recharge sites"),
}


class Command(BaseCommand):
    help = (
        "Import wells, points of diversion, storage ponds or recharge sites from a CSV file, "
        "a GeoJSON file, a zipped shapefile or a KML file. "
        "The Import screen reads the same files."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", help="The path of the file inside the container.")
        parser.add_argument(
            "--type",
            dest="infra_type",
            required=True,
            choices=list(NOUNS),
            help="The kind of record in the file: well, diversion, storage or recharge_site.",
        )
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
        infra_type = options["infra_type"]
        dry_run = options["dry_run"]
        import_commands.require_file(path)

        # The screen's own check for a type this deployment does not run.
        if infra_type not in supported_add_types():
            raise CommandError(UNSUPPORTED_IMPORT_TYPE_MESSAGE)

        try:
            with open(path, "rb") as handle:
                parsed = importer.parse_upload(handle, os.path.basename(path))
        except ImportError as exc:
            raise CommandError(str(exc))

        columns = parsed["columns"]
        fields = [field for field, _label, _required in importer.import_fields(infra_type)]
        mapping = importer.auto_map_columns(columns, infra_type)
        overrides = import_commands.column_overrides(options["column"], fields)
        import_commands.check_columns(overrides, columns)
        mapping.update(overrides)

        if dry_run:
            self.stdout.write("[DRY RUN] The command does not save any record.")
        import_commands.write_columns(self.stdout, fields, mapping)

        results, created = importer.import_infrastructure(
            parsed["rows"], mapping, infra_type, dry_run=dry_run
        )
        skipped = [
            {"index": r["index"], "errors": r["errors"]} for r in results if r["errors"]
        ]
        noted = [
            {"index": r["index"], "warnings": r["warnings"]}
            for r in results
            if r["warnings"] and not r["errors"]
        ]
        import_commands.write_rows(self.stdout, skipped)
        import_commands.write_rows(self.stdout, noted)

        singular, plural = NOUNS[infra_type]
        skipped_text = import_commands.count(len(skipped), "row", "rows")
        if dry_run:
            would = import_commands.count(len(results) - len(skipped), singular, plural)
            self.stdout.write(f"OpenH2O would create {would} and skip {skipped_text}.")
        else:
            made = import_commands.count(created, singular, plural)
            self.stdout.write(f"OpenH2O created {made} and skipped {skipped_text}.")
