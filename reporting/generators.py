# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Report generators for GEARS CSV and CalWATRS CSV.

Unit conventions used throughout:
  - Volumes: acre-feet (AF). 1 AF = 1,233.48 m³ = 325,851 US gallons.
  - Flow rates: CFS (cubic feet per second). 1 CFS × 1 day = 1.9835 AF.
    CFS to AF/day: 1 CFS × 86,400 s/day × 0.0283168 m³/ft³ / 1,233.48 m³/AF = 1.9835
  - Well capacity: GPM (gallons per minute). 1 GPM = 0.002228 CFS = 0.004419 AF/day.
  - ET depths: mm (from OpenET). Converted to AF by accounting.services.et_mm_to_acre_feet().
    Formula: ET (AF) = ET (mm) × area (acres) / 304.8
  - Areas: acres. 1 acre = 43,560 ft² = 4,046.86 m².
Reference: USGS Water Science School; California Department of Water Resources unit conversion tables.
"""

from __future__ import annotations

import csv
import io
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import Sum

from accounting.allocation_math import apportion_shared_supply
from accounting.ledger_words import DEMONSTRATION_FILE_LINE
from accounting.models import CalculationRun, ReportingPeriod
from accounting.services import runs_in_period
from core.csv_safe import safe_row
from core.models import SiteConfig
from core.modules import is_enabled
from parcels.models import Parcel, ParcelLedger
from wells.models import WellIrrigatedParcel


# Soft divergence flag: a parcel whose stored weight and ET-implied
# weight differ by this much (absolute weight, i.e. 15 percentage points) is
# worth a second look — a likely data-entry tell. Display-only; nothing is
# auto-corrected.
SHARED_SUPPLY_DIVERGENCE_THRESHOLD = Decimal("0.15")

# The quantum a shared-supply weight is rounded to once it is
# read as a percent (0.1196 -> 11.96) rather than a four-place fraction.
_PCT_PLACES = Decimal("0.01")


# GEARS "Extraction volume measurement method" controlled vocabulary.
# The GEARS portal prints this field as a fixed label, not our internal code.
# Source: a SWRCB Groundwater Extraction Report with Report Status "Accepted"
# (Extractor 25226 / Well 6895, Water Year 2018) prints the value
# "Unmetered/Estimated"; the same report's fee schedule splits the field into
# metered vs unmetered. We crosswalk our ParcelLedger.source_type codes onto the
# two state-facing labels here rather than leaking the internal code into the
# filing. (UCUM is deliberately NOT used — it targets the v1.3 open-data
# exports, not these state CSVs.)
GEARS_METHOD = {
    "meter_reading": "Metered",
    "et_estimate": "Unmetered/Estimated",
    "calculated": "Unmetered/Estimated",
}


#: The GEARS files' columns: the by-well file and the by-ET file both write one line per well.
GEARS_WELL_HEADER = [
    "Well Registration ID", "Well Name", "Latitude", "Longitude",
    "Month", "Extraction Volume (AF)", "Measurement Method",
]


def gears_method(source_type):
    """Crosswalk an internal source_type to the GEARS measurement-method label.

    An unknown code passes through unchanged so a newly-added source_type is
    visible in the file (and catchable by validate_report) rather than being
    silently relabeled to a wrong state value.

    GEARS is a groundwater filing built from ``ParcelLedger`` rows and the recorded
    crop ET (see ``generate_gears_csv`` below) -- it never reads a
    ``surface.DiversionRecord``, so the label comes from the source type alone (a
    recorded crop ET line carries ``et_estimate``).
    """
    return GEARS_METHOD.get(source_type, source_type)


def calwatrs_method_label(record):
    """The state's own words for how a ``DiversionRecord``'s number is known.

    Prefers the record's own ``method`` -- and the device's type when the
    method is ``device`` -- over any other inference: this platform asked
    the operator directly, so a guess never overrides what was stated.
    A record with no method recorded reports "Not stated" rather than
    inventing one. No CalWATRS row was ever built from a DiversionRecord's
    method before this (there was no Measurement Method column on this
    worksheet); there is nothing here to "fall back" to. The value below is
    what WOULD populate the CalWATRS worksheet's own field if a filing path
    existed -- it does not ("prepared, never filed", docs/DATA-STANDARDS.md).
    """
    if not record.method:
        return "Not stated"
    label = record.get_method_display()
    if record.method == "device" and record.device_id:
        label = f"{label}: {record.device.get_device_type_display()}"
    return label


def _period_demand_by_parcel(reporting_period):
    """Return ``{parcel_id: net_consumptive_use_af}`` summed over a period's runs.

    The per-parcel ET demand signal that the apportionment kernel weights a shared
    source against (rung 3). One grouped query — a Sum annotation over the period's
    ``CalculationRun`` rows, NOT a per-parcel loop (Architecture Gate: no N+1). A
    parcel with no run is simply absent from the map; callers treat that as demand
    0. ``reporting_period is None`` returns an empty map, so every parcel reads as
    demand 0 — that is what makes a no-period call reproduce today's static split.

    Period selection goes through ``accounting.services.runs_in_period`` — the
    one canonical selector (math eval item 6) — so the filed number and the
    on-screen balance can never disagree about which months belong to a period.
    See that function for the whole-month membership rule.
    """
    if reporting_period is None:
        return {}
    rows = (
        runs_in_period(CalculationRun.objects.all(), reporting_period)
        .values("parcel_id")
        .annotate(demand=Sum("net_consumptive_use_af"))
    )
    return {r["parcel_id"]: (r["demand"] or Decimal("0")) for r in rows}


def build_normalized_well_parcel_map(reporting_period=None):
    """Return ``{parcel_id: [(well, weight), ...]}`` split by the 56 kernel.

    WellIrrigatedParcel.fraction defaults to 1.0 (correct for single-well parcels).
    Without apportionment, a well irrigating N parcels all at fraction=1.0 would
    have its volume multiplied by N — a double-counting bug. Each well's parcels
    are split through ``apportion_shared_supply`` (the measurement-first ladder),
    so the weights always sum to exactly 1.0 across the parcels it irrigates:

      - a district's hand-set fractions win (rung 2);
      - absent any hand-set fraction, the volume follows estimated ET demand for the
        ``reporting_period`` — the thirsty crop gets the larger share (rung 3);
      - absent ET demand (or no period passed), an even 1/N split (rung 4).

    Passing no ``reporting_period`` gives every parcel demand 0, so the kernel
    falls through to fractions/even — i.e. exactly today's static behavior.

    This is the single source of truth for the well↔parcel allocation: both the
    GEARS by-well CSV (generate_gears_csv) and the OpenET pre-fill
    (reporting.services.build_openet_prefill) call it, so they can never drift
    apart on how a multi-parcel well's volume is split.
    """
    demand_by_parcel = _period_demand_by_parcel(reporting_period)

    wips_by_well = {}  # well_id → [wip]
    for wip in WellIrrigatedParcel.objects.select_related("well").all():
        wips_by_well.setdefault(wip.well_id, []).append(wip)

    well_parcel_map = {}  # parcel_id → [(well, weight)]
    for well_id, wips in wips_by_well.items():
        # Key the kernel by the link's pk (unique) so two links can never collide;
        # re-key to parcel_id on the way out to preserve the caller's shape.
        members = [
            (wip.pk, wip.fraction, demand_by_parcel.get(wip.parcel_id, Decimal("0")))
            for wip in wips
        ]
        weights = apportion_shared_supply(members)
        wip_by_pk = {wip.pk: wip for wip in wips}
        for wip_pk, weight in weights.items():
            wip = wip_by_pk[wip_pk]
            well_parcel_map.setdefault(wip.parcel_id, []).append((wip.well, weight))
    return well_parcel_map


class PodSplit:
    """Each point of diversion's split among its use areas, month by month, as the ledger divided it.

    The CalWATRS file and the Prepare with OpenET page divide a point's water in a
    month the way the ledger divided it, so the file's rows agree with the use area pages. ``for_month`` returns
    ``[(parcel_id, weight), ...]`` with 4dp weights summing to exactly 1.0000:

    * a use area's part is what the ledger put on it from this point that month:
      the rows the point divided (``divided_from_headgate``) plus this point's part
      of the use area's own recorded delivery (``own_parts_for_point``, the same
      pro-rata rule the division uses), normalized by the kernel's residual rule;
    * a point-month with nothing on the ledger (not yet calculated, water only to
      storage, every use area fallow) takes the ledger's own rule, the shares
      entered, else acreage (``shares_else_acreage``, the helper the division
      calls).

    Crop ET never feeds the split directly; it reaches the file only through a
    point the district set to divide by crop ET, as the ledger divided it. A use
    area the ledger left out of a month (fallow, or every bit of its water its own
    record at another point) has no row that month.
    """

    def __init__(self, by_month: dict[tuple[int, str], list[tuple[int, Decimal]]],
                 fallback: dict[int, list[tuple[int, Decimal]]]):
        self.by_month = by_month
        self.fallback = fallback

    def pod_ids(self):
        """Every point with a use area linked to it, or with water on the ledger."""
        return set(self.fallback) | {pod_id for pod_id, _ in self.by_month}

    def for_month(self, pod_id: int, month: str) -> list[tuple[int, Decimal]]:
        """``[(parcel_id, weight), ...]`` for one point and ``"YYYY-MM"`` month; empty for a point serving no one."""
        return self.by_month.get((pod_id, month)) or self.fallback.get(pod_id, [])


def _month_of(day) -> str:
    return day.strftime("%Y-%m")


def build_pod_split_by_month(reporting_period) -> PodSplit:
    """The ledger's split of each point's water for every month of ``reporting_period``.

    Four queries whatever the size of the site (the links, the divided rows, the
    use areas' own deliveries, the diversion records); no query per point or month.
    """
    # Local import: `surface` is an optional module, so this must not
    # run at module scope: importing surface.models with the app uninstalled
    # raises RuntimeError before any useful error prints.
    from surface.models import DiversionRecord, PointOfDiversionParcel
    from surface.services import own_parts_for_point, shares_else_acreage

    links_by_pod: dict[int, list] = {}
    serving: dict[int, set[int]] = {}
    for link in PointOfDiversionParcel.objects.select_related("parcel").order_by("id"):
        links_by_pod.setdefault(link.point_of_diversion_id, []).append(link)
        serving.setdefault(link.parcel_id, set()).add(link.point_of_diversion_id)
    fallback = {
        pod_id: list(shares_else_acreage(links).items())
        for pod_id, links in links_by_pod.items()
    }

    start, end = reporting_period.start_date, reporting_period.end_date
    surface_rows = ParcelLedger.objects.current().filter(
        source_type="surface_diversion",
        effective_date__gte=start,
        effective_date__lte=end,
    )

    # What the ledger put on each use area from each point, by month.
    magnitudes: dict[tuple[int, str], dict[int, Decimal]] = {}
    for pod_id, parcel_id, day, amount in surface_rows.filter(
        divided_from_headgate=True, divided_from_point_pk__isnull=False
    ).values_list("divided_from_point_pk", "parcel_id", "effective_date", "amount_acre_feet"):
        slot = magnitudes.setdefault((pod_id, _month_of(day)), {})
        slot[parcel_id] = slot.get(parcel_id, Decimal("0")) - amount

    # Each use area's own recorded delivery by month, and each point's recorded
    # consumed total by month: the division counts a served use area's own
    # delivery in a month its point has direct-use water (``_allocate_month``).
    own_sums: dict[str, dict[int, Decimal]] = {}
    for parcel_id, day, amount in surface_rows.filter(
        divided_from_headgate=False, parcel_id__in=list(serving)
    ).values_list("parcel_id", "effective_date", "amount_acre_feet"):
        slot = own_sums.setdefault(_month_of(day), {})
        slot[parcel_id] = slot.get(parcel_id, Decimal("0")) + amount
    if own_sums:
        recorded: dict[str, dict[int, Decimal]] = {}
        for record in DiversionRecord.objects.current().filter(
            diversion_type="direct_use", month__gte=start, month__lte=end
        ):
            slot = recorded.setdefault(_month_of(record.month), {})
            slot[record.point_of_diversion_id] = (
                slot.get(record.point_of_diversion_id, Decimal("0"))
                + record.consumed_acre_feet()
            )
        for month, sums in own_sums.items():
            own = {pk: abs(total) for pk, total in sums.items()}
            for pod_id in recorded.get(month, {}):
                served_here = {pk: af for pk, af in own.items() if pod_id in serving.get(pk, ())}
                parts = own_parts_for_point(pod_id, served_here, serving, recorded[month])
                slot = magnitudes.setdefault((pod_id, month), {})
                for parcel_id, af in parts.items():
                    slot[parcel_id] = slot.get(parcel_id, Decimal("0")) + af

    by_month = {}
    for key, parts in magnitudes.items():
        members = [(pk, Decimal("1.0"), af) for pk, af in sorted(parts.items()) if af > 0]
        if members:
            weights = apportion_shared_supply(members)
            by_month[key] = [(pk, w) for pk, w in weights.items() if w > 0]
    return PodSplit(by_month, fallback)


def _compare_split(links, demand_by_parcel, parcel_names):
    """Build one shared source's stored-vs-ET-implied comparison rows.

    ``links`` is ``[(parcel_id, stored_fraction), ...]`` for the parcels one
    shared source serves. Returns ``{"has_et_signal", "rows", "any_flag"}``.

    * ``your_weight`` — ``apportion_shared_supply`` with the STORED fractions
      (rung 2, the human split).
    * ``et_weight``  — the same call with every fraction forced to the
      ``Decimal("1.0")`` sentinel, which drops to rung 3 (pure ET demand). When
      the source's parcels have zero total measured demand it is undefined
      (``None`` → "no ET signal"), NOT a misleading even split, and the flag is
      suppressed.
    * ``your_pct`` / ``et_pct`` / ``gap_points`` -- the same three
      weights read as a percent of the source's water (0.1196 -> 11.96) rather
      than a fraction, each quantized to ``Decimal("0.01")`` with
      ``ROUND_HALF_UP``. The conversion loses no information because a weight's third
      and fourth decimal places become the percent's two. ``None`` where the
      underlying weight is ``None``. These are ADDED keys; ``your_weight``/``et_weight``/``divergence`` and the flag rule are
      unchanged, and every existing key stays for the apportionment and
      presentation tests that assert them by name.
    """
    your_split = apportion_shared_supply(
        [(pid, frac, demand_by_parcel.get(pid, Decimal("0"))) for pid, frac in links]
    )
    total_demand = sum(
        (demand_by_parcel.get(pid, Decimal("0")) for pid, _ in links), Decimal("0")
    )
    has_et = total_demand > 0
    et_split = (
        apportion_shared_supply(
            [(pid, Decimal("1.0"), demand_by_parcel.get(pid, Decimal("0"))) for pid, _ in links]
        )
        if has_et
        else {}
    )

    rows = []
    any_flag = False
    for pid, _ in links:
        your_w = your_split.get(pid, Decimal("0"))
        if has_et:
            et_w = et_split.get(pid, Decimal("0"))
            divergence = abs(your_w - et_w)
            flag = divergence >= SHARED_SUPPLY_DIVERGENCE_THRESHOLD
        else:
            et_w = None
            divergence = None
            flag = False
        any_flag = any_flag or flag
        rows.append(
            {
                "parcel_id": pid,
                "parcel_number": parcel_names.get(pid, str(pid)),
                "your_weight": your_w,
                "et_weight": et_w,
                "divergence": divergence,
                "flag": flag,
                "your_pct": (your_w * 100).quantize(_PCT_PLACES, rounding=ROUND_HALF_UP),
                "et_pct": (
                    (et_w * 100).quantize(_PCT_PLACES, rounding=ROUND_HALF_UP)
                    if et_w is not None
                    else None
                ),
                "gap_points": (
                    (divergence * 100).quantize(_PCT_PLACES, rounding=ROUND_HALF_UP)
                    if divergence is not None
                    else None
                ),
            }
        )
    return {"has_et_signal": has_et, "rows": rows, "any_flag": any_flag}


def build_shared_supply_comparison(reporting_period=None):
    """Stored split vs. ET-implied split for each hand-set shared source.

    A *shared source* is a well or point of diversion serving more than one
    parcel. A source is *hand-set* when a district nudged any member's link
    ``fraction`` off the ``Decimal("1.0")`` sentinel — rung 2 of
    ``apportion_shared_supply``, where the human split wins over ET demand.

    For every hand-set shared source this surfaces a two-column reasonableness
    check — the stored split a human entered beside the split estimated ET demand
    would imply — with a soft per-parcel flag where the two diverge by >= 15
    points. **Display only**: a hand-set share is never auto-overwritten.

    A pure demand-split (all fractions untouched) is excluded — its two columns
    are identical by construction, so there is nothing to compare. Single-parcel
    sources are excluded — there is no split.

    Returns a list of group dicts ordered by source name::

        {"kind": "Well" | "Point of diversion", "source_name": str,
         "source_id": int, "source_kind": "well" | "pod",
         "has_et_signal": bool, "any_flag": bool,
         "rows": [{"parcel_number", "your_weight", "et_weight" (Decimal|None),
                   "divergence" (Decimal|None), "flag": bool}, ...]}
    """
    demand_by_parcel = _period_demand_by_parcel(reporting_period)

    # Gather candidate hand-set shared sources from both link tables.
    # source_id + source_kind carry the well/POD pk and a discriminator so the
    # template can link a flagged group to the page where the split is edited.
    candidates = []  # (kind, source_name, source_id, source_kind, [(parcel_id, fraction), ...])

    wips_by_well = {}
    for wip in WellIrrigatedParcel.objects.select_related("well").all():
        wips_by_well.setdefault(wip.well, []).append(wip)
    for well, wips in wips_by_well.items():
        if len(wips) < 2:
            continue
        if not any(wip.fraction != Decimal("1.0") for wip in wips):
            continue  # untouched fractions → not hand-set, nothing to compare
        candidates.append(
            ("Well", well.name, well.pk, "well",
             [(wip.parcel_id, wip.fraction) for wip in wips])
        )

    # Guarded as well as locally imported: the shared-supply check is a
    # `reporting` page, which stays enabled, so this half would otherwise run
    # unconditionally. With `surface` dropped the comparison is well-only, and the
    # template's POD link branch is guarded on the same condition.
    if is_enabled("surface"):
        from surface.models import PointOfDiversionParcel

        podps_by_pod = {}
        for podp in PointOfDiversionParcel.objects.select_related("point_of_diversion").all():
            podps_by_pod.setdefault(podp.point_of_diversion, []).append(podp)
        for pod, podps in podps_by_pod.items():
            if len(podps) < 2:
                continue
            if not any(podp.fraction != Decimal("1.0") for podp in podps):
                continue
            candidates.append(
                (
                    "Point of diversion",
                    pod.name,
                    pod.pk,
                    "pod",
                    [(podp.parcel_id, podp.fraction) for podp in podps],
                )
            )

    # One query for every parcel number we will display (no N+1).
    parcel_ids = {pid for *_, links in candidates for pid, _ in links}
    parcel_names = dict(
        Parcel.objects.filter(id__in=parcel_ids).values_list("id", "parcel_number")
    )

    groups = []
    for kind, source_name, source_id, source_kind, links in candidates:
        comparison = _compare_split(links, demand_by_parcel, parcel_names)
        groups.append(
            {
                "kind": kind,
                "source_name": source_name,
                "source_id": source_id,
                "source_kind": source_kind,
                "has_et_signal": comparison["has_et_signal"],
                "any_flag": comparison["any_flag"],
                "rows": comparison["rows"],
            }
        )
    groups.sort(key=lambda g: (g["kind"], g["source_name"]))
    return groups


def _well_reading_volumes(reporting_period: ReportingPeriod) -> dict[tuple[int, str], Decimal]:
    """``{(well id, "YYYY-MM"): acre-feet}`` the wells' own meters read in the period.

    The readings are entered once, on the well, and counted the way the
    calculation counts them (``_reading_acre_feet``). A reading on a meter no
    well carries is not in the result.
    """
    import datetime as dt

    from django.utils import timezone

    from accounting.management.commands.run_calculations import _reading_acre_feet
    from measurements.models import MeterReading
    from wells.models import WellMeter

    start = timezone.make_aware(dt.datetime.combine(reporting_period.start_date, dt.time.min))
    end = timezone.make_aware(
        dt.datetime.combine(reporting_period.end_date + dt.timedelta(days=1), dt.time.min)
    )
    by_meter: dict[tuple[int, str], Decimal] = {}
    for reading in MeterReading.objects.current().filter(
        reading_date__gte=start, reading_date__lt=end
    ).select_related("meter"):
        volume = _reading_acre_feet(reading)
        if volume is None:
            continue
        key = (reading.meter_id, timezone.localtime(reading.reading_date).strftime("%Y-%m"))
        by_meter[key] = by_meter.get(key, Decimal("0")) + volume

    meter_ids = {meter_id for meter_id, _ in by_meter}
    out: dict[tuple[int, str], Decimal] = {}
    for link in WellMeter.objects.filter(meter_id__in=meter_ids):
        for (meter_id, month_str), volume in by_meter.items():
            if meter_id == link.meter_id:
                key = (link.well_id, month_str)
                out[key] = out.get(key, Decimal("0")) + volume
    return out


def _gears_by_well_build(
    reporting_period: ReportingPeriod,
) -> tuple[list[dict[str, Any]], set[tuple[int, str]]]:
    """The by-well rows, and the (field id, month) pairs those rows hold.

    A well's volume for a month is what its own meter read, once. A reading
    typed on a field is that field's water and is written once under the field's
    well (the well with the largest share of the field, the lowest id on a tie).
    A well with a typed field reading in the month takes the typed readings and
    not its own meter's, the same choice the calculation makes.
    """
    from accounting.management.commands.run_calculations import WELL_METER_SHARE_WORDS

    entries = (
        ParcelLedger.objects.current().filter(
            source_type="meter_reading",
            effective_date__gte=reporting_period.start_date,
            effective_date__lte=reporting_period.end_date,
        )
        .exclude(description__startswith=WELL_METER_SHARE_WORDS)
        .select_related("parcel")
    )

    links_by_parcel: dict[int, list[WellIrrigatedParcel]] = {}
    links_by_well: dict[int, list[WellIrrigatedParcel]] = {}
    for link in WellIrrigatedParcel.objects.select_related("well").order_by("pk"):
        links_by_parcel.setdefault(link.parcel_id, []).append(link)
        links_by_well.setdefault(link.well_id, []).append(link)

    def new_row(well, month_str):
        return {
            "reg_id": well.well_registration_id or "",
            "name": str(well),
            "lat": well.location.y,
            "lon": well.location.x,
            "month": month_str,
            "volume": Decimal("0"),
            "method": "meter_reading",
            "well_id": well.pk,
        }

    rows: dict[tuple[Any, str], dict[str, Any]] = {}
    held: set[tuple[int, str]] = set()
    typed_wells: set[tuple[int, str]] = set()
    for entry in entries:
        month_str = entry.effective_date.strftime("%Y-%m")
        held.add((entry.parcel_id, month_str))
        links = links_by_parcel.get(entry.parcel_id, [])
        if links:
            for link in links:
                typed_wells.add((link.well_id, month_str))
            home = max(links, key=lambda k: (k.fraction, -k.pk)).well
            key = (home.pk, month_str)
            if key not in rows:
                rows[key] = new_row(home, month_str)
            rows[key]["volume"] += abs(entry.amount_acre_feet)
        else:
            # Metered extraction on a parcel with no well link. Never
            # silently drop it: emit a parcel-keyed [INCOMPLETE] row so the
            # volume stays visible and flagged (mirrors the [INCOMPLETE] holder
            # convention on the CalWATRS side). validate_report warns so the
            # operator links the parcel to its well before filing.
            key = (f"parcel:{entry.parcel_id}", month_str)
            if key not in rows:
                rows[key] = {
                    "reg_id": "",
                    "name": (
                        f"[INCOMPLETE] [No well link] "
                        f"Parcel {entry.parcel.parcel_number}"
                    ),
                    "lat": "",
                    "lon": "",
                    "month": month_str,
                    "volume": Decimal("0"),
                    "method": "meter_reading",
                    "well_id": None,
                }
            rows[key]["volume"] += abs(entry.amount_acre_feet)

    well_volumes = _well_reading_volumes(reporting_period)
    if well_volumes:
        wells = {
            link.well_id: link.well
            for links in links_by_well.values()
            for link in links
        }
        from wells.models import Well

        wells.update(Well.objects.in_bulk({w for w, _ in well_volumes} - set(wells)))
        for (well_id, month_str), volume in well_volumes.items():
            if (well_id, month_str) in typed_wells:
                continue
            key = (well_id, month_str)
            if key not in rows:
                rows[key] = new_row(wells[well_id], month_str)
            rows[key]["volume"] += volume
            for link in links_by_well.get(well_id, []):
                held.add((link.parcel_id, month_str))

    ordered = sorted(rows.values(), key=lambda r: (r["reg_id"], r["month"]))
    return ordered, held


def _gears_by_well_rows(reporting_period: ReportingPeriod) -> list[dict[str, Any]]:
    """Metered volume per (well, month); unlinked parcels become [INCOMPLETE] rows."""
    return _gears_by_well_build(reporting_period)[0]


def _write_gears_by_well(writer: Any, reporting_period: ReportingPeriod) -> None:
    """Write the GEARS by-well header and one line per well-month."""
    writer.writerow(GEARS_WELL_HEADER)
    for row in _gears_by_well_rows(reporting_period):
        writer.writerow(safe_row([
            row["reg_id"], row["name"], row["lat"], row["lon"],
            row["month"], row["volume"], gears_method(row["method"]),
        ]))


class ByETLeftOut:
    """What the by-ET file leaves out, for the checks that name it.

    ``no_well``: the use areas with crop ET in the water year and no linked well.
    ``waiting``: ``{first of month: use area ids}`` OpenET has not sent crop ET for.
    ``not_calculated``: ``{first of month: use area ids}`` with crop ET and no calculation.
    Only use areas linked to a well count as waiting or not calculated, and a month the
    by-well file holds counts as neither.
    """

    def __init__(self):
        self.no_well: set[int] = set()
        self.waiting: dict[Any, set[int]] = {}
        self.not_calculated: dict[Any, set[int]] = {}


def _split_by_shares(acre_feet: Decimal, links: list[WellIrrigatedParcel]) -> list[tuple[Any, Decimal]]:
    """``[(well, part)]``: a use area's month divided among its wells by the links' shares.

    Each well takes its link's share over the sum of the use area's shares (equal parts when
    every share is 0), at four places, and the last well the remainder, so the parts add up
    to the month's figure exactly.
    """
    total_share = sum((link.fraction for link in links), Decimal("0"))
    parts = []
    assigned = Decimal("0")
    for i, link in enumerate(links):
        if i == len(links) - 1:
            part = acre_feet - assigned
        elif total_share > 0:
            part = (acre_feet * link.fraction / total_share).quantize(Decimal("0.0001"))
        else:
            part = (acre_feet / len(links)).quantize(Decimal("0.0001"))
        assigned += part
        parts.append((link.well, part))
    return parts


def _gears_by_et_build(reporting_period: ReportingPeriod) -> tuple[list[dict[str, Any]], ByETLeftOut]:
    """The by-ET rows, one per (well, month), and what the file leaves out.

    A use area-month's figure is its ``calculated`` rows counted the way the account
    pages count them (``accounting.services.with_charged_extraction``: the run's
    groundwater extraction estimate). Each figure goes to the wells linked to the use
    area, divided by the links' shares. A use area with no linked well, a use area-month
    the by-well file holds (metered), a month waiting for OpenET and a month with crop
    ET and no calculation put no figure in the file.
    """
    from accounting.services import with_charged_extraction
    from datasync.crop_et import recorded_acre_feet, waiting_months

    left_out = ByETLeftOut()
    metered = _gears_by_well_build(reporting_period)[1]

    links_by_parcel: dict[int, list[WellIrrigatedParcel]] = {}
    for link in WellIrrigatedParcel.objects.select_related("well").order_by("pk"):
        links_by_parcel.setdefault(link.parcel_id, []).append(link)

    calculated = with_charged_extraction(
        ParcelLedger.objects.current().filter(
            source_type="calculated",
            # A calculated month's figure is stored negative (water used) or 0 (none
            # pumped); the account pages count nothing for anything above 0, and
            # neither does the file.
            amount_acre_feet__lte=0,
            effective_date__gte=reporting_period.start_date,
            effective_date__lte=reporting_period.end_date,
        )
    ).values_list("parcel_id", "effective_date", "charged_af")

    figures: dict[tuple[int, str], Decimal] = {}
    ran: set[tuple[int, Any]] = set()
    for parcel_id, effective_date, charged in calculated:
        ran.add((parcel_id, effective_date))
        key = (parcel_id, effective_date.strftime("%Y-%m"))
        if key in metered or parcel_id not in links_by_parcel:
            continue
        figures[key] = figures.get(key, Decimal("0")) + abs(charged)

    for figure in recorded_acre_feet(reporting_period.start_date, reporting_period.end_date):
        month_str = figure.month.strftime("%Y-%m")
        if (figure.parcel_id, month_str) in metered or (figure.parcel_id, figure.month) in ran:
            continue
        if figure.parcel_id not in links_by_parcel:
            left_out.no_well.add(figure.parcel_id)
        else:
            left_out.not_calculated.setdefault(figure.month, set()).add(figure.parcel_id)

    waiting = waiting_months(list(links_by_parcel), reporting_period.start_date, reporting_period.end_date)
    for parcel_id, months in waiting.items():
        for first in months:
            if (parcel_id, first.strftime("%Y-%m")) not in metered:
                left_out.waiting.setdefault(first, set()).add(parcel_id)

    rows: dict[tuple[int, str], dict[str, Any]] = {}
    for (parcel_id, month_str), acre_feet in figures.items():
        for well, part in _split_by_shares(acre_feet, links_by_parcel[parcel_id]):
            key = (well.pk, month_str)
            if key not in rows:
                rows[key] = {
                    "reg_id": well.well_registration_id or "",
                    "name": str(well),
                    "lat": well.location.y,
                    "lon": well.location.x,
                    "month": month_str,
                    "volume": Decimal("0"),
                    "method": "calculated",
                    "well_id": well.pk,
                }
            rows[key]["volume"] += part

    ordered = sorted(rows.values(), key=lambda r: (r["reg_id"], r["name"], r["month"]))
    return ordered, left_out


def _gears_by_et_rows(reporting_period: ReportingPeriod) -> list[dict[str, Any]]:
    """The by-ET rows: each well's month, from the use areas linked to it."""
    return _gears_by_et_build(reporting_period)[0]


def _write_gears_by_et(writer: Any, reporting_period: ReportingPeriod) -> None:
    """Write the by-ET file: the by-well file's header, one line per well-month."""
    writer.writerow(GEARS_WELL_HEADER)
    for row in _gears_by_et_rows(reporting_period):
        writer.writerow(safe_row([
            row["reg_id"], row["name"], row["lat"], row["lon"],
            row["month"], row["volume"], gears_method(row["method"]),
        ]))


def generate_gears_csv(reporting_period, method="by_well"):
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow([DEMONSTRATION_FILE_LINE])

    if method == "by_well":
        _write_gears_by_well(writer, reporting_period)
    elif method == "by_et":
        _write_gears_by_et(writer, reporting_period)

    output.seek(0)
    return output


def _calwatrs_data_row(entry, fraction, combined_use):
    """Build one CalWATRS data row.

    Both the parcel-linked and the parcel-less branches of generate_calwatrs_csv
    route through here so the two can never drift in column formatting again
    (they previously did: linked rows carried 8-decimal Volume/Return Flow while
    parcel-less rows emitted raw 4-decimal Decimals in the same columns).

    Volume and Return Flow are rendered as fixed 8-decimal strings. A Decimal
    whose value is an exact zero at a sub-1e-6 exponent — e.g. a zero volume or
    return multiplied by a normalized fraction — renders in Python as the
    scientific-notation string "0E-8", which looks malformed in a state file.
    Formatting with ``:.8f`` keeps full Decimal precision (it never routes
    through float) while guaranteeing a plain fixed-point column for every row.
    """
    pod = entry["pod"]
    # A point that carries its re-diversion link takes water an upstream point
    # already diverted: its volume is written in the re-diverted column and the
    # direct column reads zero, so the same water is not counted as a second
    # direct diversion.
    shown = entry["volume"] * fraction
    zero = Decimal("0")
    direct, rediverted = (zero, shown) if pod.rediverted_from_id else (shown, zero)
    return [
        entry["right_id"], entry["holder"], pod.name,
        float(fraction),
        pod.location.y, pod.location.x, entry["month"],
        f"{direct:.8f}",
        entry["max_flow"], entry["type"], combined_use,
        f"{entry['return_flow'] * fraction:.8f}",
        entry["method_label"],
        f"{rediverted:.8f}",
    ]


def _calwatrs_raw_volumes(records: Any) -> dict[tuple[int, str], dict[str, Any]]:
    """Sum each (pod, month) once: the gross volume, the return flow and the row's fixed fields."""
    # Aggregate raw volumes per (pod, month), then expand per parcel fraction.
    # PointOfDiversion.water_right is a nullable FK — guard against None.
    raw = {}
    for rec in records:
        pod = rec.point_of_diversion
        wr = pod.water_right
        month_str = rec.month.strftime("%Y-%m")
        key = (pod.pk, month_str)
        if key not in raw:
            if wr is None:
                right_id = ""
                holder_name = f"[INCOMPLETE] [No water right] {pod.name}"
            else:
                right_id = wr.right_id
                holder_name = wr.holder_name
            raw[key] = {
                "right_id": right_id,
                "holder": holder_name,
                "pod": pod,
                "month": month_str,
                "volume": Decimal("0"),
                # return_flow: OpenH2O's own annotation of the portion returned to
                # the stream. It rides ALONGSIDE the gross volume below — never
                # netted out of it. The state wants gross (under-reporting is a
                # Water Code §5107 exposure), so a non-consumptive POD shows its
                # full Volume (AF) AND an equal Return Flow (AF).
                "return_flow": Decimal("0"),
                # max_flow_rate_cfs: reported as CFS. 1 CFS × 1 day = 1.9835 AF.
                "max_flow": rec.max_flow_rate_cfs or Decimal("0"),
                "type": rec.get_diversion_type_display(),
                # The record-first method label. Each
                # (pod, month) key maps to exactly one DiversionRecord here --
                # the model's own unique_together on (point_of_diversion,
                # month, diversion_type) and this loop's own diversion_type
                # filter guarantee it -- so capturing the label at key
                # creation is safe and never overwritten by a second record.
                "method_label": calwatrs_method_label(rec),
            }
        raw[key]["volume"] += rec.volume_acre_feet
        raw[key]["return_flow"] += rec.returned_af
    return raw


def _calwatrs_file_rows(
    raw: dict[tuple[int, str], dict[str, Any]],
    pod_split: PodSplit,
    gw_parcel_ids: set[int],
    combined_parcel_ids: set[int],
) -> list[list[Any]]:
    """Expand each (pod, month) total into one row per use area, by that month's split."""
    rows = []
    for key in sorted(raw, key=lambda k: (raw[k]["right_id"], raw[k]["month"])):
        entry = raw[key]
        if entry["right_id"] == "":
            # A blank Water Right ID is a structurally-invalid key the
            # CalWATRS portal rejects/orphans. Withhold the row from the file;
            # validate_report surfaces it as a warning naming the POD instead, so
            # the volume is never lost — it is flagged for the operator to fix.
            continue
        pod = entry["pod"]
        parcel_fractions = pod_split.for_month(pod.pk, entry["month"])

        if parcel_fractions:
            for parcel_id, fraction in parcel_fractions:
                if parcel_id in combined_parcel_ids:
                    combined_use = "Combined"
                elif parcel_id in gw_parcel_ids:
                    combined_use = "GW Only"
                else:
                    combined_use = "SW Only"
                rows.append(_calwatrs_data_row(entry, fraction, combined_use))
        else:
            # POD not linked to any parcel — emit a single row at fraction 1.0,
            # SW Only. Same helper as the linked branch so the columns match.
            rows.append(_calwatrs_data_row(entry, Decimal("1"), "SW Only"))
    return rows


def generate_calwatrs_csv(reporting_period, template_type="a1"):
    # Local import: `surface` is an optional module; see
    # `build_pod_split_by_month`. The CalWATRS filing is a surface-water
    # report, so this generator is only ever reached with the module enabled.
    from surface.models import DiversionRecord, PointOfDiversionParcel

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow([DEMONSTRATION_FILE_LINE])

    writer.writerow([
        "Water Right ID", "Holder Name", "POD Name", "Source Fraction",
        "Latitude", "Longitude", "Month", "Volume (AF)",
        "Max Flow Rate (CFS)", "Diversion Type", "Combined Use",
        "Return Flow (AF)", "Measurement Method", "Re-diverted Volume (AF)",
    ])

    diversion_type = "direct_use" if template_type == "a1" else "to_storage"

    records = (
        DiversionRecord.objects.current().filter(
            reporting_period=reporting_period,
            diversion_type=diversion_type,
        )
        .select_related("point_of_diversion__water_right", "device")
        .order_by("point_of_diversion__water_right__right_id", "month")
    )

    # Each point's split among its use areas, month by month, as the ledger divided
    # it. The weights sum to 1.0 across the point's use areas, so its
    # diversion is reported ONCE, not N times.
    pod_split = build_pod_split_by_month(reporting_period)

    # Determine combined-use status per parcel: has both GW and SW sources
    gw_parcel_ids = set(
        WellIrrigatedParcel.objects.values_list("parcel_id", flat=True)
    )
    sw_parcel_ids = set(
        PointOfDiversionParcel.objects.values_list("parcel_id", flat=True)
    )
    combined_parcel_ids = gw_parcel_ids & sw_parcel_ids

    raw = _calwatrs_raw_volumes(records)
    rows = _calwatrs_file_rows(raw, pod_split, gw_parcel_ids, combined_parcel_ids)

    for row in rows:
        writer.writerow(safe_row(row))

    output.seek(0)
    return output
