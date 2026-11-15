# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import zones from a map file: the Zones page's Import zones, as a command.

    manage.py import_zones gsa-boundaries.geojson --name-column GSA_Name --zone-type management_area

Runs the page's own functions (``geography/zone_import.py``), so it makes the zones the
page would. It prints the preview's lines, then the result line the page shows.
"""
import os

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from geography import zone_import
from geography.models import Zone


class Command(BaseCommand):
    help = "Import zones from a map file, one zone for each name in it."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--name-column", default="")
        parser.add_argument(
            "--zone-type", required=True, choices=[value for value, _ in Zone.ZONE_TYPE_CHOICES]
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = options["path"]
        try:
            with open(path, "rb") as handle:
                read = zone_import.read_file(File(handle, name=os.path.basename(path)))
        except (ImportError, OSError) as exc:
            raise CommandError(str(exc))
        name_column = options["name_column"] or zone_import.guess_name_column(read["columns"])
        if name_column not in read["columns"]:
            raise CommandError(f"{name_column}: {', '.join(read['columns'])}")
        plan = zone_import.plan_zones(read["features"], name_column, options["zone_type"])
        for count, what, action in zone_import.preview_lines(plan):
            self.stdout.write(f"{count:,} {what}: {action}")
        for name, count in plan["shared"]:
            self.stdout.write(zone_import.shared_sentence(name, count))
        if options["dry_run"]:
            self.stdout.write("Dry run: OpenH2O did not save anything.")
            return
        try:
            created = zone_import.write_zones(plan, options["zone_type"])
        except ImportError as exc:
            raise CommandError(str(exc))
        self.stdout.write(zone_import.result_sentence(created, plan["left_out"]))
