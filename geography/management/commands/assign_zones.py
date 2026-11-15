# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assign use areas to zones by location: the Zones page's action, as a command.

    manage.py assign_zones --zone-type management_area

Runs the page's own functions (``geography/zone_assign.py``): each use area goes to the
zone of the type that holds most of its area. It prints the preview's lines, then the
result line the page shows.
"""
from django.core.management.base import BaseCommand

from geography import zone_assign
from geography.models import Zone


class Command(BaseCommand):
    help = "Assign each use area to the zone of the chosen type that holds most of its area."

    def add_arguments(self, parser):
        parser.add_argument(
            "--zone-type", required=True, choices=[value for value, _ in Zone.ZONE_TYPE_CHOICES]
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        planned = zone_assign.plan(options["zone_type"])
        for count, what, action in zone_assign.preview_lines(planned):
            self.stdout.write(f"{count:,} {what}: {action}")
        if planned["across"]:
            self.stdout.write(zone_assign.across_sentence(len(planned["across"]), planned["to_assign"]))
        if options["dry_run"]:
            self.stdout.write("Dry run: OpenH2O did not save anything.")
            return
        created = zone_assign.assign(planned)
        self.stdout.write(zone_assign.result_sentence(created))
        if planned["outside"]:
            self.stdout.write(zone_assign.outside_sentence(len(planned["outside"])))
