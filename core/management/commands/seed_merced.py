# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Run the full Merced Subbasin demonstration seed in dependency order, so a
fresh server reproduces the whole demo with one command (``make merced``).

**REQUIRES A FULL DEPLOYMENT — every module enabled**, and unlike ``seed_data``
that is a deliberate answer rather than an oversight. ``seed_data`` loads
reference vocabularies and is gated module by module so any configuration seeds
cleanly. The Merced demo is a single interlocking story — wells feeding parcels
feeding accounts, surface rights and diversions beside them — and a version of
it with a domain removed would not be a smaller demo, it would be a broken one.
On a demoted deployment it writes rows into a switched-off module's tables,
which ``test_schema_resident_module_tables_are_present_and_empty`` forbids.

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
                              Brent's QGIS field selection (incl. the 2 Merced
                              River dual-purpose parcels). Needs PODs (4), GSAs
                              (3), and data/merced/selected_parcels.geojson.
  6. seed_merced_basins_from_selection — recharge AREAS from Brent's QGIS pick:
                              El Nido Canal spreading basins (new canal intakes)
                              + Merced River Flood-MAR cropland (linked to the
                              existing MER-POD-009). Needs the PODs (4) + parcels
                              (5). Replaces the old hardcoded seed_merced_recharge.
  7. seed_merced_cropland   — a crop-type UsageLocation per irrigated parcel, so
                              the calc engine's facility_only_zero step does not
                              zero every parcel. Land use is a prerequisite for
                              the accounting layer, so it runs BEFORE the ledgers.
  8. seed_merced_ledgers    — the synthetic accounting layer (reporting periods,
                              two-authority Allocations, accounts, and the full
                              keyed ParcelLedger). Depends on parcels, wells,
                              rights, PODs, and the GSA zones all existing, so it
                              runs after them.
  9. seed_merced_recharge_events — wet-season managed-recharge events on the two
                              basins, distributed as GROUNDWATER credits across the
                              overlying GSA's parcels. Sits ON TOP of the accounting
                              layer (needs the WY 2024-2025 ReportingPeriod + parcels
                              from step 8).
 10. seed_merced_details   — descriptive detail fields (well construction, parcel
                              addresses, CalWATRS PINs, account contacts) so every
                              detail page reads complete. Invented mock data, which
                              is why step 11's real wells are excluded from it.
 11. seed_merced_drinking  — the drinking-water domain for the same subbasin: the
                              City of Merced (CA2410009), its facilities, its
                              municipal supply wells and three years of its real
                              published lab results. Runs LAST: it needs the well
                              types and analyte vocabulary from ``seed_data``, and
                              it must follow seed_merced_details, whose invented
                              registry numbers must never land on a real utility's
                              wells.

Note: demand-aware surface sizing in step 8 reads the OpenETCache, so in a deployment
run ``sync_openet_parcels``/``sync_precip_parcels`` (and ``run_calculations`` for
the groundwater + incidental-recharge rows) around this sequence; without an ET
cache, step 8 falls back to face-value sizing and the demo is still coherent.

Each sub-command is idempotent, so re-running is safe. Step 2 is a live
network fetch (a few minutes); everything else is local.

On a DEBUG=False deployment step 4 guards itself, because it deletes and
regenerates parcel/well geometry. A FIRST-TIME seed passes straight through —
with no ``MER-`` parcels or wells in the database there is nothing to clobber.
RE-running over an existing demo is refused unless you pass
``--allow-prod-clobber``, which this command forwards to step 4. That is the
whole of ISS-095: the flag had nowhere to enter, so ``make fresh`` and the
DEPLOY.md/AI-OPERATOR-GUIDE seed instruction both died at step 3 of 10.
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
    # Recharge AREAS from the QGIS pick (El Nido pure-recharge basins + Merced
    # River Flood-MAR cropland). Replaces the hardcoded two-square seed; runs
    # after parcels (needs MER-POD-009) and before the recharge events.
    ("seed_merced_basins_from_selection", {}),
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
    # The drinking-water half of the same subbasin: the City of Merced
    # (CA2410009), its facilities, its municipal supply wells and three years
    # of its real published lab results. Runs LAST for two reasons. It needs
    # the wells module's `Production` well type and the `drinking` analyte
    # vocabulary (both from `seed_data`, which precedes this whole sequence),
    # and it must land AFTER `seed_merced_details` — that command fills blank
    # well fields with invented registry numbers, and it now skips `MER-PWS-*`
    # for exactly that reason. Idempotent; `--flush` rebuilds it cleanly.
    ("seed_merced_drinking", {}),
]

