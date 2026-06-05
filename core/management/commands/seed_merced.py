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
  7. seed_merced_cropland   — a crop-type UsageLocation per irrigated parcel, so
                              the calc engine's facility_only_zero step does not
                              zero every parcel. Land use is a prerequisite for
                              the accounting layer, so it runs BEFORE the ledgers.
  8. seed_merced_ledgers    — the synthetic accounting layer (reporting periods,
                              two-authority Water Budgets, accounts, and the full
                              keyed ParcelLedger). Depends on parcels, wells,
                              rights, PODs, and the GSA zones all existing, so it
                              runs after them.
  9. seed_merced_recharge_events — wet-season managed-recharge events on the two
                              basins, distributed as GROUNDWATER credits across the
                              overlying GSA's parcels. Sits ON TOP of the accounting
                              layer (needs the WY 2024-2025 ReportingPeriod + parcels
                              from step 8), so it runs LAST.

Note: demand-aware surface sizing in step 8 reads the OpenETCache, so on Butler
run ``sync_openet_parcels``/``sync_precip_parcels`` (and ``run_calculations`` for
the groundwater + incidental-recharge rows) around this sequence; without an ET
cache, step 8 falls back to face-value sizing and the demo is still coherent.

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
    # Land use BEFORE the accounting layer: the engine's facility_only_zero step
    # zeros any parcel with no crop_type UsageLocation, so the ledgers' parcels
    # need crop land use first. Idempotent; MER-keyed.
    ("seed_merced_cropland", {}),
    # The accounting layer hangs off everything above (parcels, wells, rights,
    # PODs, GSA zones). It self-flushes its own rows, so a re-run rebuilds the
    # ledger cleanly. Surface deliveries are demand-aware when an ET cache exists.
    ("seed_merced_ledgers", {}),
    # Managed recharge sits ON TOP of the accounting layer (needs the WY 2024-2025
    # ReportingPeriod + parcels), so it runs last. Credits groundwater; idempotent.
    ("seed_merced_recharge_events", {}),
    # Descriptive detail fields (well construction, parcel addresses, CalWATRS
    # PINs, account contacts, display meters) so every detail page reads complete.
    # Runs after the ledger rebuild because it fills account contacts; fill-only-
    # when-blank + deterministic, so it's idempotent and never clobbers real data.
    ("seed_merced_details", {}),
]


class Command(BaseCommand):
    help = "Run the full Merced Subbasin demo seed sequence in dependency order."

    def handle(self, *args, **options):
        for cmd, kwargs in SEQUENCE:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {cmd} ==="))
            call_command(cmd, stdout=self.stdout, **kwargs)
        self.stdout.write(self.style.SUCCESS("\nMerced Subbasin demo fully seeded."))
