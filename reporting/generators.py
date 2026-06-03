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

from accounting.services import billable_ledger
from parcels.models import ParcelLedger
from surface.models import DiversionRecord, PointOfDiversion, PointOfDiversionParcel
from wells.models import Well, WellIrrigatedParcel


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


def build_normalized_well_parcel_map():
    """Return ``{parcel_id: [(well, normalized_fraction), ...]}``.

    WellIrrigatedParcel.fraction defaults to 1.0 (correct for single-well parcels).
    Without normalization, a well irrigating N parcels all at fraction=1.0 would
    have its volume multiplied by N — a double-counting bug. Normalize each well's
    fractions so they always sum to 1.0 across the parcels it irrigates.

    This is the single source of truth for the well↔parcel allocation: both the
    GEARS by-well CSV (generate_gears_csv) and the OpenET pre-fill
    (reporting.services.build_openet_prefill) call it, so they can never drift
    apart on how a multi-parcel well's volume is split.
    """
    raw = {}  # well_id → [(wip, fraction)]
    for wip in WellIrrigatedParcel.objects.select_related("well").all():
        raw.setdefault(wip.well_id, []).append((wip, wip.fraction))

    well_parcel_map = {}  # parcel_id → [(well, normalized_fraction)]
    for well_id, members in _normalize_fractions(raw).items():
        for wip, norm_fraction in members:
            well_parcel_map.setdefault(wip.parcel_id, []).append((wip.well, norm_fraction))
    return well_parcel_map


def build_normalized_pod_parcel_map():
    """Return ``{pod_id: [(parcel_id, normalized_fraction), ...]}``.

    The mirror image of build_normalized_well_parcel_map on the surface-water
    side. PointOfDiversionParcel.fraction also defaults to 1.0, so a POD diverting
    to N parcels all at 1.0 would have its diverted volume multiplied by N when the
    CalWATRS CSV splits it across them — the same double-count the well map guards
    against (ISS-028). Normalize each POD's fractions to sum to 1.0.
    """
    raw = {}  # pod_id → [(parcel_id, fraction)]
    for podp in PointOfDiversionParcel.objects.all():
        raw.setdefault(podp.point_of_diversion_id, []).append(
            (podp.parcel_id, podp.fraction)
        )
    return _normalize_fractions(raw)


def generate_gears_csv(reporting_period, method="by_well"):
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

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

        # Build well→parcel map with per-well fraction normalization. Shared with
        # the OpenET pre-fill so the double-count guard can never drift between them.
        well_parcel_map = build_normalized_well_parcel_map()

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

    writer.writerow([
        "Water Right ID", "Holder Name", "POD Name", "Source Fraction",
        "Latitude", "Longitude", "Month", "Volume (AF)",
        "Max Flow Rate (CFS)", "Diversion Type", "Combined Use",
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

    # Build pod→[(parcel_id, normalized_fraction)] map. Normalized so a POD with
    # N parcels all at the default fraction=1.0 reports its diversion ONCE across
    # them, not N times (ISS-028) — the mirror of the well↔parcel guard.
    pod_parcel_map = build_normalized_pod_parcel_map()

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
                # max_flow_rate_cfs: reported as CFS. 1 CFS × 1 day = 1.9835 AF.
                "max_flow": rec.max_flow_rate_cfs or Decimal("0"),
                "type": rec.get_diversion_type_display(),
            }
        raw[key]["volume"] += rec.volume_acre_feet

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
                ])
        else:
            # POD not linked to any parcel — emit row with fraction 1.0, SW Only
            rows.append([
                entry["right_id"], entry["holder"], pod.name,
                1.0,
                pod.location.y, pod.location.x, entry["month"],
                entry["volume"],
                entry["max_flow"], entry["type"], "SW Only",
            ])

    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return output
