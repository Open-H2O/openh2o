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

import csv
import io
from decimal import Decimal

from django.db.models import Sum

from accounting.allocation_math import apportion_shared_supply
from accounting.models import CalculationRun
from accounting.services import billable_ledger
from core.models import SiteConfig
from parcels.models import Parcel, ParcelLedger
from surface.models import DiversionRecord, PointOfDiversion, PointOfDiversionParcel
from wells.models import Well, WellIrrigatedParcel


# ISS-056 soft divergence flag: a parcel whose stored weight and ET-implied
# weight differ by this much (absolute weight, i.e. 15 percentage points) is
# worth a second look — a likely data-entry tell. Display-only; nothing is
# auto-corrected.
SHARED_SUPPLY_DIVERGENCE_THRESHOLD = Decimal("0.15")


# GEARS "Extraction volume measurement method" controlled vocabulary (ISS-047a).
# The GEARS portal prints this field as a fixed label, not our internal code.
# Source: a SWRCB Groundwater Extraction Report with Report Status "Accepted"
# (Extractor 25226 / Well 6895, Water Year 2018) prints the value
# "Unmetered/Estimated"; the same report's fee schedule splits the field into
# metered vs unmetered. We crosswalk our ParcelLedger.source_type codes onto the
# two state-facing labels here rather than leaking the internal code into the
# filing. (UCUM is deliberately NOT used — it targets the v1.3 open-data
# exports, not these state CSVs; see ISS-047d.)
GEARS_METHOD = {
    "meter_reading": "Metered",
    "et_estimate": "Unmetered/Estimated",
    "calculated": "Unmetered/Estimated",
}


def gears_method(source_type):
    """Crosswalk an internal source_type to the GEARS measurement-method label.

    An unknown code passes through unchanged so a newly-added source_type is
    visible in the file (and catchable by validate_report) rather than being
    silently relabeled to a wrong state value.
    """
    return GEARS_METHOD.get(source_type, source_type)


def _normalize_fractions(raw_by_group):
    """Scale each group's fractions so they sum to 1.0.

    Input:  ``{group_id: [(member, fraction), ...]}``
    Output: ``{group_id: [(member, normalized_fraction), ...]}``

    The single source of truth for the double-count guard on BOTH sides — the
    well↔parcel map and the POD↔parcel map call it — so the GEARS and CalWATRS
    files can never drift on how a multi-member share is split. A group whose
    fractions sum to 0 collapses to 0 (no volume attributed) rather than dividing
    by zero.
    """
    normalized = {}
    for group_id, members in raw_by_group.items():
        total = sum(frac for _, frac in members)
        for member, frac in members:
            norm = frac / total if total > 0 else Decimal("0")
            normalized.setdefault(group_id, []).append((member, norm))
    return normalized


def _period_demand_by_parcel(reporting_period):
    """Return ``{parcel_id: net_consumptive_use_af}`` summed over a period's runs.

    The per-parcel ET demand signal that the apportionment kernel weights a shared
    source against (rung 3). One grouped query — a Sum annotation over the period's
    ``CalculationRun`` rows, NOT a per-parcel loop (Architecture Gate: no N+1). A
    parcel with no run is simply absent from the map; callers treat that as demand
    0. ``reporting_period is None`` returns an empty map, so every parcel reads as
    demand 0 — that is what makes a no-period call reproduce today's static split.

    CalculationRun.period is a "YYYY-MM" string; matching ``parcel_net_consumptive_use``
    in accounting.services, we select the parcel-months by a lexical string range
    from the period's start month to its end month.
    """
    if reporting_period is None:
        return {}
    start = f"{reporting_period.start_date.year}-{reporting_period.start_date.month:02d}"
    end = f"{reporting_period.end_date.year}-{reporting_period.end_date.month:02d}"
    rows = (
        CalculationRun.objects.filter(period__gte=start, period__lte=end)
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
      - absent any hand-set fraction, the volume follows measured ET demand for the
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


def build_normalized_pod_parcel_map(reporting_period=None):
    """Return ``{pod_id: [(parcel_id, weight), ...]}`` split by the 56 kernel.

    The mirror image of build_normalized_well_parcel_map on the surface-water
    side. PointOfDiversionParcel.fraction also defaults to 1.0, so a POD diverting
    to N parcels all at 1.0 would have its diverted volume multiplied by N when the
    CalWATRS CSV splits it across them — the same double-count the well map guards
    against (ISS-028). Each POD's parcels run through the SAME measurement-first
    ``apportion_shared_supply`` ladder (hand-set wins, else ET demand for the
    ``reporting_period``, else even), so the weights sum to exactly 1.0. Passing no
    ``reporting_period`` reproduces today's static split.
    """
    demand_by_parcel = _period_demand_by_parcel(reporting_period)

    members_by_pod = {}  # pod_id → [(parcel_id, fraction, demand)]
    for podp in PointOfDiversionParcel.objects.all():
        members_by_pod.setdefault(podp.point_of_diversion_id, []).append(
            (
                podp.parcel_id,
                podp.fraction,
                demand_by_parcel.get(podp.parcel_id, Decimal("0")),
            )
        )

    return {
        pod_id: list(apportion_shared_supply(members).items())
        for pod_id, members in members_by_pod.items()
    }


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
      suppressed. This is the demo state until Phase 58 re-runs the engine.
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
            }
        )
    return {"has_et_signal": has_et, "rows": rows, "any_flag": any_flag}


