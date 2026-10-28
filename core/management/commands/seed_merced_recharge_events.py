# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed managed/storm recharge EVENTS on the Merced recharge areas.

``seed_merced_basins_from_selection`` creates the demo district's recharge
areas (El Nido Canal spreading basins + Merced River Flood-MAR cropland)
as ``RechargeSite`` rows but gives them no events, so no managed
recharge ever reaches the ledger. This command adds wet-season ``RechargeEvent``
rows for BOTH demonstration water years and deposits each to the
overlying GSA's basin pool — the *managed* half of an honest groundwater budget.
The two seasons are deliberately different sizes: see ``RECHARGE_SEASONS``. (The *incidental* deep-percolation
half — surface delivered beyond crop demand — is written separately by the calc
engine; see run_calculations.)

Basins are selected by ``operator`` (Halvern Irrigation District) so this picks up
whatever the current hand-pick produced without hardcoding basin names.

Decision (2026-06-03): recharge credits **Groundwater (GW)**. The physical
source water (storm/surface runoff diverted to the basin) is preserved in the
event ``source_description``/``notes`` for the audit trail; the ledger
``water_type`` is GW so it credits the aquifer the demo tells a story about.

Distinct from the engine's incidental rows: those are described "Incidental
recharge — ..."; ``create_recharge_ledger_entries`` describes these "Recharge from
<basin> ...". The two never collide and each is independently idempotent.

The basins are the district's, so each event also credits the district's own water
account (``MER-ACCT-DIST``, named for the operator) with its volume less the share
left in the basin; the pool row stays as the basin's record of the water.

Idempotent: self-flushes its own events + ledger rows before re-creating. Runs
AFTER ``seed_merced_ledgers`` (needs both ReportingPeriods + parcels).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.locks import demonstration_seed
from accounting.models import AllocationCarryover, ReportingPeriod, WaterType
from accounting.services import BASIN_RECHARGE_POOL, create_recharge_ledger_entries
from geography.models import Zone
from parcels.models import ParcelLedger

# Wet-season recharge schedule PER WATER YEAR: storm-driven, weighted to
# mid-winter. (event_date, fraction-of-capacity). A season's fractions sum to
# the number of basin-fulls spread that year, so the list says in one line how
# wet the winter was.
#
# THE DRY YEAR'S RECHARGE IS SMALLER, NOT ABSENT, AND HERE IS WHY.
# A dry year genuinely has less storm water to spread, so copying the wet year's
# schedule would be a lie. Seeding nothing would be a different lie: the basins
# and their canal intake are still there, and a winter with half the rain still
# produces storms worth diverting. The dry season below is scaled to 0.50 — the
# same rainfall multiplier ``synthesize_dry_year`` applies to the satellite record, and it arrives as TWO mid-winter storms rather
# than a four-month season, because a dry winter is short of storms before it is
# short of water in each one. December and March, the shoulder fills, do not
# happen at all.
#
# ⚠ This is the MANAGED spreading-basin schedule only. The high-flow storm
# diversion is written by ``seed_merced_ledgers`` and must not be built here.
RECHARGE_SEASONS = {
    "WY 2024-2025": [
        (date(2024, 12, 15), Decimal("0.20")),
        (date(2025, 1, 15), Decimal("0.30")),
        (date(2025, 2, 15), Decimal("0.30")),
        (date(2025, 3, 15), Decimal("0.20")),
    ],
    "WY 2025-2026": [
        (date(2026, 1, 15), Decimal("0.30")),
        (date(2026, 2, 15), Decimal("0.20")),
    ],
}
# Merced recharge areas all carry this operator (set by the basin seed); the
# single readable key that finds them without hardcoding names or hitting other
# demos. Fictional: the recharge volumes below are invented, so
# a real district must not be named as the operator they are attributed to. No
# legacy-operator fallback here on purpose: the basin seed runs first and
# migrates the old rows, so a database still carrying the earlier operator fails
# loudly on the "no recharge areas found" branch instead of quietly writing
# invented volumes onto rows the basin seed is about to delete.
DEMO_OPERATOR = "Halvern Irrigation District"
# The district's water account, credited with the basins' recharge. The prefix is
# the one every demonstration account carries (the teardown finds them by it).
DISTRICT_ACCOUNT_NUMBER = "MER-ACCT-DIST"
# How long the gates stay open on a fill. The events used to carry no end_date at
# all, so every event-history card printed an em dash where the span belongs and
# the demonstration could not say how long a storm was diverted for.
#
# THREE DAYS, and the readings printed beside the event on the same page are what
# fix the length. `seed_merced_measurements` dates every reading off this event's
# `start_date`: canal inflow at +1 day "while the basin was filling", ponded depth
# at +2 "two days into the fill and the basin holding steady", source-water TDS at
# +3 "during the fill", and percolation at +4 "measured off the falling head AFTER
# THE GATES WERE SHUT". Gates open on the fill date and shut on +3 is the only
# span that leaves all four of those sentences true at once.
#
# Rejected: a 2-day span. The fill volumes and the seeded headgate inflow imply it
# physically (a ~1.4-day fill at the recorded rate), but it would put the TDS grab
# sample at +3 a day after the gates shut, and its note says the sample was taken
# during the fill. The recorded rate is the PEAK at the headgate on day one, which
# is throttled back as the basin fills — so a three-day span and a 1.4-day fill
# volume are not in conflict.
FILL_SPAN_DAYS = 3
# Oldest first — the order the seasons are written in, so the stdout summary
# reads as a chronology.
REPORTING_PERIOD_NAMES = tuple(RECHARGE_SEASONS)


