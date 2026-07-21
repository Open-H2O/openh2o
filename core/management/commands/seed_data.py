# SPDX-License-Identifier: AGPL-3.0-or-later
"""Umbrella management command that runs every reference-data seed command.

An operator runs it once during setup to load all baseline lookup tables in
order (roles, water types, water-right types, well types, data sources, report
templates); each underlying command is idempotent, so re-running is safe.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.modules import is_enabled

SEED_COMMANDS = [
    "seed_roles",
    "seed_water_types",
    "seed_well_types",
    "seed_data_sources",
]

#: Seed commands owned by a module a deployment can switch off. Gated rather
#: than listed above, so a district running without `drinking` still seeds
#: cleanly instead of failing on a management command that does not exist.
OPTIONAL_SEED_COMMANDS = [
    ("drinking", "seed_drinking"),
    # Phase 87. `seed_water_right_types` is owned by `surface`; with the module
    # dropped the command does not exist and `make seed` died on it. Running it
    # after the ungated block is safe — verified 2026-07-21 that no other seed
    # command references WaterRightType.
    ("surface", "seed_water_right_types"),
    # Plan 88-01, deviation rule 1. `seed_report_templates` is owned by
    # `reporting`, which has been optional since Phase 77 — but the command sat
    # in the ungated block above, so `make seed` on a deployment that dropped
    # reporting died with `CommandError: Unknown command:
    # 'seed_report_templates'`. Measured on main 2026-07-21, identical in shape
    # to the `surface` defect one line up. Nothing else references
    # ReportTemplate during seeding, so running it after the ungated block is
    # safe.
    ("reporting", "seed_report_templates"),
]


class Command(BaseCommand):
    help = "Run all seed data commands"

    def handle(self, *args, **options):
        commands = list(SEED_COMMANDS) + [
            cmd for module, cmd in OPTIONAL_SEED_COMMANDS if is_enabled(module)
        ]
        for cmd in commands:
            self.stdout.write(f"\n--- {cmd} ---")
            call_command(cmd, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("\nAll seed data loaded."))