#: Sub-commands that accept ``--allow-prod-clobber``, so this command can forward
#: it (ISS-095). Only ``seed_merced_operations`` guards on ``DEBUG`` today, and
#: before this existed there was no way to pass the flag through — so the
#: documented "full reset" died at step 3 of 10 on every DEBUG=False deployment,
#: leaving a wiped database with only steps 1-3 in it.
#:
#: Declared rather than introspected at call time, because forwarding a flag to a
#: command that does not define it is a hard ``TypeError`` mid-sequence — after
#: earlier steps have already written rows. ``tests/test_seed_merced_prod_clobber.py``
#: asserts this tuple and the real parsers describe each other exactly, so adding
#: a guarded command to SEQUENCE without listing it here fails the suite instead
#: of failing a rebuild.
ACCEPTS_PROD_CLOBBER = ("seed_merced_operations",)


class Command(BaseCommand):
    help = "Run the full Merced Subbasin demo seed sequence in dependency order."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-prod-clobber", action="store_true",
            help="Forward --allow-prod-clobber to the sub-commands that guard on "
            "DEBUG=False. Required for a deliberate REBUILD of a production "
            "instance that already holds MER- demo rows; a genuinely first-time "
            "seed needs no flag, because there is nothing to clobber.",
        )

    def handle(self, *args, **options):
        for cmd, kwargs in SEQUENCE:
            if options.get("allow_prod_clobber") and cmd in ACCEPTS_PROD_CLOBBER:
                kwargs = {**kwargs, "allow_prod_clobber": True}
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {cmd} ==="))
            call_command(cmd, stdout=self.stdout, **kwargs)
        self.stdout.write(self.style.SUCCESS("\nMerced Subbasin demo seeded."))
        self._report_engine_gap()

    def _report_engine_gap(self):
        """Say what this sequence deliberately did NOT do (ISS-099).

        This command used to sign off with "fully seeded" — after skipping the ET
        cache, the CalculationPlan and the engine run, three exclusions recorded
        only in the docstring above. An operator who stopped here got a dashboard
        reading consumptive use 0.00 for every account and zone, which is not the
        demo working; it is the demo with its headline number missing.

        Checked rather than printed unconditionally, so the message is a
        description of THIS database and not a standing disclaimer that gets
        skimmed. Where the operator ran the ET sync first, they are told so.
        """
        from accounting.models import CalculationPlan, CalculationRun
        from datasync.models import OpenETCache

        missing = []
        if not OpenETCache.objects.exists():
            missing.append(
                "  • No satellite ET data. Run `sync_openet_parcels` and "
                "`sync_precip_parcels` (needs an OpenET key; without them the "
                "ledgers fall back to face-value sizing)."
            )
        if CalculationPlan.active() is None:
            missing.append(
                "  • No active calculation method. Run `seed_calculation_plan` "
                "— without it `run_calculations` fails with `ValueError: no "
                "active CalculationPlan`."
            )
        if not CalculationRun.objects.exists():
            missing.append(
                "  • The calculation engine has never run. Run "
                "`run_calculations` last, once the two above are in place."
            )

        if not missing:
            self.stdout.write(
                self.style.SUCCESS(
                    "The calculation engine has output in this database — the "
                    "dashboard's consumptive-use figures are real."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                "\nNOT seeded by this command, by design — until these are done "
                "the dashboard shows no consumptive use, and its balance is "
                "supplies only:"
            )
        )
        for line in missing:
            self.stdout.write(self.style.WARNING(line))