class Command(BaseCommand):
    help = (
        "Seed managed-recharge events on the Merced basins, credited to "
        "groundwater (idempotent; run after seed_merced_ledgers)."
    )

    @transaction.atomic
    @demonstration_seed
    def handle(self, *args, **options):
        # Local import: `recharge` is an optional module, so this must not run at
        # module scope.
        from recharge.models import RechargeEvent, RechargeSite

        gw, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )
        # The reporting periods are a PREREQUISITE CHECK, not an argument: the
        # events carry dates, and `create_recharge_ledger_entries` derives the
        # period from the event. A missing period means seed_merced_ledgers has
        # not run, and the recharge credits would land against nothing.
        missing = [
            name for name in REPORTING_PERIOD_NAMES
            if not ReportingPeriod.objects.filter(name=name).exists()
        ]
        if missing:
            self.stderr.write(
                self.style.ERROR(
                    f"ReportingPeriod(s) not found: {', '.join(missing)} — run "
                    f"seed_merced_ledgers first."
                )
            )
            return

        basins = list(
            RechargeSite.objects.filter(
                operator=DEMO_OPERATOR, site_type="spreading_basin"
            )
        )
        if not basins:
            self.stderr.write(
                self.style.ERROR(
                    "No Merced recharge areas found — run "
                    "seed_merced_basins_from_selection first."
                )
            )
            return

        # The basins are the district's, so the district's own water account is
        # credited with what they recharge. It carries the demonstration's account
        # prefix, so the teardown that removes the other demonstration accounts
        # removes this one too.
        from accounting.models import AccountCredit, WaterAccount

        district, _ = WaterAccount.objects.get_or_create(
            account_number=DISTRICT_ACCOUNT_NUMBER,
            defaults={
                "name": DEMO_OPERATOR,
                "status": "active",
                "contact_name": "District Water Manager",
            },
        )
        for basin in basins:
            if basin.water_account_id != district.pk:
                basin.water_account = district
                basin.save(update_fields=["water_account"])

        # Self-flush: drop this seed's prior events (idempotency). Also clear any
        # LEGACY per-parcel "Recharge from <basin>" ledger rows left by the old
        # area-weighted smear — the rewritten service writes none — while leaving
        # the engine's "Incidental recharge" rows untouched.
        AccountCredit.objects.filter(
            origin="managed_recharge",
            source_key__in=[
                f"recharge_event:{pk}"
                for pk in RechargeEvent.objects.filter(
                    recharge_site__in=basins
                ).values_list("pk", flat=True)
            ],
        ).delete()
        RechargeEvent.objects.filter(recharge_site__in=basins).delete()
        for basin in basins:
            ParcelLedger.objects.filter(
                source_type="recharge",
                description__startswith=f"Recharge from {basin.name}",
            ).delete()

        # Managed recharge now deposits to each zone's basin pool (an
        # AllocationCarryover row, origin=basin_recharge_pool) instead of smearing
        # ledger rows. Reset THIS seed's pool slice for the involved zones before
        # re-depositing so a re-run is idempotent — and only the MANAGED origin, so
        # the engine's separate incidental-recharge pool survives untouched.
        zone_by_basin = {basin.pk: self._resolve_zone(basin) for basin in basins}
        reset_zone_ids = {z.pk for z in zone_by_basin.values() if z is not None}
        AllocationCarryover.objects.filter(
            zone_id__in=reset_zone_ids, origin=BASIN_RECHARGE_POOL
        ).delete()

        total_events = 0
        for basin in basins:
            zone = zone_by_basin[basin.pk]
            if zone is None:
                self.stderr.write(
                    self.style.WARNING(
                        f"  {basin.name}: no containing GSA zone — skipped"
                    )
                )
                continue
            capacity = basin.capacity_acre_feet or Decimal("0")
            season_totals = []
            for wy_name in REPORTING_PERIOD_NAMES:
                season = RECHARGE_SEASONS[wy_name]
                season_totals.append(
                    f"{wy_name}: {sum(f for _, f in season)}x capacity over "
                    f"{len(season)} event(s)"
                )
            for ev_date, fraction in [
                pair
                for wy_name in REPORTING_PERIOD_NAMES
                for pair in RECHARGE_SEASONS[wy_name]
            ]:
                vol = (capacity * fraction).quantize(Decimal("0.0001"))
                if vol <= 0:
                    continue
                event = RechargeEvent.objects.create(
                    recharge_site=basin,
                    start_date=ev_date,
                    # The gates were open for FILL_SPAN_DAYS — see that constant
                    # for why three and not two. ⚠ Never derive a reading date
                    # from end_date: seed_merced_measurements dates all 126
                    # readings off start_date, so the span may move only if that
                    # command's four notes stay true.
                    end_date=ev_date + timedelta(days=FILL_SPAN_DAYS),
                    volume_acre_feet=vol,
                    water_type=gw,
                    source_description="storm/surface runoff diverted to basin",
                    notes=(
                        "Managed aquifer recharge credited to groundwater (GW); "
                        "physical source is diverted surface/storm water."
                    ),
                )
                # No parcel arg -> the whole event volume pools to the zone's GSA
                # basin pool; no per-parcel ledger rows (no smear across parcels).
                create_recharge_ledger_entries(event, zone=zone)
                total_events += 1
            self.stdout.write(
                f"  {basin.name}: {capacity} AF capacity -> basin pool for zone "
                f"'{zone.name}'; " + "; ".join(season_totals)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded managed recharge: {total_events} event(s) deposited to "
                f"the basin pool across {len(basins)} basin(s)."
            )
        )

    def _resolve_zone(self, basin):
        """The GSA management-area zone for this basin.

        Prefers the basin's own ``zone`` FK; falls back to the management-area
        zone whose boundary geometry spatially contains the basin location (the
        seeded basins ship with ``zone=NULL``).
        """
        if basin.zone is not None:
            return basin.zone
        for zone in Zone.objects.filter(zone_type="management_area"):
            boundary = getattr(zone, "boundary", None)
            geom = getattr(boundary, "geometry", None)
            if geom is not None and geom.contains(basin.location):
                return zone
        return None
