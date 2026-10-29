# SPDX-License-Identifier: AGPL-3.0-or-later
"""Umbrella management command that runs every reference-data seed command.

An operator runs it once during setup to load all baseline lookup tables in
order (the observed-property crosswalk, water types, water-right types,
well types, data sources, report templates); each underlying command is
idempotent, so re-running is safe.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.modules import is_enabled

SEED_COMMANDS = [
    # The standards crosswalk — the "born-compliant" claim the README makes, and
    # until now the one seed nothing ran. Not `seed_data`, not `seed_merced`, not
    # the Makefile, not DEPLOY.md: only the test suite called it. An adopter who
    # followed the documented quick start got an empty ObservedProperty registry,
    # and `check_conformance` passed by having nothing to check — a gate reporting
    # PASS on a vocabulary that was never loaded.
    #
    # Ungated rather than in OPTIONAL_SEED_COMMANDS because `standards` is
    # `required=True` and `schema_resident=True` in core/modules.py: it is the
    # vocabulary other modules FK into, so it can never be the module that is
    # missing. Kept out of `MODULE_REGISTRY["standards"].seed_commands`, which
    # `tests/droppability/checks.py` requires to stay empty for a schema-resident
    # module.
    "seed_observed_properties",
]

#: Seed commands owned by a module a deployment can switch off. Gated rather
#: than listed above, so a district running without `drinking` still seeds
#: cleanly instead of failing on a management command that does not exist.
OPTIONAL_SEED_COMMANDS = [
    # Two kinds of gated command, which fail differently when the gate is
    # missing. `surface` and `reporting` are truly removable, so their commands
    # cease to exist and `make seed` would die loudly. `wells`, `datasync` and
    # `accounting` are schema-resident: the apps stay in INSTALLED_APPS,
    # management commands are discovered from INSTALLED_APPS, so their commands
    # still exist and still run, quietly filling the tables of a switched-off
    # module. A crash announces itself; this does not, and only
    # `test_schema_resident_module_tables_are_present_and_empty` can see it.
    # `seed_water_types` is owned by `accounting` (core/modules.py) and is the
    # same quiet kind.
    #
    # The schema-resident commands are listed first so the resolved order on a
    # full deployment is: the observed-property crosswalk, water types, well types, data sources, then
    # the commands below.
    #
    # `parcels` declares NO seed command (`MODULE_REGISTRY["parcels"].seed_commands`
    # is empty), so there is no parcels-side twin.
    ("accounting", "seed_water_types"),
    ("wells", "seed_well_types"),
    ("datasync", "seed_data_sources"),
    ("drinking", "seed_drinking"),
    # `seed_water_right_types` is owned by `surface`; with the module dropped
    # the command does not exist and `make seed` would die on it. Running it
    # after the ungated block is safe: no other command this one runs
    # references WaterRightType.
    ("surface", "seed_water_right_types"),
    # `seed_report_templates` is owned by `reporting`, which is optional. In the
    # ungated block it would make `make seed` on a deployment that dropped
    # reporting die with `CommandError: Unknown command:
    # 'seed_report_templates'`, the same shape as the `surface` case above.
    # Nothing else references ReportTemplate during seeding, so running it
    # after the ungated block is safe.
    ("reporting", "seed_report_templates"),
]


class Command(BaseCommand):
    help = "Run all seed data commands"

    def handle(self, *args, **options):
        commands = list(SEED_COMMANDS)
        # Say what was skipped and why. Without it a deployment with a module
        # off just prints fewer lines, which reads identically to a seed command
        # that was never written, so an operator comparing two deployments could
        # not tell "not applicable here" from "we forgot". One line each makes
        # the composition visible where an operator is already looking.
        for module, cmd in OPTIONAL_SEED_COMMANDS:
            if is_enabled(module):
                commands.append(cmd)
            else:
                self.stdout.write(
                    f"\n--- {cmd}: skipped (module '{module}' not enabled) ---"
                )
        for cmd in commands:
            self.stdout.write(f"\n--- {cmd} ---")
            call_command(cmd, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("\nAll seed data loaded."))
