# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the Merced demonstration's synthetic ACCOUNTING layer (Phase 52-01).

WHY this command exists. Phases 50–51 built the physical Merced demo — real
boundaries, rivers/canals, GSAs, water rights, points of diversion, parcels on
surveyed cropland, and wells. That canvas shows WHERE water moves. This command
adds the accounting layer that shows HOW MUCH: reporting periods, Allocations
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

TWO-AUTHORITY allocations (Brent's 2026-06-03 call). SGMA splits the jobs: the GSA
manages groundwater (a management-area zone), the irrigation district moves canal
water (a water right + PODs). Both get Allocations here. A GSA already IS a zone,
so its groundwater allocation hangs off it directly. A surface district is a water
right, NOT a zone — so this command synthesizes a ``custom`` service-area zone per
surface district (the dissolve of the parcels it serves) to hang its surface allocation
on, exactly so a canal district shows allocation-vs-delivered on screen like a GSA does.

DETERMINISTIC + IDEMPOTENT + ADDITIVE. No ``random`` (index-based jitter only), so
re-runs reproduce identical rows. The command ALWAYS flushes its OWN rows first
(the synthesized district zones, its Allocations, its accounts, and the
ParcelLedger rows on MER- parcels) then rebuilds, so a bare re-run leaves counts
unchanged. It NEVER touches Demo Valley / base-layer rows, nor the three GSA
management-area zones (those belong to seed_merced_gsas).

SIZING — estimated-ET-derived (58-03, the corrected v1.10 model). The DELIVERED
supply — surface deliveries AND meter readings — is now sized to each parcel's
ESTIMATED net consumptive-use demand (gross ET − effective precip), read from the
``CalculationRun`` rows the FIRST ``run_calculations`` pass of
``refresh_merced_accounting`` writes for EVERY parcel (54-01 spine + the 58-03
metered reference run). Supply tracks that demand within a realistic loss band
with modest per-source scatter, so per-parcel residuals land small and realistic
instead of the basin-wide ~50% under-supply 58-02 diagnosed (ISS-057). A surface
delivery over-delivers slightly; the over-delivery percolates as incidental
recharge (the engine's ``clamp_floor`` step), so a surface parcel's books close to
~0. A meter reading pumps slightly MORE than the crop consumed; that loss/return
flow has no recharge sink, so a metered parcel carries a small POSITIVE residual
(supplied a little more than consumed — never a deficit, never alarming). The flat
``area × rate × seasonal`` envelope is RETIRED as the sizing basis; ``SURFACE_RATE``
/ ``GW_RATE`` / ``SEASONAL_WEIGHTS`` survive ONLY as a fail-soft fallback for a
parcel-month that genuinely has no CalculationRun (should not happen inside the
two-pass refresh). Do NOT "restore" the flat rates — they undersupply measured ET.

APPLIED WATER IS NOW CROP DEMAND ÷ THE FIELD'S IRRIGATION-METHOD EFFICIENCY
(131-01). 58-03 sized the delivered supply as demand times a band keyed on an
INDEX — the well's index on the meter path, the point of diversion's index on
the surface path. An index is not a field: every parcel came out near-drip, and
the aggregate irrigation efficiency across all 74 valley fields measured 0.9288
whether the field was flood-irrigated alfalfa or a micro-irrigated almond block.
``health/checks.py::check_et_meter_agreement`` says so in its own docstring —
on demo data that check "measures the seeder". A district engineer reading 0.93
on border-check flood stops believing the demonstration.

So the multiple is now ``1 / efficiency``, and the efficiency comes from the
crop each parcel actually carries (``CROP_IRRIGATION`` below, one entry per crop
``seed_merced_cropland`` assigns), naming the irrigation method in words:

    Almonds    micro-sprinkler / drip   0.87   inside the cited 0.70-0.95 drip/micro band
    Grapes     drip                     0.85   inside the cited 0.70-0.95 drip/micro band
    Tomatoes   subsurface drip          0.88   inside the cited 0.70-0.95 drip/micro band
    Corn       furrow / sprinkler       0.72   inside the cited 0.55-0.75 flood/furrow band
    Alfalfa    border-check flood       0.62   inside the cited 0.55-0.75 flood/furrow band

The two bands are the only published figures this codebase cites, and they are
already cited in ``health/checks.py`` (~lines 60-63 and again in that check's
docstring). No per-crop figure here is presented as published.

The per-parcel scatter 58-03 wanted SURVIVES — ±3% deterministic, index-keyed,
through the same 8-bucket helper (``_crop_supply_ratio``). The crop sets the
centre; the index sets the scatter. Still no ``random``.

Well capacity stays out of scope for the sizing itself; CropType no longer does.

Prerequisite (the physical demo must already exist on this instance)::

    python manage.py seed_merced            # the full physical demo, OR at least:
    python manage.py seed_merced_gsas
    python manage.py seed_merced_operations
    python manage.py seed_merced_parcels_from_selection
"""
from collections import defaultdict
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
from wells.models import Well, WellIrrigatedParcel

# Phase 67-03 diversion-reach journey: the two parcel-less PODs seed_merced_operations
# places on the Merced River. Their monthly DiversionRecords are created HERE (the
# accounting layer's home — operations creates no records by design), keyed to these
# names so the two seeds stay in lock-step.
from core.management.commands.seed_merced_operations import (  # noqa: E402
    JOURNEY_DOWNSTREAM_POD,
    JOURNEY_UPSTREAM_POD,
)

# 134-01: the storm fill schedule, IMPORTED from the command that owns it rather
# than copied — the same import `seed_merced_measurements` makes. Three commands
# now describe the same storms (the events, the on-site readings, and the surface
# diversion they were taken under); one definition cannot drift from itself.
from core.management.commands.seed_merced_recharge_events import (  # noqa: E402
    DEMO_OPERATOR as RECHARGE_OPERATOR,
    RECHARGE_SEASONS,
)

MER_PARCEL_PREFIX = "MER-APN-"
# The demonstration's two water years, oldest first. Named once so the
# `--journey-only` surgical path and the main seed cannot drift apart (133-02).
DEMO_PERIOD_NAMES = ("WY 2024-2025", "WY 2025-2026")
GSA_BASIN_CODE = "5-022.04"
DISTRICT_ZONE_PREFIX = "MER Surface Service Area"

# 58-03: DELIVERED supply (surface deliveries + meter readings) is no longer sized
# from these flat rates — it tracks each parcel's MEASURED net ET demand (see the
# module docstring), because the flat rates undersupply measured ET (ISS-057). The
# rates survive for two narrow, legitimate uses ONLY: (1) a fail-soft fallback when
# a parcel-month genuinely has no CalculationRun (should not happen inside the
# two-pass refresh); (2) the paper ALLOCATION rows (`_allocation_rows`), which are
# budget CEILINGS (area × rate, the face-value water-budget grant), not delivered
# volumes — a separate concern from the delivered envelope. Do NOT re-route the
# delivered supply back through these.
SEASONAL_WEIGHTS = {
    10: 0.05, 11: 0.03, 12: 0.02, 1: 0.02, 2: 0.02, 3: 0.04,
    4: 0.08, 5: 0.14, 6: 0.16, 7: 0.16, 8: 0.15, 9: 0.13,
}
SURFACE_RATE = 2.2          # AF/acre/yr — allocation ceiling + delivery fallback
GW_RATE = 1.8               # AF/acre/yr — allocation ceiling + meter fallback

# Measured-ET supply bands (58-03). Each is a per-source multiple of a parcel's
# measured net consumptive-use demand, deterministic by parcel index so re-runs
# are stable and parcels scatter instead of tracking ET identically.
#
# SURFACE: lean generous (a canal district over-delivers; the surplus percolates
#   as incidental recharge → the parcel's books close to ~0 regardless of the
#   exact over-delivery). Always ≥ 1.0 so a non-curtailed surface parcel never
#   shows a deficit — the ONLY surface deficits in the demo come from the
#   intentional El Nido curtailment.
# METER: pumps a little MORE than the crop consumed (on-farm loss / return flow).
#   Always ≥ 1.0 so a metered farm never reads as "in trouble"; the small excess
#   is its positive, non-alarming residual (no recharge sink for a meter reading).
SURFACE_SUPPLY_LO = Decimal("1.02")   # surface over-delivery band [1.02, 1.16]
SURFACE_SUPPLY_SPAN = Decimal("0.14")
METER_SUPPLY_LO = Decimal("1.05")     # meter over-pump band [1.05, 1.18]
METER_SUPPLY_SPAN = Decimal("0.13")

# 131-01: the flat index-keyed bands above are RETIRED as the delivered-supply
# basis. They are kept because `_allocation_rows` and the no-CalculationRun
# fallbacks still reference the same idea of a deterministic band, and because
# deleting a constant a future reader may want to compare against loses the
# history. Do NOT route delivered supply back through them: an index is not a
# field, and a per-index band gives a flood-irrigated alfalfa field the same
# applied-water multiple as a micro-irrigated almond block. Measured before this
# change, the demo's aggregate irrigation efficiency was 0.9288 across all 74
# valley fields — near-drip everywhere, including the alfalfa.
#
# CROP → IRRIGATION METHOD → EFFICIENCY. One entry per crop
# `seed_merced_cropland.CROPS` assigns, round-robin by parcel index. Applied
# water is now that parcel's measured net consumptive-use demand DIVIDED by this
# efficiency, so the ratio a field carries is a property of how it is irrigated,
# not of where it sits in a list.
#
# The only bands this codebase treats as published are the two `health/checks.py`
# already cites (lines ~60-63, and again in `check_et_meter_agreement`'s
# docstring): roughly **0.70-0.95 for drip/micro** and **0.55-0.75 for
# flood/furrow**. Every value below sits inside the band for its own method.
# Three are the figures the v2.15 roadmap fixes by name (almonds, corn,
# alfalfa); the other two are chosen inside the cited band for the method that
# crop is actually grown under in the San Joaquin Valley, and are NOT presented
# as published per-crop figures — no such per-crop citation exists here.
CROP_IRRIGATION = {
    # crop:        (irrigation method,             efficiency, published band)
    "Almonds":     ("micro-sprinkler / drip",      Decimal("0.87")),  # 0.70-0.95
    "Alfalfa":     ("border-check flood",          Decimal("0.62")),  # 0.55-0.75
    "Corn":        ("furrow / sprinkler",          Decimal("0.72")),  # 0.55-0.75
    "Grapes":      ("drip",                        Decimal("0.85")),  # 0.70-0.95
    "Tomatoes":    ("subsurface drip",             Decimal("0.88")),  # 0.70-0.95
}

# Per-parcel scatter around the crop's ratio. The crop sets the CENTRE; the
# parcel index sets the scatter, so no two fields track measured ET identically
# (the property `_supply_ratio` existed to give, preserved) while the centre
# stops being an accident of ordering. ±3%, deterministic, no `random`.
CROP_SCATTER_LO = Decimal("0.97")
CROP_SCATTER_SPAN = Decimal("0.06")

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
#
# 133-02 — THIS CALENDAR IS A DECISION, NOT A LEFTOVER DATE. It is a single
# cutoff, not a per-water-year window, and that is deliberate: a curtailment
# order does not expire when the water year rolls over. `MER-CURT-001` is
# effective 2025-07-01, status `active`, with no rescission anywhere in the
# seed — so every month of WY 2025-2026 falls after the cutoff and the El Nido
# right records NO diversion at all in the open year. That is what a curtailment
# carried across a whole dry year means. The district's paper allocation for
# that year is deliberately NOT zero (`CURTAILED_OPEN_FRACTION` leaves it at a
# tenth of face value), and the gap between a 10%-of-face budget and no
# deliveries at all IS the story on screen: the board cut the allocation, and
# then the order stopped the diversions outright. Rescinding the order partway
# through the open year would be a different demonstration; it belongs to a
# phase that decides to tell it, not to a constant that lapses by accident.
CURTAILMENT_LAST_DELIVERY = date(2025, 6, 30)
# Phase 67-03 journey calendar, as MONTH NUMBERS so it reproduces in any water
# year (133-02). June/July/August are drawn fully by the downstream re-diversion
# (returned_af = 0, wholly consumptive); May is the one partially-returned month,
# so the demo shows all three points of the spectrum — 0% / partial / 100%.
JOURNEY_FULL_DRAW_MONTHS = {6, 7, 8}
JOURNEY_PARTIAL_RETURN_MONTH = 5
# The substitution bump applies ONLY on the fail-soft fallback path (a
# parcel-month with no CalculationRun). Inside the two-pass refresh every
# parcel-month has a run, so both of these are inert in the shipped demo and are
# kept for the fallback's hermetic story. Their month NUMBERS are water-year
# agnostic, so a second year needs no variant of them.
POST_CURTAILMENT_MONTHS = {7, 8, 9}
SUBSTITUTION_MULTIPLIER = Decimal("1.6")

# 134-01 — THE STORM'S HEADGATE RATE. The peak flow recorded on the CalWATRS
# "Max rate (CFS)" column for a basin fill. Same deterministic shape
# `seed_merced_measurements` uses for its canal-inflow reading (a bigger basin
# taking a bigger fill pulls more canal water), so the number on the form and the
# number on the basin's readings card describe one storm rather than two.
#
# ⛔ NO JITTER. The measurements seed adds `rng.uniform(-2.5, 2.5)` to its
# reading, because a reading is one instrument at one moment. A peak rate written
# on a state form is the district's record of the highest flow it ran — taken
# once, then transcribed. Re-rolling a random draw for it would mean the form and
# the reading disagree by a couple of cfs for no reason anyone could explain.
HEADGATE_BASE_CFS = 48.0
HEADGATE_SIZE_CFS = 38.0
# A 0.20 fill is a smaller storm than a 0.30 fill and the gates are not opened as
# far: the same 0.82 the measurements seed applies to its inflow reading.
HEADGATE_SMALL_FILL_FACTOR = 0.82
SMALL_FILL_FRACTION = Decimal("0.20")
# The recharge intake POD name prefix. `MER-BPOD-001 El Nido Canal Recharge
# Intake` has no water right of its own, so the flush needs a second handle on it.
RECHARGE_INTAKE_POD_PREFIX = "MER-BPOD-"


def _q(value):
    """Quantize to the ledger's 4 decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _jitter(seq):
    """Deterministic ±6% factor keyed on an index — varies volumes without random."""
    return Decimal("1") + (Decimal(seq % 7) - Decimal("3")) * Decimal("0.02")


def _supply_ratio(seq, lo, span):
    """A deterministic supply-to-demand multiple in ``[lo, lo + span]`` (58-03).

    Keyed on a parcel/POD index across 8 buckets so the supply scatters parcel to
    parcel (no two track measured ET identically) yet re-runs reproduce identical
    rows. ``lo``/``span`` are the per-source bands defined above.
    """
    return lo + (Decimal(seq % 8) / Decimal("7")) * span


def _crop_supply_ratio(seq, efficiency):
    """Applied-water multiple for one field: ``1 / efficiency``, scattered (131-01).

    The centre is the inverse of that field's irrigation-method efficiency — a
    0.62 border-check flood alfalfa field applies 1/0.62 ≈ 1.613 times what the
    crop consumes, a 0.87 micro-irrigated almond block 1/0.87 ≈ 1.149. The index
    then scatters ±3% around that centre through the SAME 8-bucket helper the
    retired flat bands used, so re-runs are identical and no two parcels track
    measured ET exactly.
    """
    centre = Decimal("1") / efficiency
    return _supply_ratio(seq, centre * CROP_SCATTER_LO, centre * CROP_SCATTER_SPAN)


def _period_str(month_date):
    """The ``YYYY-MM`` CalculationRun period key for a schedule month."""
    return f"{month_date.year:04d}-{month_date.month:02d}"


class Command(BaseCommand):
    help = (
        "Build the Merced demo's synthetic accounting layer (reporting periods, "
        "two-authority Allocations, accounts, and the full keyed ParcelLedger). "
        "Idempotent; additive (MER-keyed; never touches Demo Valley/base/GSA rows)."
    )

    def add_arguments(self, parser):
        # Accepted for orchestrator symmetry. The command ALWAYS flushes its own
        # rows before rebuilding, so re-runs are idempotent with or without it.
        parser.add_argument(
            "--flush", action="store_true",
            help="No-op alias: this seed always self-flushes its own rows first.",
        )
        parser.add_argument(
            "--journey-only", action="store_true",
            help="Seed ONLY the Phase 67-03 diversion-reach journey records onto "
            "the EXISTING accounting layer — no flush, no rebuild. For surgical "
            "live seeding that cannot perturb the whole-basin closure.",
        )

    def handle(self, *args, **options):
        if options.get("journey_only"):
            # 133-02: both demonstration water years, not just the finalized one.
            # A surgical journey re-seed that covered only WY 2024-2025 would leave
            # the open year's reach records behind whenever it ran.
            journey_periods = list(ReportingPeriod.objects.filter(
                name__in=DEMO_PERIOD_NAMES).order_by("start_date"))
            if not journey_periods:
                self.stdout.write(self.style.ERROR(
                    "Neither demonstration reporting period found — run the full "
                    "seed_merced_ledgers first."
                ))
                return
            with transaction.atomic():
                for rp in journey_periods:
                    self._seed_diversion_journey_records(rp)
            return
        with transaction.atomic():
            self._flush()
            self._seed()

    # ------------------------------------------------------------------
    # Flush — ONLY this seed's rows. Never the GSA zones (management_area,
    # owned by seed_merced_gsas), never Demo Valley/base-layer rows.
    # ------------------------------------------------------------------
    def _flush(self):
        # Local import: `surface` is an optional module (Phase 87), so this must
        # not run at module scope.
        from surface.models import CurtailmentOrder, DiversionRecord

        ParcelLedger.objects.filter(
            parcel__parcel_number__startswith=MER_PARCEL_PREFIX
        ).delete()

        # DiversionRecords this seed synthesizes as the recorded district total per
        # MER POD/month (the source of truth the allocation service splits). Keyed
        # to MER- rights so the flush never touches Demo Valley / base-layer records.
        DiversionRecord.objects.filter(
            point_of_diversion__water_right__right_id__startswith="MER-WR-"
        ).delete()

        # 134-01: the recharge-basin intake carries NO water right, so the filter
        # above does not reach it and its to-storage records would accumulate on
        # every re-run. This is the same defect class as the 132-01 totalizer bug
        # and it is exactly why the storm records are written HERE and not in
        # seed_merced_recharge_events: `refresh_merced_accounting`'s pass 2 re-runs
        # this command, so records written elsewhere get half-deleted —
        # MER-POD-009-DEMO carries MER-WR-008-DEMO and would be caught by the line
        # above, MER-BPOD-001 carries no right and would survive. One command owns
        # both the creation and the flush.
        DiversionRecord.objects.filter(
            point_of_diversion__name__startswith=RECHARGE_INTAKE_POD_PREFIX
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
        # Local import: `surface` is an optional module (Phase 87) — see `_flush`.
        from surface.models import PointOfDiversionParcel

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

        # --- Reporting periods (global, agency-agnostic) ---
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

        # --- Allocations for BOTH authorities, both periods ---
        self._build_budgets(gw, sw, periods, prior, open_wy, parcels, district_zones)

        # --- Water accounts (one per distinct owner) + account-parcel links ---
        self._build_accounts(parcels, prior)

        # --- Curtailment order (audit provenance for the El Nido cut) ---
        self._build_curtailment_order()

        # 58-03: each parcel-month's ESTIMATED net consumptive-use demand
        # (gross ET − effective precip), read from the CalculationRuns the first
        # run_calculations pass wrote. Supply (surface + meter) is sized to THIS,
        # so the seed sizes against the SAME ET the mass balance later checks.
        net_cu = self._net_cu_by_parcel_month(parcels, periods)

        # --- Paper allocation (budget-ceiling) rows ---
        entries = self._allocation_rows(parcels, surface_parcel_ids, gw, sw, periods)
        ParcelLedger.objects.bulk_create(entries, batch_size=500)

        # 131-01: each field's irrigation efficiency, resolved from its crop once
        # (single joined query) and read from a dict inside both supply loops. It is
        # a property of the FIELD, not of the year, so it is resolved ONCE outside
        # the per-period loop and both water years share it (133-02).
        eff_by_parcel = self._efficiency_by_parcel(parcels)

        # --- THE SUPPLY SIDE, ONCE PER REPORTING PERIOD (133-02). Before this, the
        # month schedule was hardcoded to WY 2024-2025's twelve months, so the open
        # water year carried a full demand side and no supply at all. Within a period
        # the ordering is unchanged and still load-bearing: surface FIRST, then
        # meters against the demand surface left unmet. Across periods the ledger
        # keys are month-scoped, so neither year can see the other's rows. ---
        surface_rows = []
        gw_rows = []
        for rp in periods:
            # Surface deliveries FIRST: synthesize the recorded district total per
            # POD, then let the PLATFORM service split it across served parcels by
            # ET demand. The service writes the negative surface_diversion rows.
            surface_rows.extend(self._surface_deliveries(
                parcels, curtailed_parcel_ids, rp, net_cu, eff_by_parcel))

            # Meter readings AFTER surface: a metered parcel's groundwater covers
            # only the ET demand its surface delivery did NOT meet (the same residual
            # the engine computes for an UNMETERED conjunctive parcel), so a parcel
            # with both sources is never double-supplied. Sized from the surface
            # actually delivered, within the over-pump band. The lookup is keyed
            # (parcel, "YYYY-MM"), so re-reading it inside the loop returns this
            # period's months and the other year's rows are simply never asked for.
            surface_by_pm = self._surface_by_parcel_month(parcels)
            period_gw_rows = self._groundwater_rows(
                parcels, curtailed_parcel_ids, gw, rp, net_cu, surface_by_pm,
                eff_by_parcel)
            ParcelLedger.objects.bulk_create(period_gw_rows, batch_size=500)
            gw_rows.extend(period_gw_rows)

            # Phase 67-03: the visible water journey (non-consumptive passthrough +
            # downstream re-diversion). Parcel-less PODs -> zero ledger supply ->
            # closure untouched. Recreated AFTER the flush so a `make merced` re-run
            # reproduces it.
            self._seed_diversion_journey_records(rp)

        # 134-01: the high-flow diversions the managed basin fills were taken
        # under. AFTER the period loop closes, not inside it, and that placement
        # is load-bearing. `surface.services._records_for_period` selects a POD's
        # records by period FK *or* month span and does NOT filter on
        # `diversion_type`, so `allocate_district_delivery` would happily split a
        # to-storage record across the parcels its intake serves — and
        # MER-POD-009-DEMO serves ten. Writing these after every
        # `allocate_district_delivery` call in the build has been made means no
        # allocator run can ever see one, without depending on which month lands
        # in which period. ⚠ Do not move this back inside the loop.
        for rp in periods:
            self._seed_recharge_diversion_records(rp)

        entries = entries + gw_rows  # combined ledger count for the summary

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
        # Local import: `surface` is an optional module (Phase 87) — see `_flush`.
        from surface.models import WaterRightParcel

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
                        "Surface Allocation (a district is a right, not a zone)."
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
    # Allocations
    # ------------------------------------------------------------------
    def _build_budgets(self, gw, sw, periods, prior, open_wy, parcels, district_zones):
        # GSA groundwater allocations — one per GSA zone, both periods. Sized to a
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
                        "notes": "SGMA sustainable-yield groundwater allocation (demo).",
                    },
                )

        # Surface-district allocations — one per district zone, both periods, sized near
        # the right's face value. The curtailed district's CURRENT-year allocation
        # collapses to reflect the curtailment, so the on-screen story stays honest.
        for right_id, (zone, right) in district_zones.items():
            face = Decimal(str(right.face_value_acre_feet or 0))
            base = _q(face * SURFACE_BUDGET_FRACTION)
            curtailed = right.status == "curtailed"
            for rp in periods:
                if curtailed and rp is open_wy:
                    amount = _q(face * CURTAILED_OPEN_FRACTION)
                    note = "Surface allocation reduced — junior right curtailed this year."
                else:
                    amount = base
                    note = "Surface Allocation (~face value of the district's right)."
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
        WY 2024-2025, where the full year of transactions lives (mirroring the prior demo,
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
        # Local import: `surface` is an optional module (Phase 87) — see `_flush`.
        from surface.models import CurtailmentOrder, WaterRight

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

    def _month_schedule(self, period):
        """(date, month_num) for each month of ``period``, day 15.

        133-02: walks the ReportingPeriod's OWN start/end dates. It used to
        hardcode ``2024 if mn >= 10 else 2025``, which is why the open water year
        had a full demand side and no supply at all — every one of this method's
        four callers built WY 2024-2025 and nothing else. Reading the dates off
        the period means a second water year needs no second code path, and a
        period whose dates are edited needs no code change either.

        Day 15 is the mid-month convention the whole seed uses: `DiversionRecord`
        is unique on (POD, month, type), and the engine keys `CalculationRun` by
        ``YYYY-MM``, so the day is a label rather than a date.
        """
        schedule = []
        year, month = period.start_date.year, period.start_date.month
        while date(year, month, 15) <= period.end_date:
            schedule.append((date(year, month, 15), month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
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
                agency_name="Halvern Valley GSA",
                default_irrigation_efficiency=SEED_IRRIGATION_EFFICIENCY,
            )
        elif not config.default_irrigation_efficiency:
            config.default_irrigation_efficiency = SEED_IRRIGATION_EFFICIENCY
            config.save(update_fields=["default_irrigation_efficiency"])

    def _net_cu_by_parcel_month(self, parcels, periods):
        """Map ``(parcel_id, "YYYY-MM") -> measured net consumptive-use demand``.

        Reads the ``CalculationRun`` rows the first ``run_calculations`` pass wrote
        for every parcel (54-01 spine + 58-03 metered reference run), scoped to the
        months of every period being seeded (133-02 — one query for both water
        years, never one per year inside a loop). ``net_consumptive_use_af`` is gross ET minus
        effective precip — the demand the supply must meet — and is stable across
        the two passes (it never depends on surface or meter readings), so sizing
        supply against it guarantees the seed and the mass balance use the SAME ET.
        """
        from accounting.models import CalculationRun

        parcel_ids = [p.id for p in parcels]
        period_keys = sorted({
            _period_str(d)
            for rp in periods
            for d, _ in self._month_schedule(rp)
        })
        out = {}
        for run in CalculationRun.objects.filter(
            parcel_id__in=parcel_ids, period__in=period_keys
        ).values_list("parcel_id", "period", "net_consumptive_use_af"):
            out[(run[0], run[1])] = run[2] or Decimal("0")
        return out

    def _efficiency_by_parcel(self, parcels):
        """Map ``parcel_id -> irrigation efficiency`` from each field's crop (131-01).

        ONE query over the crop-type ``UsageLocation`` rows
        ``seed_merced_cropland`` wrote, joined to ``CropType``, read into a dict
        before the ledger loops — never a per-parcel query inside a monthly loop.

        A parcel with no crop-type usage location falls back to the agency-wide
        ``SEED_IRRIGATION_EFFICIENCY`` (0.750, the same value the seed installs on
        ``SiteConfig`` and the surface kernel reads) rather than being skipped: a
        missing crop must change the parcel's ratio, never silently drop water out
        of the ledger. A crop present in the data but absent from
        ``CROP_IRRIGATION`` takes the same fallback.
        """
        from parcels.models import UsageLocation

        parcel_ids = [p.id for p in parcels]
        out = {}
        for usage in UsageLocation.objects.filter(
            parcel_id__in=parcel_ids, crop_type__isnull=False
        ).select_related("crop_type"):
            method_eff = CROP_IRRIGATION.get(usage.crop_type.name)
            if method_eff is not None:
                out[usage.parcel_id] = method_eff[1]
        return out

    def _efficiency_for(self, eff_by_parcel, parcel_id):
        """That parcel's irrigation efficiency, or the agency-wide default."""
        return eff_by_parcel.get(parcel_id, SEED_IRRIGATION_EFFICIENCY)

    def _surface_by_parcel_month(self, parcels):
        """Map ``(parcel_id, "YYYY-MM") -> delivered surface magnitude (positive AF)``.

        Reads the negative ``surface_diversion`` rows the allocation service just
        wrote, summed per parcel-month, so the meter sizing can subtract the surface
        a parcel already received and bill groundwater only for the residual.
        """
        parcel_ids = [p.id for p in parcels]
        out = {}
        for row in ParcelLedger.objects.filter(
            parcel_id__in=parcel_ids, source_type="surface_diversion"
        ).values_list("parcel_id", "effective_date", "amount_acre_feet"):
            key = (row[0], f"{row[1].year:04d}-{row[1].month:02d}")
            out[key] = out.get(key, Decimal("0")) + abs(row[2] or Decimal("0"))
        return out

    def _surface_deliveries(self, parcels, curtailed_parcel_ids, period, net_cu,
                            eff_by_parcel):
        """Surface deliveries, produced by the PLATFORM allocation service.

        This is the 55-03 wiring: the seed no longer sizes each parcel's delivery
        with its own private math. Instead it does what a real district does —
        records the MONTHLY DISTRICT TOTAL that left each point of diversion (a
        ``DiversionRecord``, the source of truth) — then calls
        ``surface.services.allocate_district_delivery`` to split that total across
        the served parcels. The service weights the split by each parcel's measured
        ET demand for the month (the 54-01 spine) when calculations have run, and
        falls back to the static ``PointOfDiversionParcel.fraction`` split when they
        have not. Either way it writes the NEGATIVE ``surface_diversion`` rows the
        calc engine consumes — the SAME tested path the app uses, so the seed and
        the app can never drift.

        58-03 sizing: the recorded district total per POD/month is the sum over its
        served parcels of each parcel's MEASURED net consumptive-use demand
        (``net_cu``, from the first run_calc pass) times a per-POD surface
        over-delivery ratio (always ≥ 1.0). The measured ET already carries real
        seasonality, so no synthetic seasonal weight is applied — the monthly total
        IS that month's measured demand, lifted by the loss band. The over-delivery
        percolates as incidental recharge, so served parcels close to ~0. A
        parcel-month with no run (should not happen inside the two-pass refresh)
        fails soft to the retired flat ``area × SURFACE_RATE × jitter × seasonal``.
        Curtailed PODs record NO diversion after June 2025 — the El Nido cut — so
        the service produces no post-curtailment deliveries for their parcels; the
        resulting summer shortfall on their surface-only parcels is the intentional
        scarcity demonstration, not a sizing error. 133-02: because the cutoff is a
        date and not a per-year window, that also means a curtailed POD records
        nothing at all across WY 2025-2026 — see the constant's comment block.

        133-02: called ONCE PER REPORTING PERIOD. The ``period`` argument sets both
        the month schedule and the ``reporting_period`` stamped on each
        ``DiversionRecord`` — that FK matters, because ``_records_for_period``
        matches a record on its FK **OR** its month falling inside the period span,
        so a second year's records carrying the first year's FK would be allocated
        against BOTH periods.

        Returns the list of ``ParcelLedger`` surface rows the service wrote (for the
        summary count); the service has already persisted them.
        """
        # Local imports: `surface` is an optional module (Phase 87) — see `_flush`.
        from surface.models import (
            DiversionRecord,
            PointOfDiversion,
            PointOfDiversionParcel,
        )
        from surface.services import allocate_district_delivery

        schedule = self._month_schedule(period)
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
        for pod_seq, pod in enumerate(pods):
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
            # served parcels' MEASURED net ET demand for the month, lifted by the
            # over-delivery band. This is the metered truth the platform splits;
            # idempotent via update_or_create on the (POD, month, type) unique key.
            for month_date, mn in schedule:
                if curtailed and month_date > CURTAILMENT_LAST_DELIVERY:
                    continue  # no diversion recorded once the junior right is cut
                month_key = _period_str(month_date)
                total = Decimal("0")
                for p in served:
                    demand = net_cu.get((p.id, month_key))
                    if demand is not None and demand > 0:
                        # 131-01: per-PARCEL, not per-POD. Each served field's
                        # demand is divided by ITS OWN crop's irrigation-method
                        # efficiency, so one canal can serve a flood-irrigated
                        # alfalfa field and a drip almond block and deliver the
                        # right multiple to each. The kernel below takes ONE
                        # efficiency per call (per POD) and changing that is an
                        # engine change this milestone forbids — so the
                        # differentiation happens HERE, in the recorded district
                        # total the kernel then splits by ET demand.
                        total += demand * _crop_supply_ratio(
                            seq_of.get(p.id, 0),
                            self._efficiency_for(eff_by_parcel, p.id),
                        )
                    else:
                        # Fail-soft fallback (no run this parcel-month).
                        area = Decimal(str(p.area_acres or 40))
                        total += (
                            area * Decimal(str(SURFACE_RATE))
                            * _jitter(seq_of.get(p.id, 0))
                            * Decimal(str(SEASONAL_WEIGHTS[mn]))
                        )
                total = _q(total)
                if total <= 0:
                    continue
                DiversionRecord.objects.update_or_create(
                    point_of_diversion=pod,
                    month=month_date,
                    diversion_type="direct_use",
                    defaults={
                        "reporting_period": period,
                        "volume_acre_feet": total,
                    },
                )

            # Let the platform service split the recorded totals across parcels by
            # ET demand (or the static fraction fallback) and write the negative
            # surface_diversion rows. Same path the app uses.
            written.extend(allocate_district_delivery(pod, period))

        self.stdout.write(
            f"    surface deliveries [{period.name}]: {len(written)} row(s) written "
            f"by allocate_district_delivery across {pods.count()} POD(s)"
        )
        return written

    def _groundwater_rows(self, parcels, curtailed_parcel_ids, gw, period, net_cu,
                          surface_by_pm, eff_by_parcel):
        """Monthly groundwater extraction (NEGATIVE) for METERED wells ONLY.

        The metering split is the 52-01 dual-source invariant: wells alternate
        metered / unmetered. The two halves are handled differently:

        - A METERED well's reading is authoritative. 58-03 sizes each served
          parcel's monthly reading to the RESIDUAL groundwater it actually needed —
          its MEASURED net ET demand (``net_cu``, from the first run_calc pass) MINUS
          the surface already delivered to it that month — divided by that field's
          own crop irrigation-method efficiency (131-01; the ratio used to be a
          per-WELL index band, but a well can irrigate several parcels growing
          different crops, so the crop is resolved PER SERVED PARCEL through the
          ``WellIrrigatedParcel`` links and each link's share is scaled by its own
          ratio before the fraction weighting). This mirrors exactly what the engine computes for an UNMETERED
          conjunctive parcel (``ET − precip − surface``), so a parcel with BOTH a
          meter and a surface delivery is never double-supplied: its meter reads ~0
          when surface covered its ET, and rises (the substitution story) when
          surface is curtailed. A groundwater-only metered parcel (no surface) reads
          its full demand × the band. Readings are stored NEGATIVE (production
          convention). NO synthetic substitution bump is applied on the ET path —
          surface curtailment lifts the residual on its own. The bump + the
          fraction-split well total survive ONLY on the fallback path (a parcel-month
          with no run), to preserve the hermetic demo story.

        - An UNMETERED well writes NO synthetic groundwater rows. Its parcels'
          groundwater is computed by the REAL calc engine (``calculated`` rows); a
          synthetic row here would double-count. The well still gets
          ``measurement_method='unmetered_estimate'`` so the metered/unmetered story
          survives. The substitution story for these parcels EMERGES from the engine:
          surface deliveries stop after curtailment, so the engine subtracts less
          surface → more net groundwater in the dry months.
        """
        parcel_by_id = {p.id: p for p in parcels}
        # Parcel index → the deterministic scatter key, the SAME one the surface
        # path uses, so a parcel's ±3% offset is a property of the parcel rather
        # than of which supply path is writing it.
        seq_of = {p.id: i for i, p in enumerate(parcels)}
        # well -> [WellIrrigatedParcel links] for MER wells irrigating MER parcels.
        wells = list(Well.objects.filter(
            well_registration_id__startswith="MER-W-").order_by("well_registration_id"))
        links_by_well = {}
        for ln in WellIrrigatedParcel.objects.filter(
            well__in=wells, parcel_id__in=parcel_by_id
        ):
            links_by_well.setdefault(ln.well_id, []).append(ln)

        schedule = self._month_schedule(period)
        rows = []
        for wseq, well in enumerate(wells):
            links = links_by_well.get(well.id)
            if not links:
                continue
            # Alternate metered / unmetered so the demo exercises both stories.
            # The assignment is a property of the WELL, not of the water year, so
            # calling this once per period (133-02) re-derives the identical value
            # and the guarded update below writes nothing on the second pass.
            metered = (wseq % 2 == 0)
            method = "certified_meter" if metered else "unmetered_estimate"
            if well.measurement_method != method:
                Well.objects.filter(pk=well.pk).update(measurement_method=method)

            # Unmetered wells are engine-owned: the method is set (above) but the
            # seed writes no synthetic extraction, so the engine's `calculated`
            # rows never double-count.
            if not metered:
                continue

            substitutes = any(ln.parcel_id in curtailed_parcel_ids for ln in links)
            # Fallback basis (used only for a parcel-month with no CalculationRun).
            served_acres = sum(
                Decimal(str(parcel_by_id[ln.parcel_id].area_acres or 40)) * ln.fraction
                for ln in links
            )
            well_annual = served_acres * Decimal(str(GW_RATE)) * _jitter(wseq)

            for month_date, mn in schedule:
                month_key = _period_str(month_date)
                # ET path: size EACH served parcel's reading to its RESIDUAL
                # groundwater need = measured net ET demand MINUS the surface already
                # delivered that month, DIVIDED by that field's own crop
                # irrigation-method efficiency (131-01). A parcel fully met
                # by surface reads ~0; a groundwater-only parcel (no surface) reads
                # its full demand ÷ its efficiency — always a positive residual,
                # never a deficit, no double-supply for a conjunctive parcel. The
                # ratio is resolved per PARCEL, not per well: a shared well can
                # irrigate an alfalfa field and an almond block, and each reads its
                # own multiple. `ln.fraction` is deliberately NOT applied here — on
                # the ET path the demand is already per parcel, so the well total is
                # the sum of its parcels' needs rather than a split of one figure.
                # Fallback (no run this parcel-month): the flat seasonal envelope
                # split by fraction, with the curtailment substitution bump.
                demands = {
                    ln.parcel_id: net_cu.get((ln.parcel_id, month_key))
                    for ln in links
                }
                has_demand = any(d is not None and d > 0 for d in demands.values())
                if has_demand:
                    shares = {}
                    for ln in links:
                        demand = demands[ln.parcel_id] or Decimal("0")
                        surf = surface_by_pm.get(
                            (ln.parcel_id, month_key), Decimal("0"))
                        gw_need = demand - surf
                        if gw_need < 0:
                            gw_need = Decimal("0")
                        shares[ln.parcel_id] = _q(gw_need * _crop_supply_ratio(
                            seq_of.get(ln.parcel_id, 0),
                            self._efficiency_for(eff_by_parcel, ln.parcel_id),
                        ))
                else:
                    well_monthly = well_annual * Decimal(str(SEASONAL_WEIGHTS[mn]))
                    if substitutes and mn in POST_CURTAILMENT_MONTHS:
                        well_monthly *= SUBSTITUTION_MULTIPLIER
                    shares = {
                        ln.parcel_id: _q(well_monthly * ln.fraction) for ln in links
                    }
                for ln in links:
                    share = shares[ln.parcel_id]
                    if share <= 0:
                        continue
                    p = parcel_by_id[ln.parcel_id]
                    rows.append(ParcelLedger(
                        parcel=p, transaction_date=month_date, effective_date=month_date,
                        amount_acre_feet=-share, water_type=gw,
                        source_type="meter_reading",
                        description="Monthly metered groundwater extraction",
                        reporting_period=period,
                    ))
        return rows

    # ------------------------------------------------------------------
    # Diversion-reach journey records (Phase 67-03)
    # ------------------------------------------------------------------
    def _seed_diversion_journey_records(self, period):
        """Recorded diversions for the two parcel-less journey PODs.

        The UPSTREAM hydroelectric passthrough (seed_merced_operations placed it on
        the Merced River) returns its FULL volume to the stream every month
        (``returned_af == volume_acre_feet`` → ``consumed_acre_feet() == 0``), so it
        writes a zero consumed magnitude and cannot touch the consumptive spine. The
        DOWNSTREAM re-diversion (linked one hop via ``rediverted_from``) draws on
        that return flow as ordinary consumptive water — three summer months fully
        consumed (``returned_af == 0``) plus ONE partially-returned spring month, so
        the demo shows all three points of the spectrum (0% / partial / 100%).

        SPINE-SAFE BY CONSTRUCTION: both PODs serve no parcels, so
        ``allocate_district_delivery`` writes no ``surface_diversion`` rows for them;
        the records are visible on the detail pages + in CalWATRS (gross Volume AF +
        Return Flow AF) but contribute nothing to the whole-basin balance.
        ``update_or_create`` on the ``(POD, month, type)`` unique key → idempotent.

        133-02: the calendar comes from ``period`` rather than four literal 2025
        dates. The hydro passthrough runs every month of whichever year is being
        seeded; the downstream re-diversion draws in that year's June/July/August
        and returns part of its May. Those are MONTH NUMBERS, so the same shape
        reproduces in any water year — and for WY 2024-2025 it reproduces the
        exact five records the literals used to write.
        """
        # Local import: `surface` is an optional module (Phase 87) — see `_flush`.
        from surface.models import DiversionRecord, PointOfDiversion

        upstream = PointOfDiversion.objects.filter(name=JOURNEY_UPSTREAM_POD).first()
        downstream = PointOfDiversion.objects.filter(
            name=JOURNEY_DOWNSTREAM_POD).first()
        if upstream is None or downstream is None:
            self.stdout.write(self.style.WARNING(
                "    diversion-reach journey PODs not found — run "
                "seed_merced_operations first; skipping journey records."
            ))
            return

        created = 0
        # Upstream: a steady run-of-river hydro passthrough, 100% returned, every
        # month of the water year being seeded. consumed == 0 on every row.
        hydro_af = Decimal("1200.0000")
        for month_date, _mn in self._month_schedule(period):
            DiversionRecord.objects.update_or_create(
                point_of_diversion=upstream, month=month_date,
                diversion_type="direct_use",
                defaults={"reporting_period": period,
                          "volume_acre_feet": hydro_af, "returned_af": hydro_af},
            )
            created += 1

        # Downstream re-diversion: summer months drawn fully (consumptive), well
        # under the upstream return flow it draws on; one spring month partial.
        for month_date, mn in self._month_schedule(period):
            if mn in JOURNEY_FULL_DRAW_MONTHS:
                volume, returned = Decimal("300.0000"), Decimal("0")
            elif mn == JOURNEY_PARTIAL_RETURN_MONTH:
                volume, returned = Decimal("250.0000"), Decimal("100.0000")
            else:
                continue
            DiversionRecord.objects.update_or_create(
                point_of_diversion=downstream, month=month_date,
                diversion_type="direct_use",
                defaults={"reporting_period": period,
                          "volume_acre_feet": volume, "returned_af": returned},
            )
            created += 1

        self.stdout.write(
            f"    diversion-reach journey [{period.name}]: {created} records "
            "(upstream hydro 100%-returned, downstream re-diversion + 1 partial)"
        )

    def _seed_recharge_diversion_records(self, period):
        """The surface-side paper for every managed basin fill (134-01).

        ``MER-BPOD-001 El Nido Canal Recharge Intake`` carries the note "Operated
        during high-flow/storm events to divert water for managed aquifer
        recharge" and, directly beneath it on the same page, "No diversion records
        yet." Nothing had ever flowed through it. The basins it feeds were being
        filled by 42 ``RechargeEvent`` rows with no diverted water behind them.

        One ``to_storage`` record per fill month per feeding point of diversion.
        Six fill dates across the two water years and two feeding points → twelve
        records, eight in the wet year and four in the dry.

        EVERY NUMBER IS DERIVED, none typed:

          * ``volume_acre_feet`` is the sum of the fills that point fed on that
            date — capacity × the season's fraction, the same arithmetic
            ``seed_merced_recharge_events`` uses to size the events themselves.
            POSITIVE, matching all 161 existing records; the model docstring's
            remark about a negative production convention describes the surface
            *delivery* path, and this seed has never followed it.
          * ``max_flow_rate_cfs`` is the summed peak headgate rate — see
            ``HEADGATE_BASE_CFS`` for the shape and for why the measurements
            seed's ±2.5 jitter is deliberately dropped. It is the PEAK: flow is
            highest on day one and throttled back as the basin fills, which is
            why a 3-day event span and a ~1.4-day fill volume are not in conflict.
          * ``reporting_period`` is set EXPLICITLY (133-02). ``_records_for_period``
            matches on the FK *or* the month span, so a missing or stale FK
            double-allocates.
          * ``returned_af`` is 0. Water diverted into a recharge basin percolates;
            none of it goes back to the stream.

        ⛔ ``create_diversion_ledger_entries`` is NOT called on these records, and
        must never be. The recharge credit already reaches the basin pool through
        ``create_recharge_ledger_entries``; calling it here would count the same
        water twice — and ``MER-BPOD-001`` has neither parcel links nor a water
        right, so it would raise rather than silently double. Nothing outside
        ``reporting/`` reads ``DiversionRecord``, so these rows appear on the POD
        page and in the CalWATRS "To Storage" filing and touch no parcel's account.

        Side effect worth naming: ``validate_report(period, "calwatrs_a2")`` used
        to ERROR in BOTH water years — "No to storage diversion records for this
        period" — because all 161 seeded records were ``direct_use``. One of the
        four report layouts the platform ships could not be produced from the
        demonstration. A basin fill IS a to-storage diversion, so writing these
        fixes that as a consequence rather than as separate work.
        """
        # `recharge` is an optional module (ISS-072) and `surface` is optional too
        # (Phase 87) — see `_flush`. With recharge off there are no basins to fill,
        # so there is nothing to record and nothing to import.
        from core.modules import is_enabled

        if not is_enabled("recharge"):
            return
        from recharge.models import RechargeSite, RechargeSitePOD
        from surface.models import DiversionRecord

        season = RECHARGE_SEASONS.get(period.name)
        if not season:
            return

        sites = list(
            RechargeSite.objects.filter(
                operator=RECHARGE_OPERATOR, site_type="spreading_basin"
            )
        )
        if not sites:
            self.stdout.write(self.style.WARNING(
                "    recharge intake diversions: no recharge areas found — run "
                "seed_merced_basins_from_selection first; skipping."
            ))
            return

        # The size scale is taken across ALL the district's basins, not across one
        # intake's share of them, so the same basin gets the same headgate rate
        # whichever point of diversion happens to feed it. This is the identical
        # scaling `seed_merced_measurements._seed_recharge_measurements` computes.
        capacities = [float(s.capacity_acre_feet or 0) for s in sites]
        cap_min, cap_max = min(capacities), max(capacities)
        cap_span = (cap_max - cap_min) or 1.0

        # Group the basins by the point of diversion that fills them. A basin with
        # no POD link has no surface paper to write and is simply skipped.
        sites_by_pod = defaultdict(list)
        for link in RechargeSitePOD.objects.filter(
            recharge_site__in=sites
        ).select_related("point_of_diversion"):
            sites_by_pod[link.point_of_diversion].append(link.recharge_site)

        created = 0
        for pod in sorted(sites_by_pod, key=lambda p: p.name):
            fed = sorted(sites_by_pod[pod], key=lambda s: s.name)
            for fill_date, fraction in season:
                # Belt and braces on the FK: the season is keyed by the period's
                # own name, and the fill must also fall inside the period's span.
                # A schedule edited into the wrong year should stop here rather
                # than attach a record to a period that does not contain it.
                if not (period.start_date <= fill_date <= period.end_date):
                    continue

                volume = Decimal("0")
                peak_cfs = 0.0
                filled = []
                for site in fed:
                    capacity = site.capacity_acre_feet or Decimal("0")
                    vol = (capacity * fraction).quantize(Decimal("0.0001"))
                    if vol <= 0:
                        continue
                    volume += vol
                    size = (float(capacity) - cap_min) / cap_span
                    rate = HEADGATE_BASE_CFS + HEADGATE_SIZE_CFS * size
                    if fraction == SMALL_FILL_FRACTION:
                        rate *= HEADGATE_SMALL_FILL_FACTOR
                    peak_cfs += rate
                    filled.append(site.name)

                if volume <= 0:
                    continue

                month_name = fill_date.strftime("%B %Y")
                DiversionRecord.objects.update_or_create(
                    point_of_diversion=pod,
                    month=fill_date,
                    diversion_type="to_storage",
                    defaults={
                        "reporting_period": period,
                        "volume_acre_feet": _q(volume),
                        "returned_af": Decimal("0"),
                        "max_flow_rate_cfs": _q(peak_cfs),
                        "notes": (
                            f"High-flow diversion on the {month_name} storm, "
                            f"taken to storage for managed aquifer recharge and "
                            f"spread across {len(filled)} basin(s): "
                            f"{', '.join(filled)}. Rate is the peak at the "
                            f"headgate; flow was throttled back as the basins "
                            f"filled. None returned to the stream."
                        ),
                    },
                )
                created += 1

        self.stdout.write(
            f"    recharge intake diversions [{period.name}]: {created} "
            f"to-storage record(s) across {len(sites_by_pod)} intake(s)"
        )

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
            f"(+ {gsa_count} GSA zones) carry Allocations for BOTH authorities\n"
            f"  {WaterAccount.objects.filter(account_number__startswith='MER-ACCT-').count()} "
            "water accounts (one per owner)\n"
            f"  {AllocationPlan.objects.filter(name__startswith='MER Surface Service Area').count()} "
            "surface allocations + GSA groundwater allocations, both periods\n"
            f"  {total_rows} ledger rows ({len(entries)} allocations + groundwater, "
            f"{len(surface_rows)} surface deliveries via allocate_district_delivery)\n"
            "  2 reporting periods (WY 2024-2025 finalized, WY 2025-2026 open)"
        ))
