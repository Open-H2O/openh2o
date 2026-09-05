# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the Merced demo's MEASUREMENT record: what the district actually read.

The structural seeds build the district — basins, wells, meters, parcels, a
ledger — and then leave every instrument table empty. Seven recharge basin pages
say "No measurements recorded." next to an event history showing hundreds of
acre-feet delivered, which reads as a platform monitoring nothing it recharges.
Behind them, ``check_conformance`` reports a clean bill of health having examined
zero measurements: green because it is empty, which is the worst shape a gate can
take (``tests/test_standards_registry.py`` names this in its own words).

This command writes the five slices ISS-105 flagged, all in one place because
they are one story — a water year of fieldwork:

  1. ``recharge.RechargeMeasurement`` — on-site monitoring at the seven basins
     across the WY 2024-2025 wet season: ponded depth, canal inflow, percolation
     rate, source-water TDS. THE ONE SLICE WITH A SCREEN (the recharge detail
     page's "Recent measurements" card, ``recharge/views.py``).
  2. ``wells.MonitoringWell`` — the three ag wells that double as water-level
     monitoring points. Rendered by ``templates/wells/partials/_detail_pane.html``
     (a section that has never had a row to show), and the prerequisite for 3-5:
     each instrument's cadence is read off the frequency its own well declares.
  3. ``measurements.MeterReading`` — monthly totalizer reads on the 12 certified
     meters, reconciled to the ledger's metered groundwater to the acre-foot.
  4. ``measurements.Sensor`` + ``SensorMeasurement`` — the one pressure
     transducer the demo declares, logging DAILY. Not streaming: PROJECT.md rules
     real-time telemetry out of scope, so this is a data logger downloaded on a
     schedule and nothing else.
  5. ``measurements.WaterMeasurement`` — the hand-entered counterpart: manual
     sounder readings at the cadence each monitoring well declares, sitting a few
     hundredths off the transducer where the two overlap. That small disagreement
     is the realistic part, and is what a ``quality`` flag exists to carry.

DESIGN — the same three rules the rest of the Merced seed follows:

  * **Deterministic.** Every jittered value comes from a ``random.Random`` seeded
    by a stable string key (site name + date, meter serial, well id + day). No
    bare ``random``, no ``datetime.now()``. Two builds of the same commit produce
    byte-identical rows, because ``data/demo/expected_shape.json`` pins every
    count at tolerance 0 and a wobbling number turns promotion gate 2 into a coin
    flip.
  * **Idempotent.** Self-flushes exactly its own rows before recreating them, the
    way ``seed_merced_recharge_events`` does. Re-running cannot duplicate.
  * **Accounting-safe.** Writes to five instrument tables and nothing else.
    ``measurements.MeterReading`` is NOT what the engine reads — the accounting
    spine reads ``ParcelLedger`` rows of source type ``meter_reading``, a
    different thing with nearly the same name (``seed_merced_details``:19-22).
    This command reads that ledger and never writes to it. ``ParcelLedger``,
    ``DiversionRecord`` and ``UnallocatedDelivery`` must not move, and
    ``tests/test_merced_measurements.py`` asserts they do not.

⛔ NO USER FK IS EVER SET. ``MeterReading.read_by`` and
``WaterMeasurement.recorded_by`` point at ``AUTH_USER_MODEL``, and promotion gate
2 requires ``core.User = 0`` — ``scripts/rebuild-golden.sh`` skips
``ensure_superuser`` specifically to keep it there. Attaching a reader to a
reading would create the one row that mechanism exists to prevent. Provenance
goes in ``notes``.

TWO PLAN PREMISES THAT DID NOT SURVIVE THE SOURCE, recorded so the next reader
does not re-derive them:

  * The seeded ``RechargeEvent`` rows used to carry ``end_date = NULL`` — every
    one of them — so there was no event window to place a reading "inside", and
    the fill window was defined here instead: a storm fill worked over the ~5 days
    after the gates open, with the reading offsets below counted from
    ``start_date``. **134-01 gave the events a real 3-day span**
    (``FILL_SPAN_DAYS`` in the events seed) and chose that length so all four
    notes below stay true. The offsets are still counted from ``start_date`` and
    MUST stay that way — deriving one from ``end_date`` would make a future span
    change silently re-date 126 readings. ``tests/test_merced_recharge_events.py``
    locks the reading-inside-the-fill invariant in both directions.
  * ``MONITORING_WELLS`` lives in ``scripts/export_merced_native.py``, an export
    for the native app — NOT in any Django seed, and ``wells.MonitoringWell`` was
    empty. Those three declarations are the demo's own record of which wells are
    monitored and how often, so they are carried across here verbatim rather than
    re-invented, and this command creates the rows.

Runs LAST in the Merced chain (before ``seed_merced_drinking``): it reads the
recharge events, the ledger, and the meters, so every one of those seeds must
have run first.
"""
import datetime
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# The basin fill schedule lives in the events seed and is imported, not copied
# (133-02) — the two commands describe the same storms and must not drift.
from core.management.commands.seed_merced_recharge_events import (  # noqa: E402
    RECHARGE_SEASONS,
)

# The single readable key that finds the demo district's basins without
# hardcoding names — the same key seed_merced_recharge_events uses. Fictional
# since Phase 97: these readings are invented, so they must never be attributed
# to a real district.
DEMO_OPERATOR = "Halvern Irrigation District"

# The fill schedule seed_merced_recharge_events writes its events on — IMPORTED
# from that command rather than copied (133-02). It used to be a second literal
# list here with a comment saying the two were "kept in step by test, not by
# hope"; no such test existed, and a reading dated outside its basin's fill is a
# reading of nothing. One definition cannot drift from itself.
#
# A season is a list of (date, fraction-of-capacity). A 0.30 fill ponds deeper
# and runs the canal harder than a 0.20 fill; the readings below have to say so,
# or the card contradicts the event history printed beside it on the same page.
# The dry year's season is shorter AND smaller — see RECHARGE_SEASONS' comment.
FILL_SEASONS = RECHARGE_SEASONS

# The span everything here is measured across: BOTH water years, as one
# continuous instrument record. A logger and a totalizer do not restart on
# October 1 — the water-year boundary is an accounting convention, not an
# instrument event — so these bound the whole record rather than one year.
RECORD_START = datetime.date(2024, 10, 1)
RECORD_END = datetime.date(2026, 9, 30)
DAYS_IN_FIRST_WY = (datetime.date(2025, 9, 30) - RECORD_START).days  # 364
# Month-end read dates for the totalizers, one per month of BOTH water years
# (133-02). A totalizer is a lifetime counter: it does not reset at the water
# year boundary, so the second year continues the first year's running value.
WY_MONTHS = [
    (2024, 10), (2024, 11), (2024, 12),
    (2025, 1), (2025, 2), (2025, 3), (2025, 4), (2025, 5),
    (2025, 6), (2025, 7), (2025, 8), (2025, 9),
    (2025, 10), (2025, 11), (2025, 12),
    (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5),
    (2026, 6), (2026, 7), (2026, 8), (2026, 9),
]
# Index of the first month of the OPEN water year, so "one missed read a year"
# and "the last two months are provisional" stay per-year statements rather than
# becoming per-record accidents.
OPEN_YEAR_FIRST_INDEX = 12

# The district's monitoring points, transcribed from MONITORING_WELLS in
# scripts/export_merced_native.py (the demo's own declaration, Phase 52.5). The
# NGVD29 row is deliberate: it exercises the legacy-datum path.
# reg -> (agency, frequency, reference elevation ft, datum, notes)
MONITORING_WELLS = {
    "MER-W-001": (
        "Halvern Irrigation District", "Monthly", "182.40", "NAVD88",
        "CASGEM voluntary monitoring point; manual sounder reading.",
    ),
    "MER-W-002": (
        "Halvern Valley GSA", "Quarterly", "176.10", "NAVD88",
        "Representative monitoring well for the GSA's spring/fall sweep.",
    ),
    "MER-W-004": (
        "DWR", "Continuous", "169.85", "NGVD29",
        "Legacy DWR record; transducer logs daily, datum not yet converted to NAVD88.",
    ),
}

# How often a declared frequency is actually read. The instrument cadence is
# derived from the well's OWN declaration rather than chosen here, so a future
# change cannot quietly smuggle a streaming cadence into a demo whose PROJECT.md
# puts real-time telemetry out of scope. "Continuous" means a logger downloaded
# on a schedule — one record a day, never sub-daily.
FREQUENCY_DAYS = {
    "Continuous": 1,
    "Daily": 1,
    "Monthly": 30,
    "Quarterly": 91,
}

# Depth-to-water shape for WY 2024-2025, as (day-of-water-year, feet below land
# surface) anchors on the DWR transducer well. October opens at the seasonal low
# after a summer of pumping; the water table recovers through the December-March
# recharge season this command's own basin readings instrument, then draws back
# down through the irrigation season. Linear between anchors, which is honest
# about being a shape rather than a model.
DEPTH_ANCHORS = [
    (0, 91.5),     # Oct 1 — seasonal low, end of the irrigation season
    (31, 90.2),    # Nov 1
    (61, 88.6),    # Dec 1
    (91, 85.1),    # Jan 1 — the December fills reach the water table
    (122, 80.4),   # Feb 1
    (153, 76.2),   # Mar 1
    (181, 73.8),   # Mar 29 — shallowest, after the last wet-season fill
    (212, 76.9),   # Apr 29 — irrigation season opens
    (242, 81.8),   # May 29
    (273, 86.4),   # Jun 29
    (303, 90.1),   # Jul 29
    (334, 93.0),   # Aug 29
    (364, 94.2),   # Sep 30 — a foot deeper than last October: the overdraft
]
# Each monitoring well sits at its own depth; the seasonal SHAPE is the
# subbasin's and is shared. Feet added to the anchors above, per well.
WELL_DEPTH_OFFSET = {
    "MER-W-001": Decimal("-6.4"),
    "MER-W-002": Decimal("3.7"),
    "MER-W-004": Decimal("0.0"),
}

# The annual calibration visit: the day the transducer was lifted out of the
# water and kept logging in air, and the day it spent re-equilibrating. Flagged
# anomalous with the cause named. The two days after it are reconstructed from
# the manual sounder either side, and carry quality "estimated". ANNUAL, so the
# second water year has its own (133-02) — one visit across two years would read
# as a district that stopped servicing its instrument.
SERVICE_VISITS = (datetime.date(2025, 5, 14), datetime.date(2026, 5, 14))
# The tail of the record that has not been through the district's annual review.
# It moves with the record's end, not with a literal date.
PROVISIONAL_FROM = datetime.date(2026, 8, 16)

# 133-02 — THE DRY YEAR'S WATER TABLE IS DERIVED FROM THIS DEMONSTRATION'S OWN
# NUMBERS, not drawn a second time. The wet year's anchors above are a shape and
# say so; a second hand-drawn shape would be a second unverifiable claim, and a
# flat continuation would be worse — a water table that does not move through a
# drought is the one thing this audience would never believe.
#
# So the second year reuses the first year's shape SEGMENT BY SEGMENT, scaled by
# the two quantities the rest of this milestone already measured:
#
#   * winter RECOVERY is scaled by 0.50, because managed recharge halved —
#     `RECHARGE_SEASONS` spreads 1.00x basin capacity in the wet year and 0.50x
#     in the dry one, and 133-01 halved the rainfall that drives it.
#   * summer DRAWDOWN is scaled by 1.187, because metered groundwater rose 18.7%
#     (2,558.6 AF -> 3,037.8 AF, measured on the built demo 2026-09-05).
#
# The second year opens exactly where the first closed, so the record is
# continuous across the boundary. Everything else about the shape — when the
# season turns, how fast — is inherited rather than invented.
DRY_RECOVERY_SCALE = Decimal("0.50")
DRY_DRAWDOWN_SCALE = Decimal("1.187")


def _derive_next_year_anchors(anchors, recovery_scale, drawdown_scale):
    """Anchors for a following year, continuing ``anchors`` segment by segment.

    Depth is FEET BELOW LAND SURFACE, so a falling value is the water table
    rising (recovery) and a rising value is drawdown. Each segment's change is
    scaled by whichever factor applies, and the year opens at the depth the
    previous one closed at.
    """
    depth = Decimal(str(anchors[-1][1]))
    out = [(anchors[0][0], float(depth))]
    for (_d0, v0), (d1, v1) in zip(anchors, anchors[1:]):
        delta = Decimal(str(v1)) - Decimal(str(v0))
        depth += delta * (drawdown_scale if delta > 0 else recovery_scale)
        out.append((d1, float(round(depth, 2))))
    return out


# The whole two-year record, in days from RECORD_START. The second year's day
# numbers are the first year's shifted by one water year, so the interpolation
# below needs no notion of which year it is in.
RECORD_ANCHORS = DEPTH_ANCHORS + [
    (day + DAYS_IN_FIRST_WY + 1, value)
    for day, value in _derive_next_year_anchors(
        DEPTH_ANCHORS, DRY_RECOVERY_SCALE, DRY_DRAWDOWN_SCALE
    )
]


def _q4(value):
    """Quantize to the 4 decimal places every measurement column carries."""
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _aware(d, hour, minute=0):
    """A timezone-aware field-visit timestamp. Fixed clock, never now()."""
    return timezone.make_aware(
        datetime.datetime(d.year, d.month, d.day, hour, minute)
    )


def _month_end(year, month):
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def _interp_depth(day):
    """Depth to water on day-of-water-year `day`, linear between the anchors."""
    if day <= RECORD_ANCHORS[0][0]:
        return RECORD_ANCHORS[0][1]
    for (d0, v0), (d1, v1) in zip(RECORD_ANCHORS, RECORD_ANCHORS[1:]):
        if d0 <= day <= d1:
            span = d1 - d0
            return v0 + (v1 - v0) * (day - d0) / span
    return RECORD_ANCHORS[-1][1]


class Command(BaseCommand):
    help = (
        "Seed the Merced demo's instrument record: recharge-basin monitoring, "
        "monitoring wells, meter reads, one transducer and its manual checks "
        "(idempotent; run after seed_merced_details)."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        # Local imports: `recharge`, `wells` and `measurements` are optional
        # modules, so a module-scope import raises app_label RuntimeError on a
        # demoted deployment (ISS-072, Phase 87).
        from measurements.models import (
            Meter, MeterReading, Sensor, SensorMeasurement, WaterMeasurement,
        )
        from recharge.models import RechargeMeasurement, RechargeSite
        from standards.models import ObservedProperty
        from wells.models import MonitoringWell, Well, WellIrrigatedParcel, WellMeter

        sites = list(
            RechargeSite.objects.filter(operator=DEMO_OPERATOR).order_by("name")
        )
        if not sites:
            self.stderr.write(self.style.ERROR(
                "No Merced recharge areas found — run "
                "seed_merced_basins_from_selection first."
            ))
            return

        # ── Self-flush: only this command's own rows. ────────────────────────
        # Scoped by the same keys used to write them, so an operator's real
        # entry on some other deployment is never in range.
        RechargeMeasurement.objects.filter(recharge_site__in=sites).delete()
        demo_meters = list(
            Meter.objects.filter(serial_number__startswith="MTR-MER-").order_by(
                "serial_number")
        )
        MeterReading.objects.filter(meter__in=demo_meters).delete()
        demo_sensors = Sensor.objects.filter(serial_number__startswith="HID-XD-")
        SensorMeasurement.objects.filter(sensor__in=demo_sensors).delete()
        demo_sensors.delete()
        WaterMeasurement.objects.filter(
            well__well_registration_id__in=list(MONITORING_WELLS)
        ).delete()

        extracted = self._require_property(ObservedProperty, "extracted_volume")
        gw_depth = self._require_property(
            ObservedProperty, "groundwater_level_depth")
        if extracted is None or gw_depth is None:
            # A null observed_property FK is precisely what the conformance audit
            # counts, so seeding readings without the vocabulary would write the
            # defect this phase exists to end. Refuse instead.
            return

        n_rm = self._seed_recharge_measurements(RechargeMeasurement, sites)
        n_mw = self._seed_monitoring_wells(MonitoringWell, Well)
        n_mr = self._seed_meter_readings(
            MeterReading, demo_meters, WellMeter, WellIrrigatedParcel, extracted
        )
        n_s, n_sm = self._seed_sensors(Sensor, SensorMeasurement, Well, gw_depth)
        n_wm = self._seed_water_measurements(
            WaterMeasurement, Well, MonitoringWell, gw_depth
        )

        self.stdout.write(self.style.SUCCESS(
            f"Merced measurement record seeded: {n_rm} basin reading(s) across "
            f"{len(sites)} site(s); {n_mw} monitoring well(s); {n_mr} totalizer "
            f"read(s) on {len(demo_meters)} meter(s); {n_s} sensor(s) with "
            f"{n_sm} logged reading(s); {n_wm} field measurement(s)."
        ))

    # ── 1. The one slice with a screen: recharge-basin monitoring ────────────
    def _seed_recharge_measurements(self, RechargeMeasurement, sites):
        """On-site readings across every wet-season fill, per basin, per year.

        Three readings a fill: ponded depth and canal inflow every time, then
        percolation OR source-water quality on alternating fills. The detail card
        renders the ten most recent; at this spacing those ten reach back across a
        season rather than sampling one storm.

        133-02: the dry year's two fills are instrumented the same way the wet
        year's four are. The district did not stop reading its basins because it
        rained less, and an event history for WY 2025-2026 sitting beside an
        empty measurements card is the exact contradiction 132-01 closed.

        The numbers have to agree with the event history printed beside them on
        the same page: a bigger basin taking a bigger fill ponds deeper and pulls
        more canal water. Percolation rate and source-water TDS are properties of
        the ground and of the storm, so those read nearly flat across the season
        and differ site to site instead.
        """
        capacities = [float(s.capacity_acre_feet or 0) for s in sites]
        cap_min, cap_max = min(capacities), max(capacities)
        cap_span = (cap_max - cap_min) or 1.0

        created = 0
        for site in sites:
            # Flood-MAR cropland is distinguished ONLY by the name suffix — all
            # seven sites carry site_type="spreading_basin", so branching on the
            # type would silently treat the orchards as engineered basins.
            flood_mar = site.name.endswith("(Flood-MAR)")
            size = (float(site.capacity_acre_feet or 0) - cap_min) / cap_span

            # Intrinsic to the site, not to the season: the soil's percolation
            # rate and the TDS of the water the canal is carrying.
            srng = random.Random(f"rmeas-site:{site.name}")
            # Coarse valley sands take water faster than the finer soils under
            # the cropland; both sit inside the 0.8-1.2 in/hr band the demo's
            # prior art uses.
            perc_base = (1.15 if not flood_mar else 0.86) - 0.10 * size
            perc_base += srng.uniform(-0.04, 0.04)
            tds_base = 296 + 34 * srng.random() - 12 * size

            season_fills = [
                pair for season in FILL_SEASONS.values() for pair in season
            ]
            for idx, (start, fraction) in enumerate(season_fills):
                # A 0.20 fill is a smaller storm than a 0.30 fill.
                fill = 0.80 if fraction == Decimal("0.20") else 1.00
                month = start.strftime("%B")
                rng = random.Random(f"rmeas:{site.name}:{start.isoformat()}")

                # Ponded depth, two days into the fill. Cropland is run thin on
                # purpose; a dedicated basin is built to hold water.
                if flood_mar:
                    depth = (0.92 + 0.45 * size) * fill
                    depth_note = (
                        f"Flooded depth across the orchard middles during the "
                        f"{month} fill. Cropland is run thin — held under about a "
                        f"foot so the trees are never standing in water."
                    )
                else:
                    depth = (2.60 + 1.30 * size) * fill
                    depth_note = (
                        f"Ponded depth at the staff gauge, two days into the "
                        f"{month} fill and the basin holding steady."
                    )
                created += self._add(
                    RechargeMeasurement, site, _aware(start + datetime.timedelta(days=2), 9),
                    "water_level", depth + rng.uniform(-0.08, 0.08), "ft", depth_note,
                )

                # Canal inflow, measured at the headgate on the first full day.
                cfs = (48.0 + 38.0 * size) * (0.82 if fill == 0.80 else 1.00)
                created += self._add(
                    RechargeMeasurement, site,
                    _aware(start + datetime.timedelta(days=1), 8),
                    "flow_rate", cfs + rng.uniform(-2.5, 2.5), "cfs",
                    (
                        f"Canal inflow at the headgate while the basin was filling "
                        f"on the {month} storm. Gates set wide; flow held through "
                        f"the fill."
                    ),
                )

                # Percolation, on every OTHER fill: once early, once after the
                # fines off the first storms have had time to settle out.
                # Expressed as a parity rather than the literal (0, 2) it used to
                # be, so a season of a different length (133-02's two-storm dry
                # winter) still gets a reading rather than falling through both
                # branches and recording nothing but depth and flow.
                if idx % 2 == 0:
                    silting = 0.0 if idx == 0 else -0.07
                    created += self._add(
                        RechargeMeasurement, site,
                        _aware(start + datetime.timedelta(days=4), 10),
                        "infiltration_rate",
                        perc_base + silting + rng.uniform(-0.03, 0.03), "in/hr",
                        (
                            "Percolation measured off the falling head after the "
                            "gates were shut."
                            if idx == 0 else
                            "Percolation re-checked late in the season. Down a "
                            "little on December — fines off the storm have started "
                            "to seal the floor, which is normal and comes back "
                            "with a summer disc."
                        ),
                    )

                # Source-water quality, on the alternate fills, from a grab
                # sample at the inlet. Storm runoff is the source, so it runs
                # fresh. Same parity reasoning as the percolation reading above.
                if idx % 2 == 1:
                    created += self._add(
                        RechargeMeasurement, site,
                        _aware(start + datetime.timedelta(days=3), 11),
                        "water_quality",
                        tds_base + rng.uniform(-9, 9), "mg/L",
                        (
                            f"Total dissolved solids on a grab sample taken at the "
                            f"inlet during the {month} fill. Storm runoff, so it "
                            f"comes in fresher than the groundwater it is going to."
                        ),
                    )
            per_site = 3 * len(season_fills)  # depth + flow every fill, then
            #                                     perc OR quality on each fill
            self.stdout.write(
                f"  {site.name}: {per_site} reading(s) across "
                f"{len(season_fills)} fills in {len(FILL_SEASONS)} water year(s)"
            )
        return created

    @staticmethod
    def _add(RechargeMeasurement, site, when, mtype, value, unit, notes):
        RechargeMeasurement.objects.create(
            recharge_site=site, measurement_date=when, measurement_type=mtype,
            value=_q4(round(value, 4)), unit=unit, notes=notes,
        )
        return 1

    # ── 2. The monitoring wells the instruments hang off ─────────────────────
    def _seed_monitoring_wells(self, MonitoringWell, Well):
        """The three ag wells that double as water-level monitoring points.

        Carried across from scripts/export_merced_native.py rather than invented:
        that file is the demonstration's own declaration of which wells are
        monitored, by whom, and how often, and it has been the only home for it.
        Everything downstream reads the cadence off these rows.
        """
        created = 0
        for reg, (agency, freq, elev, datum, notes) in MONITORING_WELLS.items():
            well = Well.objects.filter(well_registration_id=reg).first()
            if well is None:
                self.stderr.write(self.style.WARNING(
                    f"  {reg}: well not present — monitoring record skipped"
                ))
                continue
            MonitoringWell.objects.update_or_create(
                well=well,
                defaults={
                    "monitoring_agency": agency,
                    "measurement_frequency": freq,
                    "reference_elevation_ft": Decimal(elev),
                    "vertical_datum": datum,
                    "notes": notes,
                },
            )
            created += 1
        return created

    # ── 3a. The vocabulary row a totalizer needs ─────────────────────────────
    def _require_property(self, ObservedProperty, key):
        """Resolve a concept from the registry, or say plainly what is missing.

        The vocabulary is NOT written here. ``extracted_volume`` — the concept a
        totalizer actually reads, which the seventeen original concepts had no
        word for — was added to ``seed_observed_properties.OBSERVED_PROPERTIES``,
        because that command is the registry's one home and is what
        ``rebuild-golden.sh`` runs to produce the pinned count of 18. Writing the
        row here as well would give the same concept two authors and let them
        drift.
        """
        op = ObservedProperty.objects.filter(key=key).first()
        if op is None:
            self.stderr.write(self.style.ERROR(
                f"ObservedProperty '{key}' missing — run "
                f"seed_observed_properties first; measurements need it to name "
                f"what they measure."
            ))
        return op

    # ── 3b. Totalizer reads that agree with the ledger ───────────────────────
    def _seed_meter_readings(
        self, MeterReading, meters, WellMeter, WellIrrigatedParcel, extracted
    ):
        """Monthly reads on the 12 certified meters, reconciled to the ledger.

        133-02: across BOTH water years, 24 reads a meter. The delta is read off
        the ledger month by month, so the second year's reads reconcile to the
        second year's metered groundwater the same way the first year's do — that
        reconciliation is the whole tie between this instrument record and the
        accounting spine, and letting it stop at 2025-09-30 would leave 24 months
        of pumping described by 12 months of meter reads with nothing on the page
        saying which year was which.

        A domain expert reading a well's meter against its parcel's metered
        groundwater WILL compare the two, and disagreement is a worse defect than
        emptiness. So the monthly delta is not invented: it is read straight off
        the ``ParcelLedger`` rows of source type ``meter_reading`` for the
        parcels that well irrigates, summed for the month. Where a well serves
        several parcels (MER-W-019 serves four), the well's total is the sum of
        its parcels' rows, which is the same demand-weighted split
        ``seed_merced_ledgers`` already applied when it wrote them.

        The totalizer itself runs the way a totalizer runs: monotonically
        increasing, never reset, ``calculated_volume`` exactly the difference.
        Its opening value is the well's lifetime accumulation, deterministic on
        the meter serial.

        ⛔ ``read_by`` stays NULL. See the module docstring.
        """
        from parcels.models import ParcelLedger
        from django.db.models import Sum

        created = 0
        for meter in meters:
            link = WellMeter.objects.filter(meter=meter).select_related("well").first()
            if link is None:
                continue
            well = link.well
            parcel_ids = list(
                WellIrrigatedParcel.objects.filter(well=well).values_list(
                    "parcel_id", flat=True)
            )
            rng = random.Random(f"totalizer:{meter.serial_number}")
            # Lifetime accumulation before this water year opened — a well
            # pumping a few hundred acre-feet a year since the 1990s.
            running = _q4(Decimal(rng.randrange(80_000, 420_000)) / Decimal("10"))
            # One meter in four had a read missed somewhere in each water year.
            # Drawn PER YEAR (133-02) rather than once across the whole record, so
            # adding a second year does not silently halve the miss rate — and so
            # the committed year's draw is the one it always was.
            estimated_months = set()
            for year_start in (0, OPEN_YEAR_FIRST_INDEX):
                if rng.random() < 0.30:
                    estimated_months.add(year_start + rng.randrange(0, 12))

            for m_idx, (year, month) in enumerate(WY_MONTHS):
                first = datetime.date(year, month, 1)
                last = _month_end(year, month)
                delta = ParcelLedger.objects.filter(
                    parcel_id__in=parcel_ids,
                    source_type="meter_reading",
                    effective_date__gte=first,
                    effective_date__lte=last,
                ).aggregate(total=Sum("amount_acre_feet"))["total"] or Decimal("0")
                # Ledger extraction rows are negative (water leaving the parcel);
                # a totalizer counts what came out, so take the magnitude.
                delta = _q4(abs(delta))
                previous = running
                running = _q4(previous + delta)

                month_name = last.strftime("%B %Y")
                if m_idx in estimated_months:
                    quality = "estimated"
                    notes = (
                        f"Totalizer read for {month_name}. Read missed on the "
                        f"scheduled visit — the gate was locked and the well was "
                        f"down — so the month is estimated from the following "
                        f"read and the field's irrigation schedule."
                    )
                elif m_idx >= len(WY_MONTHS) - 2:
                    # The last two months of the OPEN year have not been through
                    # the district's annual review yet (133-02). WY 2024-2025 is
                    # `is_finalized=True`, so its September read is no longer
                    # provisional once a second year has passed — leaving it that
                    # way would have a finalized year still awaiting review.
                    quality = "provisional"
                    notes = (
                        f"Totalizer read for {month_name}. Provisional until the "
                        f"district's end-of-year review closes the water year."
                    )
                elif delta == 0:
                    quality = "approved"
                    notes = (
                        f"Totalizer read for {month_name}. No change on the face — "
                        f"the pump did not run this month."
                    )
                else:
                    quality = "approved"
                    notes = f"Totalizer read for {month_name}, taken at the wellhead."

                MeterReading.objects.create(
                    meter=meter,
                    observed_property=extracted,
                    reading_date=_aware(last, 14),
                    previous_value=previous,
                    current_value=running,
                    calculated_volume=delta,
                    quality=quality,
                    read_by=None,   # ⛔ gate 2 requires core.User = 0
                    notes=notes,
                )
                created += 1
        return created

    # ── 4. The one logger the demo declares, downloaded daily ────────────────
    def _seed_sensors(self, Sensor, SensorMeasurement, Well, gw_depth):
        """A pressure transducer on the well whose own record says it has one.

        A sensor goes ONLY on a monitoring well that declares a continuous
        cadence. MER-W-001's declaration reads "manual sounder reading" and
        MER-W-002's reads "spring/fall sweep" — installing a transducer on either
        would contradict the demonstration's own note about it, so those two get
        the hand-entered record in the next step and no instrument here.

        The cadence is DAILY and comes from FREQUENCY_DAYS[declared frequency],
        not from a constant chosen here. PROJECT.md puts real-time telemetry out
        of scope, so nothing in this record may imply a webhook, a stream, or a
        sub-daily poll: this is a logger someone downloads.
        """
        sensors = 0
        readings = 0
        for reg, (agency, freq, elev, datum, _note) in MONITORING_WELLS.items():
            if FREQUENCY_DAYS.get(freq) != 1:
                continue
            well = Well.objects.filter(well_registration_id=reg).first()
            if well is None:
                continue
            rng = random.Random(f"sensor:{reg}")
            sensor = Sensor.objects.create(
                name=f"{reg} water-level transducer",
                sensor_type="pressure_transducer",
                serial_number=f"HID-XD-{rng.randrange(10000, 99999)}",
                model="In-Situ Level TROLL 500",
                well=well,
                location=well.location,
                status="active",
                # Anomalous records below are flagged with their cause; excluding
                # them from downstream calculation is the point of flagging them.
                exclude_anomalies=True,
                notes=(
                    f"Vented pressure transducer set below the seasonal low. Logs "
                    f"once a day; the record is downloaded on the {agency} field "
                    f"round, not telemetered. Reference elevation {elev} ft "
                    f"{datum}."
                ),
            )
            sensors += 1
            readings += self._log_daily(
                SensorMeasurement, sensor, reg, gw_depth
            )
        return sensors, readings

    def _log_daily(self, SensorMeasurement, sensor, reg, gw_depth):
        offset = WELL_DEPTH_OFFSET.get(reg, Decimal("0"))
        rows = []
        day = RECORD_START
        idx = 0
        while day <= RECORD_END:
            rng = random.Random(f"sm:{reg}:{day.isoformat()}")
            depth = Decimal(str(round(_interp_depth(idx), 4))) + offset
            depth += Decimal(str(round(rng.uniform(-0.12, 0.12), 4)))
            anomalous = False
            quality = "approved"
            notes = ""

            service_gap = min(((day - v).days for v in SERVICE_VISITS
                               if (day - v).days >= 0), default=-1)
            if service_gap == 0:
                anomalous = True
                depth = Decimal("2.1400")
                notes = (
                    "Transducer lifted out of the water for the annual "
                    "calibration check and left logging in air. The value is the "
                    "instrument, not the aquifer."
                )
            elif service_gap == 1:
                anomalous = True
                depth = depth - Decimal("3.6")
                notes = (
                    "First full day back down the casing; still equilibrating "
                    "after the calibration visit."
                )
            elif service_gap in (2, 3):
                quality = "estimated"
                notes = (
                    "Reconstructed from the manual sounder readings either side "
                    "of the calibration visit."
                )
            elif day >= PROVISIONAL_FROM:
                # The tail of the record has not been reviewed yet.
                quality = "provisional"

            rows.append(SensorMeasurement(
                sensor=sensor,
                observed_property=gw_depth,
                measurement_date=_aware(day, 6),
                value=_q4(depth),
                unit="ft",
                quality=quality,
                is_anomalous=anomalous,
                notes=notes,
            ))
            day += datetime.timedelta(days=1)
            idx += 1
        SensorMeasurement.objects.bulk_create(rows)
        return len(rows)

    # ── 5. The hand-entered counterpart ──────────────────────────────────────
    def _seed_water_measurements(self, WaterMeasurement, Well, MonitoringWell, gw_depth):
        """Manual sounder readings at the cadence each well declares.

        This is the operator's own field record, and on the transducer well it is
        the check ON the instrument: the same day, a few hundredths off. That
        small disagreement is the realistic part — a steel tape and a pressure
        transducer never agree exactly — and it is exactly what a ``quality``
        flag exists to carry.

        ⛔ ``recorded_by`` stays NULL. See the module docstring.
        """
        created = 0
        for reg, (agency, freq, elev, datum, _note) in MONITORING_WELLS.items():
            well = Well.objects.filter(well_registration_id=reg).first()
            if well is None:
                continue
            mw = MonitoringWell.objects.filter(well=well).first()
            declared = mw.measurement_frequency if mw else freq
            step = FREQUENCY_DAYS.get(declared, 30)
            has_logger = step == 1
            # A logger well still gets a hand check, but quarterly, not daily —
            # the point of the visit is to verify the instrument, not to replace
            # it. A well with no logger is read at the cadence it declares.
            visit_step = 91 if has_logger else step

            offset = WELL_DEPTH_OFFSET.get(reg, Decimal("0"))
            day = RECORD_START + datetime.timedelta(days=14)
            idx = (day - RECORD_START).days
            while day <= RECORD_END:
                rng = random.Random(f"wm:{reg}:{day.isoformat()}")
                depth = Decimal(str(round(_interp_depth(idx), 4))) + offset
                if has_logger:
                    # Shadow the logger for the same date, a few hundredths off.
                    depth += Decimal(str(round(rng.uniform(-0.12, 0.12), 4)))
                    depth += Decimal(str(round(rng.uniform(-0.09, 0.09), 4)))
                    notes = (
                        f"Steel-tape check against the transducer on the {agency} "
                        f"field round. Reads a few hundredths off the logger, "
                        f"which is the tape and the instrument disagreeing the "
                        f"way they always do."
                    )
                else:
                    depth += Decimal(str(round(rng.uniform(-0.18, 0.18), 4)))
                    notes = (
                        f"{declared} sounder reading, measured down from the "
                        f"casing top and referenced to {elev} ft {datum}."
                    )
                WaterMeasurement.objects.create(
                    name=f"{reg} depth to water",
                    measurement_type="groundwater_level",
                    observed_property=gw_depth,
                    value=_q4(depth),
                    unit="ft",
                    measurement_date=_aware(day, 10),
                    parcel=None,
                    well=well,
                    source="manual",
                    recorded_by=None,   # ⛔ gate 2 requires core.User = 0
                    notes=notes,
                )
                created += 1
                day += datetime.timedelta(days=visit_step)
                idx += visit_step
        return created
