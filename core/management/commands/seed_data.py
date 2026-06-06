# SPDX-License-Identifier: AGPL-3.0-or-later
"""Umbrella management command that runs every reference-data seed command.

An operator runs it once during setup to load all baseline lookup tables in
order (roles, water types, water-right types, well types, data sources, report
templates); each underlying command is idempotent, so re-running is safe.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand

SEED_COMMANDS = [
    "seed_roles",
    "seed_water_types",
    "seed_water_right_types",
    "seed_well_types",
    "seed_data_sources",
    "seed_report_templates",
]


class Command(BaseCommand):
    help = "Run all seed data commands"

    def handle(self, *args, **options):
        for cmd in SEED_COMMANDS:
            self.stdout.write(f"\n--- {cmd} ---")
            call_command(cmd, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("\nAll seed data loaded."))
