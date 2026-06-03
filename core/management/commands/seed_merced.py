# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Run the full Merced Subbasin demonstration seed in dependency order, so a
fresh server reproduces the whole demo with one command (``make merced``).

Order matters:
  1. seed_merced_base       — the subbasin boundary (the spatial canvas).
  2. auto_populate          — real rivers/canals + monitoring stations from
                              live USGS 3DHP (operations places diversions on
                              these named flowlines, so they must exist first).
  3. seed_merced_gsas       — the three GSAs as management-area zones (the
                              groundwater authority).
  4. seed_merced_operations — water rights + points of diversion (the surface
                              district). Needs the flowlines from step 2.
  5. seed_merced_parcels_from_selection — parcels + canal/well/GSA links from
                              Brent's QGIS field selection. Needs PODs (4),
                              GSAs (3), and data/merced/selected_parcels.geojson.
  6. seed_merced_recharge   — managed-recharge sites.
  7. seed_merced_ledgers    — the synthetic accounting layer (reporting periods,
                              two-authority Water Budgets, accounts, and the full
                              keyed ParcelLedger). Depends on parcels, wells,
                              rights, PODs, and the GSA zones all existing, so it
                              runs LAST.

Each sub-command is idempotent, so re-running is safe. Step 2 is a live
network fetch (a few minutes); everything else is local.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand

SEQUENCE = [
    ("seed_merced_base", {}),
    ("auto_populate", {"boundary": "Merced Subbasin", "steps": "flowlines,stations"}),
    ("seed_merced_gsas", {}),
    # --flush so a re-run drops rows removed from config (e.g. a retired water
    # right), not just updates survivors. parcels_from_selection rebuilds the
    # real parcels/wells right after, so the flush is safe.
    ("seed_merced_operations", {"flush": True}),
    ("seed_merced_parcels_from_selection", {}),
    ("seed_merced_recharge", {}),
    # The accounting layer hangs off everything above (parcels, wells, rights,
    # PODs, GSA zones), so it runs last. It self-flushes its own rows, so a
    # re-run rebuilds the ledger cleanly.
    ("seed_merced_ledgers", {}),
]


class Command(BaseCommand):
    help = "Run the full Merced Subbasin demo seed sequence in dependency order."

    def handle(self, *args, **options):
        for cmd, kwargs in SEQUENCE:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {cmd} ==="))
            call_command(cmd, stdout=self.stdout, **kwargs)
        self.stdout.write(self.style.SUCCESS("\nMerced Subbasin demo fully seeded."))