def build_shared_supply_comparison(reporting_period=None):
    """ISS-056: stored split vs. ET-implied split for each hand-set shared source.

    A *shared source* is a well or point of diversion serving more than one
    parcel. A source is *hand-set* when a district nudged any member's link
    ``fraction`` off the ``Decimal("1.0")`` sentinel — rung 2 of
    ``apportion_shared_supply``, where the human split wins over ET demand.

    For every hand-set shared source this surfaces a two-column reasonableness
    check — the stored split a human entered beside the split measured ET demand
    would imply — with a soft per-parcel flag where the two diverge by >= 15
    points. **Display only**: a hand-set share is never auto-overwritten.

    A pure demand-split (all fractions untouched) is excluded — its two columns
    are identical by construction, so there is nothing to compare. Single-parcel
    sources are excluded — there is no split.

    Returns a list of group dicts ordered by source name::

        {"kind": "Well" | "Point of diversion", "source_name": str,
         "has_et_signal": bool, "any_flag": bool,
         "rows": [{"parcel_number", "your_weight", "et_weight" (Decimal|None),
                   "divergence" (Decimal|None), "flag": bool}, ...]}
    """
    demand_by_parcel = _period_demand_by_parcel(reporting_period)

    # Gather candidate hand-set shared sources from both link tables.
    candidates = []  # (kind, source_name, [(parcel_id, fraction), ...])

    wips_by_well = {}
    for wip in WellIrrigatedParcel.objects.select_related("well").all():
        wips_by_well.setdefault(wip.well, []).append(wip)
    for well, wips in wips_by_well.items():
        if len(wips) < 2:
            continue
        if not any(wip.fraction != Decimal("1.0") for wip in wips):
            continue  # untouched fractions → not hand-set, nothing to compare
        candidates.append(
            ("Well", well.name, [(wip.parcel_id, wip.fraction) for wip in wips])
        )

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
                [(podp.parcel_id, podp.fraction) for podp in podps],
            )
        )

    # One query for every parcel number we will display (no N+1).
    parcel_ids = {pid for _, _, links in candidates for pid, _ in links}
    parcel_names = dict(
        Parcel.objects.filter(id__in=parcel_ids).values_list("id", "parcel_number")
    )

    groups = []
    for kind, source_name, links in candidates:
        comparison = _compare_split(links, demand_by_parcel, parcel_names)
        groups.append(
            {
                "kind": kind,
                "source_name": source_name,
                "has_et_signal": comparison["has_et_signal"],
                "any_flag": comparison["any_flag"],
                "rows": comparison["rows"],
            }
        )
    groups.sort(key=lambda g: (g["kind"], g["source_name"]))
    return groups


def generate_gears_csv(reporting_period, method="by_well"):
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow(["DEMONSTRATION DATA — sample values, not an official submission"])

    if method == "by_well":
        writer.writerow([
            "Well Registration ID", "Well Name", "Latitude", "Longitude",
            "Month", "Extraction Volume (AF)", "Measurement Method",
        ])

        entries = (
            ParcelLedger.objects.filter(
                source_type="meter_reading",
                effective_date__gte=reporting_period.start_date,
                effective_date__lte=reporting_period.end_date,
            )
            .select_related("parcel")
        )

        # Build well→parcel map split by the measurement-first kernel for THIS
        # period (hand-set share wins; else the thirsty crop's well carries the
        # larger slice via ET demand). Shared with the OpenET pre-fill so the
        # double-count guard and the demand split can never drift between them.
        well_parcel_map = build_normalized_well_parcel_map(reporting_period)

        rows = {}
        for entry in entries:
            well_fractions = well_parcel_map.get(entry.parcel_id, [])
            month_str = entry.effective_date.strftime("%Y-%m")
            if well_fractions:
                for well, fraction in well_fractions:
                    key = (well.pk, month_str)
                    if key not in rows:
                        rows[key] = {
                            "reg_id": well.well_registration_id or "",
                            "name": str(well),
                            "lat": well.location.y,
                            "lon": well.location.x,
                            "month": month_str,
                            "volume": Decimal("0"),
                            "method": "meter_reading",
                        }
                    rows[key]["volume"] += abs(entry.amount_acre_feet) * fraction
            else:
                # ISS-027: metered extraction on a parcel with no well link. Never
                # silently drop it — emit a parcel-keyed [INCOMPLETE] row so the
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
                    }
                rows[key]["volume"] += abs(entry.amount_acre_feet)

        for row in sorted(rows.values(), key=lambda r: (r["reg_id"], r["month"])):
            writer.writerow([
                row["reg_id"], row["name"], row["lat"], row["lon"],
                row["month"], row["volume"], gears_method(row["method"]),
            ])

    elif method == "by_et":
        writer.writerow([
            "Parcel Number", "Area (acres)", "Month",
            "ET Volume (AF)", "Measurement Method",
        ])

        # Query BOTH ET-family sources, then let billable_ledger() pick the
        # netted ``calculated`` row where the engine ran and fall back to the raw
        # ``et_estimate`` row where it didn't. This keeps the state filing
        # consistent with the internal bill (same shared suppression helper, so
        # they can never drift), and labels each surviving row by its own source.
        entries = (
            ParcelLedger.objects.filter(
                source_type__in=["et_estimate", "calculated"],
                effective_date__gte=reporting_period.start_date,
                effective_date__lte=reporting_period.end_date,
            )
            .select_related("parcel")
        )
        entries = billable_ledger(entries)

        rows = {}
        for entry in entries:
            month_str = entry.effective_date.strftime("%Y-%m")
            key = (entry.parcel_id, month_str)
            if key not in rows:
                rows[key] = {
                    "parcel_number": entry.parcel.parcel_number,
                    # ISS-031c: a null acreage becomes a blank cell, never a literal
                    # 0 — reporting 0 acres beside a real ET volume is self-
                    # inconsistent to a state reviewer. validate_report flags it.
                    "area": (
                        entry.parcel.area_acres
                        if entry.parcel.area_acres is not None
                        else ""
                    ),
                    "month": month_str,
                    "volume": Decimal("0"),
                    "method": entry.source_type,
                }
            rows[key]["volume"] += abs(entry.amount_acre_feet)

        for row in sorted(rows.values(), key=lambda r: (r["parcel_number"], r["month"])):
            writer.writerow([
                row["parcel_number"], row["area"], row["month"],
                row["volume"], gears_method(row["method"]),
            ])

    output.seek(0)
    return output


