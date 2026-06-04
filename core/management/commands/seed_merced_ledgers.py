# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the Merced demonstration's synthetic ACCOUNTING layer (Phase 52-01).

WHY this command exists. Phases 50–51 built the physical Merced demo — real
boundaries, rivers/canals, GSAs, water rights, points of diversion, parcels on
surveyed cropland, and wells. That canvas shows WHERE water moves. This command
adds the accounting layer that shows HOW MUCH: reporting periods, Water Budgets
for BOTH authorities, water accounts per grower, and the full ParcelLedger
transaction set. It is the payoff of the whole rebuild — the layer that lets an
evaluator read "this grower was allocated X, used Y, is Z over/under, and here is
the audit trail." Phase 53 turns these rows into the state reports + teardown.

The four headline cases it demonstrates, all keyed off each parcel's water source
(the physical truth: a POD link means surface delivery, a well link means
groundwater extraction):

  1. single-source canal district — surface-only parcels get surface deliveries
     and NEVER a groundwater extraction;
  2. conjunctive use — parcels with both a canal delivery and a well get both;
  3. curtailment → substitution — the junior El Nido right (MER-WR-009) is cut
     going into peak season; its parcels lose surface water after June, and the
     conjunctive growers among them fall back on groundwater (a clear pumping bump);
  4. shared-well apportionment — a well that irrigates several parcels splits its
     monthly extraction across them by the stored fraction, summing to the well total.

