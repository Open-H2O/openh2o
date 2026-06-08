# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed managed/storm recharge EVENTS on the Merced recharge areas (Phase 52.5-03).

``seed_merced_basins_from_selection`` creates the Merced Irrigation District
recharge areas (El Nido Canal spreading basins + Merced River Flood-MAR cropland,
Phase 62) as ``RechargeSite`` rows but gives them no events, so no managed
recharge ever reaches the ledger. This command adds wet-season ``RechargeEvent``
rows for WY 2024-2025 and deposits each to the overlying GSA's basin pool — the
*managed* half of an honest groundwater budget. (The *incidental* deep-percolation
half — surface delivered beyond crop demand — is written separately by the calc
engine; see run_calculations / ISS-052.)

Basins are selected by ``operator`` (Merced Irrigation District) so this picks up
whatever the current hand-pick produced without hardcoding basin names, and never
touches Demo Valley recharge sites.

Decision (Brent, 2026-06-03): recharge credits **Groundwater (GW)**. The physical
source water (storm/surface runoff diverted to the basin) is preserved in the
event ``source_description``/``notes`` for the audit trail; the ledger
``water_type`` is GW so it credits the aquifer the demo tells a story about.

Distinct from the engine's incidental rows: those are described "Incidental
recharge — ..."; ``create_recharge_ledger_entries`` describes these "Recharge from
<basin> ...". The two never collide and each is independently idempotent.

Idempotent: self-flushes its own events + ledger rows before re-creating. Runs
AFTER ``seed_merced_ledgers`` (needs the WY 2024-2025 ReportingPeriod + parcels).
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.models import AllocationCarryover, ReportingPeriod, WaterType
from accounting.services import BASIN_RECHARGE_POOL, create_recharge_ledger_entries
from geography.models import Zone
from parcels.models import ParcelLedger
from recharge.models import RechargeEvent, RechargeSite

# Wet-season recharge schedule for WY 2024-2025: storm-driven, weighted to
# mid-winter. (event_date, fraction-of-capacity). Fractions sum to 1.0, so each
# basin recharges ~one full capacity over the season — a strong, visible GW
# credit against the demo's extraction.
WET_SEASON = [
    (date(2024, 12, 15), Decimal("0.20")),
    (date(2025, 1, 15), Decimal("0.30")),
    (date(2025, 2, 15), Decimal("0.30")),
    (date(2025, 3, 15), Decimal("0.20")),
]
# Merced recharge areas all carry this operator (set by the basin seed); the
# single readable key that finds them without hardcoding names or hitting other demos.
MID_OPERATOR = "Merced Irrigation District"
REPORTING_PERIOD_NAME = "WY 2024-2025"


class Command(BaseCommand):
    help = (
        "Seed managed-recharge events on the Merced basins, credited to "
        "groundwater (idempotent; run after seed_merced_ledgers)."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        gw, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )
        period = ReportingPeriod.objects.filter(
            name=REPORTING_PERIOD_NAME
        ).first()
        if period is None:
            self.stderr.write(
                self.style.ERROR(
                    f"{REPORTING_PERIOD_NAME} ReportingPeriod not found — run "
                    f"seed_merced_ledgers first."
                )
            )
            return

        basins = list(
            RechargeSite.objects.filter(
                operator=MID_OPERATOR, site_type="spreading_basin"
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

        # Self-flush: drop this seed's prior events (idempotency). Also clear any
        # LEGACY per-parcel "Recharge from <basin>" ledger rows left by the old
        # area-weighted smear — the rewritten service writes none — while leaving
        # the engine's "Incidental recharge" rows untouched.
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
            for ev_date, fraction in WET_SEASON:
                vol = (capacity * fraction).quantize(Decimal("0.0001"))
                if vol <= 0:
                    continue
                event = RechargeEvent.objects.create(
                    recharge_site=basin,
                    start_date=ev_date,
                    volume_acre_feet=vol,
                    water_type=gw,
                    source_description="storm/surface runoff diverted to basin",
                    notes=(
                        "Managed aquifer recharge credited to groundwater (GW); "
                        "physical source is diverted surface/storm water."
                    ),
                )
                # No parcel arg -> the whole event volume pools to the zone's GSA
                # basin pool; no per-parcel ledger rows (kills the ISS-053 smear).
                create_recharge_ledger_entries(event, zone=zone)
                total_events += 1
            self.stdout.write(
                f"  {basin.name}: {capacity} AF over {len(WET_SEASON)} "
                f"wet-season events -> basin pool for zone '{zone.name}'"
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