def generate_calwatrs_csv(reporting_period, template_type="a1"):
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow(["DEMONSTRATION DATA — sample values, not an official submission"])

    writer.writerow([
        "Water Right ID", "Holder Name", "POD Name", "Source Fraction",
        "Latitude", "Longitude", "Month", "Volume (AF)",
        "Max Flow Rate (CFS)", "Diversion Type", "Combined Use",
        "Return Flow (AF)",
    ])

    diversion_type = "direct_use" if template_type == "a1" else "to_storage"

    records = (
        DiversionRecord.objects.filter(
            reporting_period=reporting_period,
            diversion_type=diversion_type,
        )
        .select_related("point_of_diversion__water_right")
        .order_by("point_of_diversion__water_right__right_id", "month")
    )

    # Build pod→[(parcel_id, weight)] map split by the measurement-first kernel for
    # THIS period. Sums to 1.0 across the POD's parcels so its diversion is reported
    # ONCE, not N times (ISS-028); where no share is hand-set the split follows ET
    # demand so the thirsty crop carries the larger slice — the mirror of the well guard.
    pod_parcel_map = build_normalized_pod_parcel_map(reporting_period)

    # Determine combined-use status per parcel: has both GW and SW sources
    gw_parcel_ids = set(
        WellIrrigatedParcel.objects.values_list("parcel_id", flat=True)
    )
    sw_parcel_ids = set(
        PointOfDiversionParcel.objects.values_list("parcel_id", flat=True)
    )
    combined_parcel_ids = gw_parcel_ids & sw_parcel_ids

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
            }
        raw[key]["volume"] += rec.volume_acre_feet
        raw[key]["return_flow"] += rec.returned_af

    rows = []
    for key in sorted(raw, key=lambda k: (raw[k]["right_id"], raw[k]["month"])):
        entry = raw[key]
        if entry["right_id"] == "":
            # ISS-031b: a blank Water Right ID is a structurally-invalid key the
            # CalWATRS portal rejects/orphans. Withhold the row from the file;
            # validate_report surfaces it as a warning naming the POD instead, so
            # the volume is never lost — it is flagged for the operator to fix.
            continue
        pod = entry["pod"]
        parcel_fractions = pod_parcel_map.get(pod.pk, [])

        if parcel_fractions:
            for parcel_id, fraction in parcel_fractions:
                if parcel_id in combined_parcel_ids:
                    combined_use = "Combined"
                elif parcel_id in gw_parcel_ids:
                    combined_use = "GW Only"
                else:
                    combined_use = "SW Only"
                rows.append([
                    entry["right_id"], entry["holder"], pod.name,
                    float(fraction),
                    pod.location.y, pod.location.x, entry["month"],
                    entry["volume"] * fraction,
                    entry["max_flow"], entry["type"], combined_use,
                    # Fixed-decimal string so an exact-zero return reads
                    # "0.00000000" — Decimal renders zero at this precision as the
                    # scientific-notation "0E-8", which looks wrong in a state file.
                    f"{entry['return_flow'] * fraction:.8f}",
                ])
        else:
            # POD not linked to any parcel — emit row with fraction 1.0, SW Only
            rows.append([
                entry["right_id"], entry["holder"], pod.name,
                1.0,
                pod.location.y, pod.location.x, entry["month"],
                entry["volume"],
                entry["max_flow"], entry["type"], "SW Only",
                entry["return_flow"],
            ])

    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return output