TWO-AUTHORITY budgets (Brent's 2026-06-03 call). SGMA splits the jobs: the GSA
manages groundwater (a management-area zone), the irrigation district moves canal
water (a water right + PODs). Both get Water Budgets here. A GSA already IS a zone,
so its groundwater budget hangs off it directly. A surface district is a water
right, NOT a zone — so this command synthesizes a ``custom`` service-area zone per
surface district (the dissolve of the parcels it serves) to hang its surface budget
on, exactly so a canal district shows budget-vs-delivered on screen like a GSA does.

DETERMINISTIC + IDEMPOTENT + ADDITIVE. No ``random`` (index-based jitter only), so
re-runs reproduce identical rows. The command ALWAYS flushes its OWN rows first
(the synthesized district zones, its Water Budgets, its accounts, and the
ParcelLedger rows on MER- parcels) then rebuilds, so a bare re-run leaves counts
unchanged. It NEVER touches Kaweah / Demo / base-layer rows, nor the three GSA
management-area zones (those belong to seed_merced_gsas). Synthetic volumes are
``area × rate × seasonal weight`` (NOT crop-ET-derived — the proven Kaweah engine
never needed crop ET), so CropType and well capacity stay out of scope.

Prerequisite (the physical demo must already exist on this instance)::

    python manage.py seed_merced            # the full physical demo, OR at least:
    python manage.py seed_merced_gsas
    python manage.py seed_merced_operations
    python manage.py seed_merced_parcels_from_selection
"""
from datetime import date
from decimal import Decimal

from django.contrib.gis.geos import MultiPolygon
from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.models import (
    AllocationPlan,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterType,
)
from core.models import SiteConfig
from geography.models import Boundary, ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger
from surface.models import (
    CurtailmentOrder,
    DiversionRecord,
    PointOfDiversion,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightParcel,
)
from surface.services import allocate_district_delivery
from wells.models import Well, WellIrrigatedParcel

MER_PARCEL_PREFIX = "MER-APN-"
GSA_BASIN_CODE = "5-022.04"
DISTRICT_ZONE_PREFIX = "MER Surface Service Area"

# Seasonal irrigation weights across the California water year (Oct..Sep). Same
# shape as seed_kaweah's so the two demos read alike. Sums to 1.0.
SEASONAL_WEIGHTS = {
    10: 0.05, 11: 0.03, 12: 0.02, 1: 0.02, 2: 0.02, 3: 0.04,
    4: 0.08, 5: 0.14, 6: 0.16, 7: 0.16, 8: 0.15, 9: 0.13,
}

# Synthetic per-acre rates (acre-feet per acre per year). NOT crop-ET-derived.
SURFACE_RATE = 2.2          # canal delivery to a surface/conjunctive parcel
GW_RATE = 1.8               # groundwater pumped by a parcel's well(s)

# Agency-wide irrigation efficiency the seed installs on the SiteConfig singleton
# (55-03). The per-parcel surface split is now produced by
# surface.services.allocate_district_delivery, which READS efficiency from
# SiteConfig — so the seed sets it here rather than carrying its own constant.
SEED_IRRIGATION_EFFICIENCY = Decimal("0.750")
GSA_SUSTAINABLE_RATE = 2.0  # GSA groundwater budget — SGMA sustainable-yield proxy
GSA_BUDGET_FLOOR = Decimal("500.0")   # a GSA with no demo parcels still gets a budget
SURFACE_BUDGET_FRACTION = Decimal("0.9")    # district surface budget ~ 90% of face
CURTAILED_OPEN_FRACTION = Decimal("0.1")    # curtailed district's current-year budget collapses

# Curtailment. The junior El Nido right is cut going INTO the peak season: the
# last month with a surface delivery is June 2025, so July–September run dry and
# the conjunctive growers substitute groundwater (a clear pumping bump).
CURTAILMENT_LAST_DELIVERY = date(2025, 6, 30)
POST_CURTAILMENT_MONTHS = {7, 8, 9}
SUBSTITUTION_MULTIPLIER = Decimal("1.6")


def _q(value):
    """Quantize to the ledger's 4 decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _jitter(seq):
    """Deterministic ±6% factor keyed on an index — varies volumes without random."""
    return Decimal("1") + (Decimal(seq % 7) - Decimal("3")) * Decimal("0.02")


class Command(BaseCommand):
    help = (
        "Build the Merced demo's synthetic accounting layer (reporting periods, "
        "two-authority Water Budgets, accounts, and the full keyed ParcelLedger). "
        "Idempotent; additive (MER-keyed; never touches Kaweah/Demo/base/GSA rows)."
    )

    def add_arguments(self, parser):
        # Accepted for orchestrator symmetry. The command ALWAYS flushes its own
        # rows before rebuilding, so re-runs are idempotent with or without it.
        parser.add_argument(
            "--flush", action="store_true",
            help="No-op alias: this seed always self-flushes its own rows first.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            self._flush()
            self._seed()

    # ------------------------------------------------------------------
    # Flush — ONLY this seed's rows. Never the GSA zones (management_area,
    # owned by seed_merced_gsas), never Kaweah/Demo/base-layer rows.
    # ------------------------------------------------------------------
    def _flush(self):
        ParcelLedger.objects.filter(
            parcel__parcel_number__startswith=MER_PARCEL_PREFIX
        ).delete()

        # DiversionRecords this seed synthesizes as the recorded district total per
        # MER POD/month (the source of truth the allocation service splits). Keyed
        # to MER- rights so the flush never touches Kaweah / base-layer records.
        DiversionRecord.objects.filter(
            point_of_diversion__water_right__right_id__startswith="MER-WR-"
        ).delete()

        acct_ids = list(
            WaterAccount.objects.filter(account_number__startswith="MER-ACCT-")
            .values_list("id", flat=True)
        )
        WaterAccountParcel.objects.filter(water_account_id__in=acct_ids).delete()
        WaterAccount.objects.filter(id__in=acct_ids).delete()

        district_zone_ids = list(
            Zone.objects.filter(
                zone_type="custom", name__startswith=DISTRICT_ZONE_PREFIX
            ).values_list("id", flat=True)
        )
        gsa_zone_ids = list(
            Zone.objects.filter(
                zone_type="management_area", basin_code=GSA_BASIN_CODE
            ).values_list("id", flat=True)
        )
        # Budgets this seed created: on its own district zones (surface) and on the
        # GSA zones (groundwater). Deleting the AllocationPlans never deletes the GSA
        # zones themselves.
        AllocationPlan.objects.filter(
            zone_id__in=district_zone_ids + gsa_zone_ids
        ).delete()
        Zone.objects.filter(id__in=district_zone_ids).delete()

        CurtailmentOrder.objects.filter(order_id__startswith="MER-CURT-").delete()

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------
    def _seed(self):
        parcels = list(Parcel.objects.filter(
            parcel_number__startswith=MER_PARCEL_PREFIX).order_by("parcel_number"))
        if not parcels:
            self.stdout.write(self.style.WARNING(
                "No MER- parcels found. Run seed_merced_parcels_from_selection "
                "(or `make merced`) first — nothing to build accounting on."
            ))
            return

        gw, _ = WaterType.objects.get_or_create(code="GW", defaults={"name": "Groundwater"})
        sw, _ = WaterType.objects.get_or_create(code="SW", defaults={"name": "Surface Water"})

        # The per-parcel surface split is produced by the platform service, which
        # reads irrigation efficiency from the SiteConfig singleton (55-03). Set the
        # demo's agency-wide efficiency here so a fresh demo install has it; respect
        # an operator who has already tuned it to a non-default value.
        self._ensure_efficiency()

        # --- Reporting periods (global, agency-agnostic; shared with Kaweah) ---
        prior, _ = ReportingPeriod.objects.get_or_create(
            name="WY 2024-2025",
            defaults={"start_date": date(2024, 10, 1), "end_date": date(2025, 9, 30),
                      "is_finalized": True},
        )
        open_wy, _ = ReportingPeriod.objects.get_or_create(
            name="WY 2025-2026",
            defaults={"start_date": date(2025, 10, 1), "end_date": date(2026, 9, 30)},
        )
        periods = [prior, open_wy]

        # --- Classify parcels by physical link (the water-source truth) ---
        surface_parcel_ids = set(
            PointOfDiversionParcel.objects.filter(parcel__in=parcels)
            .values_list("parcel_id", flat=True)
        )
        # Parcels served by a CURTAILED MER right (via its PODs) — the El Nido story.
        curtailed_parcel_ids = set(
            PointOfDiversionParcel.objects.filter(
                parcel__in=parcels,
                point_of_diversion__water_right__status="curtailed",
                point_of_diversion__water_right__right_id__startswith="MER-WR-",
            ).values_list("parcel_id", flat=True)
        )

        # --- Surface-district service-area zones (one per served surface right) ---
        district_zones = self._build_district_zones(parcels)

        # --- Water Budgets for BOTH authorities, both periods ---
        self._build_budgets(gw, sw, periods, prior, open_wy, parcels, district_zones)

        # --- Water accounts (one per distinct owner) + account-parcel links ---
        self._build_accounts(parcels, prior)

        # --- Curtailment order (audit provenance for the El Nido cut) ---
        self._build_curtailment_order()

        # --- The ledger: allocations + groundwater extraction (bulk-created here) ---
        entries = []
        entries += self._allocation_rows(parcels, surface_parcel_ids, gw, sw, periods)
        entries += self._groundwater_rows(parcels, curtailed_parcel_ids, gw, prior)
        ParcelLedger.objects.bulk_create(entries, batch_size=500)

        # --- Surface deliveries: synthesize the recorded district total per POD, then
        # let the PLATFORM service split it across served parcels by ET demand. The
        # service writes the negative surface_diversion rows itself (its own
        # delete-then-insert), so they are NOT part of the bulk_create above. ---
        surface_rows = self._surface_deliveries(parcels, curtailed_parcel_ids, prior)

        self._summary(parcels, district_zones, surface_parcel_ids,
                      curtailed_parcel_ids, entries, surface_rows)

    # ------------------------------------------------------------------
    # Surface-district service-area zones
    # ------------------------------------------------------------------
    def _build_district_zones(self, parcels):
        """A ``custom`` zone per surface right, geometry = dissolve of served parcels.

        A surface district is a water right, not a zone, so we synthesize one zone
        per right to hang its surface budget on. Keyed by name prefix + right_id so
        the flush removes only these — never the three GSA management-area zones.
        """
        parcel_ids = [p.id for p in parcels]
        # right -> [parcels it serves] via the WaterRightParcel links the parcels seed built.
        right_to_parcels = {}
        for wrp in WaterRightParcel.objects.filter(
            parcel_id__in=parcel_ids
        ).select_related("water_right", "parcel"):
            right_to_parcels.setdefault(wrp.water_right, []).append(wrp.parcel)

        # Hang the synthesized zones off the Merced Subbasin boundary (the canvas
        # every GSA zone already uses), so they render on the same map.
        any_gsa = Zone.objects.filter(
            zone_type="management_area", basin_code=GSA_BASIN_CODE).first()
        boundary = any_gsa.boundary if any_gsa else (
            Boundary.objects.filter(name="Merced Subbasin").first())

        zones = {}
        for right, served in sorted(right_to_parcels.items(), key=lambda kv: kv[0].right_id):
            geoms = [p.geometry for p in served if p.geometry is not None]
            if not geoms:
                continue
            union = geoms[0]
            for g in geoms[1:]:
                union = union.union(g)
            if union.geom_type == "Polygon":
                union = MultiPolygon(union)
            name = f"{DISTRICT_ZONE_PREFIX} — {right.holder_name} ({right.right_id})"
            zone, _ = Zone.objects.update_or_create(
                name=name,
                defaults={
                    "boundary": boundary,
                    "geometry": union,
                    "zone_type": "custom",
                    "description": (
                        f"Surface-water service area for {right.holder_name} "
                        f"({right.right_id}). Synthesized to carry the district's "
                        "surface Water Budget (a district is a right, not a zone)."
                    ),
                },
            )
            # Link the served parcels to the zone so the zone-detail page lists
            # them AND can total delivered-vs-budget (zone usage reads ParcelZone).
            # The flush deletes these zones, which cascades these ParcelZone rows.
            for p in served:
                ParcelZone.objects.get_or_create(zone=zone, parcel=p)
            zones[right.right_id] = (zone, right)
        return zones

    # ------------------------------------------------------------------
    # Water Budgets
    # ------------------------------------------------------------------
    def _build_budgets(self, gw, sw, periods, prior, open_wy, parcels, district_zones):
        # GSA groundwater budgets — one per GSA zone, both periods. Sized to a
        # plausible SGMA sustainable-yield fraction of the GSA's demo acreage.
        gsa_zones = list(Zone.objects.filter(
            zone_type="management_area", basin_code=GSA_BASIN_CODE))
        acres_by_gsa = {z.id: Decimal("0") for z in gsa_zones}
        for pz in ParcelZone.objects.filter(
            zone__in=gsa_zones, parcel__parcel_number__startswith=MER_PARCEL_PREFIX
        ).select_related("parcel"):
            acres_by_gsa[pz.zone_id] += Decimal(str(pz.parcel.area_acres or 0))
        for zone in gsa_zones:
            budget = max(GSA_BUDGET_FLOOR,
                         _q(acres_by_gsa[zone.id] * Decimal(str(GSA_SUSTAINABLE_RATE))))
            for rp in periods:
                AllocationPlan.objects.update_or_create(
                    zone=zone, water_type=gw, reporting_period=rp,
                    defaults={
                        "name": f"{zone.name} — Groundwater {rp.name}",
                        "allocation_acre_feet": budget,
                        "notes": "SGMA sustainable-yield groundwater budget (demo).",
                    },
                )

        # Surface-district budgets — one per district zone, both periods, sized near
        # the right's face value. The curtailed district's CURRENT-year budget
        # collapses to reflect the curtailment, so the on-screen story stays honest.
        for right_id, (zone, right) in district_zones.items():
            face = Decimal(str(right.face_value_acre_feet or 0))
            base = _q(face * SURFACE_BUDGET_FRACTION)
            curtailed = right.status == "curtailed"
            for rp in periods:
                if curtailed and rp is open_wy:
                    amount = _q(face * CURTAILED_OPEN_FRACTION)
                    note = "Surface budget reduced — junior right curtailed this year."
                else:
                    amount = base
                    note = "Surface Water Budget (~face value of the district's right)."
                AllocationPlan.objects.update_or_create(
                    zone=zone, water_type=sw, reporting_period=rp,
                    defaults={
                        "name": f"{zone.name} — Surface Water {rp.name}",
                        "allocation_acre_feet": amount,
                        "notes": note,
                    },
                )

    # ------------------------------------------------------------------
    # Water accounts
    # ------------------------------------------------------------------
    def _build_accounts(self, parcels, activity_period):
        """One account per distinct owner; an account-parcel link per parcel.

        Membership is recorded for the operative reporting period — the finalized
        WY 2024-2025, where the full year of transactions lives (mirroring Kaweah,
        whose proven engine reads account membership for that period).
        """
        owners = sorted({(p.owner_name or "Unassigned Owner") for p in parcels})
        acct_by_owner = {}
        for i, owner in enumerate(owners, start=1):
            acct = WaterAccount.objects.create(
                account_number=f"MER-ACCT-{i:03d}", name=owner, status="active",
                contact_name=f"{owner.split()[0]} Water Manager",
            )
            acct_by_owner[owner] = acct
        for p in parcels:
            WaterAccountParcel.objects.get_or_create(
                water_account=acct_by_owner[p.owner_name or "Unassigned Owner"],
                parcel=p, reporting_period=activity_period,
            )

    # ------------------------------------------------------------------
    # Curtailment order (audit provenance)
    # ------------------------------------------------------------------
    def _build_curtailment_order(self):
        curtailed = WaterRight.objects.filter(
            status="curtailed", right_id__startswith="MER-WR-").first()
        if curtailed is None:
            return
        CurtailmentOrder.objects.update_or_create(
            order_id="MER-CURT-001",
            defaults={
                "title": (
                    f"Drought curtailment of junior right {curtailed.right_id} "
                    f"({curtailed.holder_name})"
                ),
                "effective_date": date(2025, 7, 1),
                "watershed": curtailed.source_name or "Merced River",
                "priority_date_cutoff": curtailed.priority_date,
                "status": "active",
                "notes": (
                    "Demo curtailment: the junior El Nido right is cut going into "
                    "the peak irrigation season. Surface deliveries stop after June; "
                    "conjunctive growers substitute groundwater."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Ledger rows
    # ------------------------------------------------------------------
    def _allocation_rows(self, parcels, surface_parcel_ids, gw, sw, periods):
        """Positive allocation rows — the budget granted to each parcel.

        gw for any parcel with a groundwater draw (a well), sw for any parcel with a
        surface delivery (a POD link) — each matching the authority that budgets it.
        """
        # Which parcels have a well (a groundwater component)?
        gw_parcel_ids = set(
            WellIrrigatedParcel.objects.filter(parcel__in=parcels)
            .values_list("parcel_id", flat=True)
        )
        rows = []
        for p in parcels:
            area = Decimal(str(p.area_acres or 40))
            for rp in periods:
                if p.id in gw_parcel_ids:
                    rows.append(ParcelLedger(
                        parcel=p, transaction_date=rp.start_date,
                        effective_date=rp.start_date,
                        amount_acre_feet=_q(area * Decimal(str(GW_RATE))),
                        water_type=gw, source_type="allocation",
                        description=f"Annual groundwater allocation for {rp.name}",
                        reporting_period=rp,
                    ))
                if p.id in surface_parcel_ids:
                    rows.append(ParcelLedger(
                        parcel=p, transaction_date=rp.start_date,
                        effective_date=rp.start_date,
                        amount_acre_feet=_q(area * Decimal(str(SURFACE_RATE))),
                        water_type=sw, source_type="allocation",
                        description=f"Annual surface-water allocation for {rp.name}",
                        reporting_period=rp,
                    ))
        return rows

    def _month_schedule(self):
        """(date, month_num) for each month of the prior water year, day 15."""
        schedule = []
        for offset in range(12):
            mn = ((10 + offset - 1) % 12) + 1
            yr = 2024 if mn >= 10 else 2025
            schedule.append((date(yr, mn, 15), mn))
        return schedule

    def _ensure_efficiency(self):
        """Install the demo's agency-wide irrigation efficiency on SiteConfig.

        The per-parcel surface split is now produced by
        ``surface.services.allocate_district_delivery``, which reads efficiency
        from the SiteConfig singleton. So the seed sets it here (0.750) rather than
        carrying its own constant — closing the loop the 55-03 settings UI opens.
        Idempotent: it only writes a fresh row's default, leaving an operator's
        tuned value in place on re-runs of an already-configured install.
        """
        config = SiteConfig.objects.first()
        if config is None:
            SiteConfig.objects.create(
                agency_name="Merced Subbasin GSA",
                default_irrigation_efficiency=SEED_IRRIGATION_EFFICIENCY,
            )
        elif not config.default_irrigation_efficiency:
            config.default_irrigation_efficiency = SEED_IRRIGATION_EFFICIENCY
            config.save(update_fields=["default_irrigation_efficiency"])

    def _surface_deliveries(self, parcels, curtailed_parcel_ids, prior):
        """Surface deliveries, produced by the PLATFORM allocation service.

        This is the 55-03 wiring: the seed no longer sizes each parcel's delivery
        with its own private math. Instead it does what a real district does —
        records the MONTHLY DISTRICT TOTAL that left each point of diversion (a
        ``DiversionRecord``, the source of truth) — then calls
        ``surface.services.allocate_district_delivery`` to split that total across
        the served parcels. The service weights the split by each parcel's measured
        ET demand for the month (the 54-01 spine) when calculations have run, and
        falls back to the static ``PointOfDiversionParcel.fraction`` split when they
        have not (e.g. local dev with no ET cache). Either way it writes the NEGATIVE
        ``surface_diversion`` rows the calc engine consumes — the SAME tested path
        the app uses, so the seed and the app can never drift.

        The recorded district total per POD/month is the sum of its served parcels'
        synthetic envelopes (``area × SURFACE_RATE × jitter × seasonal weight``) —
        the same overall volume the old per-parcel sizing produced, now expressed at
        the district grain the platform actually meters. Curtailed PODs record NO
        diversion after June 2025 — the El Nido cut — so the service produces no
        post-curtailment deliveries for their parcels.

        Returns the list of ``ParcelLedger`` surface rows the service wrote (for the
        summary count); the service has already persisted them.
        """
        schedule = self._month_schedule()
        seq_of = {p.id: i for i, p in enumerate(parcels)}

        # MER PODs that serve MER parcels (skip PODs with no served parcels — the
        # service would write nothing for them anyway).
        pods = (
            PointOfDiversion.objects.filter(
                water_right__right_id__startswith="MER-WR-",
                pod_parcels__parcel__in=parcels,
            )
            .distinct()
            .order_by("name")
        )

        written = []
        for pod in pods:
            curtailed = (
                pod.water_right is not None and pod.water_right.status == "curtailed"
            )
            served = [
                link.parcel
                for link in PointOfDiversionParcel.objects.filter(
                    point_of_diversion=pod
                ).select_related("parcel")
            ]

            # Record the monthly DISTRICT TOTAL that left this POD = the sum of its
            # served parcels' synthetic envelopes for the month. This is the metered
            # truth the platform splits; idempotent via update_or_create on the
            # (POD, month, type) unique key.
            for month_date, mn in schedule:
                if curtailed and month_date > CURTAILMENT_LAST_DELIVERY:
                    continue  # no diversion recorded once the junior right is cut
                total = Decimal("0")
                for p in served:
                    area = Decimal(str(p.area_acres or 40))
                    annual = area * Decimal(str(SURFACE_RATE)) * _jitter(
                        seq_of.get(p.id, 0)
                    )
                    total += annual * Decimal(str(SEASONAL_WEIGHTS[mn]))
                total = _q(total)
                if total <= 0:
                    continue
                DiversionRecord.objects.update_or_create(
                    point_of_diversion=pod,
                    month=month_date,
                    diversion_type="direct_use",
                    defaults={
                        "reporting_period": prior,
                        "volume_acre_feet": total,
                    },
                )

            # Let the platform service split the recorded totals across parcels by
            # ET demand (or the static fraction fallback) and write the negative
            # surface_diversion rows. Same path the app uses.
            written.extend(allocate_district_delivery(pod, prior))

        self.stdout.write(
            f"    surface deliveries: {len(written)} row(s) written by "
            f"allocate_district_delivery across {pods.count()} POD(s)"
        )
        return written

    def _groundwater_rows(self, parcels, curtailed_parcel_ids, gw, prior):
        """Monthly groundwater extraction (NEGATIVE) for METERED wells ONLY.

        The metering split is the 52-01 dual-source invariant: wells alternate
        metered / unmetered. The two halves are now handled differently (52.5-01
        reconciliation):

        - A METERED well's reading is authoritative. The seed writes its
          ``meter_reading`` rows here exactly as before — driven by the well so a
          shared well's monthly total splits across its parcels by the stored
          fraction (summing back to the well total, no double-count), with the
          curtailed-conjunctive substitution bump applied to the well total BEFORE
          apportionment.

        - An UNMETERED well writes NO synthetic groundwater rows. Its parcels'
          groundwater will be computed by the REAL calc engine (``calculated``
          rows, Plan 02); writing an ``et_estimate`` row here too would
          double-count against the engine's output. The well still gets
          ``measurement_method='unmetered_estimate'`` so Task 3's
          ``--unmetered-only`` filter and the metered/unmetered story survive —
          only the synthetic ledger rows go away. The substitution story for these
          parcels then EMERGES from the engine itself: surface deliveries stop
          after curtailment, so the engine subtracts less surface → more net
          groundwater in the dry months.
        """
        parcel_by_id = {p.id: p for p in parcels}
        # well -> [WellIrrigatedParcel links] for MER wells irrigating MER parcels.
        wells = list(Well.objects.filter(
            well_registration_id__startswith="MER-W-").order_by("well_registration_id"))
        links_by_well = {}
        for ln in WellIrrigatedParcel.objects.filter(
            well__in=wells, parcel_id__in=parcel_by_id
        ):
            links_by_well.setdefault(ln.well_id, []).append(ln)

        schedule = self._month_schedule()
        rows = []
        for wseq, well in enumerate(wells):
            links = links_by_well.get(well.id)
            if not links:
                continue
            # Alternate metered / unmetered so the demo exercises both stories.
            metered = (wseq % 2 == 0)
            method = "certified_meter" if metered else "unmetered_estimate"
            if well.measurement_method != method:
                Well.objects.filter(pk=well.pk).update(measurement_method=method)

            # Unmetered wells are engine-owned: the method is set (above) but the
            # seed writes no synthetic extraction, so the engine's `calculated`
            # rows (Plan 02) never double-count.
            if not metered:
                continue

            served_acres = sum(
                Decimal(str(parcel_by_id[ln.parcel_id].area_acres or 40)) * ln.fraction
                for ln in links
            )
            well_annual = served_acres * Decimal(str(GW_RATE)) * _jitter(wseq)
            substitutes = any(ln.parcel_id in curtailed_parcel_ids for ln in links)

            for month_date, mn in schedule:
                well_monthly = well_annual * Decimal(str(SEASONAL_WEIGHTS[mn]))
                if substitutes and mn in POST_CURTAILMENT_MONTHS:
                    well_monthly *= SUBSTITUTION_MULTIPLIER
                if well_monthly <= 0:
                    continue
                for ln in links:
                    share = _q(well_monthly * ln.fraction)
                    if share <= 0:
                        continue
                    p = parcel_by_id[ln.parcel_id]
                    rows.append(ParcelLedger(
                        parcel=p, transaction_date=month_date, effective_date=month_date,
                        amount_acre_feet=-share, water_type=gw,
                        source_type="meter_reading",
                        description="Monthly metered groundwater extraction",
                        reporting_period=prior,
                    ))
        return rows

    # ------------------------------------------------------------------
    def _summary(self, parcels, district_zones, surface_parcel_ids,
                 curtailed_parcel_ids, entries, surface_rows):
        gsa_count = Zone.objects.filter(
            zone_type="management_area", basin_code=GSA_BASIN_CODE).count()
        total_rows = len(entries) + len(surface_rows)
        self.stdout.write(self.style.SUCCESS(
            "\nMerced synthetic accounting layer seeded:\n"
            f"  {len(parcels)} parcels keyed off water source "
            f"({len(surface_parcel_ids)} with surface delivery, "
            f"{len(curtailed_parcel_ids)} under the curtailed El Nido right)\n"
            f"  {len(district_zones)} surface-district service-area zones "
            f"(+ {gsa_count} GSA zones) carry Water Budgets for BOTH authorities\n"
            f"  {WaterAccount.objects.filter(account_number__startswith='MER-ACCT-').count()} "
            "water accounts (one per owner)\n"
            f"  {AllocationPlan.objects.filter(name__startswith='MER Surface Service Area').count()} "
            "surface budgets + GSA groundwater budgets, both periods\n"
            f"  {total_rows} ledger rows ({len(entries)} allocations + groundwater, "
            f"{len(surface_rows)} surface deliveries via allocate_district_delivery)\n"
            "  2 reporting periods (WY 2024-2025 finalized, WY 2025-2026 open)"
        ))
