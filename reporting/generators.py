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

from parcels.models import ParcelLedger
from surface.models import DiversionRecord, PointOfDiversion, PointOfDiversionParcel
from wells.models import Well, WellIrrigatedParcel


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

        # Build well→parcel map with per-well fraction normalization.
        # WellIrrigatedParcel.fraction defaults to 1.0 (correct for single-well parcels).
        # Without normalization, a well irrigating N parcels all at fraction=1.0
        # would have its extraction multiplied by N — a double-counting bug.
        # Fix: normalize each well's fractions so they always sum to 1.0.
        raw_well_fractions = {}
        for wip in WellIrrigatedParcel.objects.select_related("well").all():
            raw_well_fractions.setdefault(wip.well_id, []).append(wip)

        well_parcel_map = {}  # parcel_id → [(well, normalized_fraction)]
        for well_id, wips in raw_well_fractions.items():
            total_fraction = sum(w.fraction for w in wips)
            for wip in wips:
                norm_fraction = wip.fraction / total_fraction if total_fraction > 0 else Decimal("0")
                well_parcel_map.setdefault(wip.parcel_id, []).append((wip.well, norm_fraction))

        rows = {}
        for entry in entries:
            well_fractions = well_parcel_map.get(entry.parcel_id, [])
            month_str = entry.effective_date.strftime("%Y-%m")
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

        for row in sorted(rows.values(), key=lambda r: (r["reg_id"], r["month"])):
            writer.writerow([
                row["reg_id"], row["name"], row["lat"], row["lon"],
                row["month"], row["volume"], row["method"],
            ])

    elif method == "by_et":
        writer.writerow([
            "Parcel Number", "Area (acres)", "Month",
            "ET Volume (AF)", "Measurement Method",
        ])

        entries = (
            ParcelLedger.objects.filter(
                source_type="et_estimate",
                effective_date__gte=reporting_period.start_date,
                effective_date__lte=reporting_period.end_date,
            )
            .select_related("parcel")
        )

        rows = {}
        for entry in entries:
            month_str = entry.effective_date.strftime("%Y-%m")
            key = (entry.parcel_id, month_str)
            if key not in rows:
                rows[key] = {
                    "parcel_number": entry.parcel.parcel_number,
                    "area": entry.parcel.area_acres or Decimal("0"),
                    "month": month_str,
                    "volume": Decimal("0"),
                    "method": "et_estimate",
                }
            rows[key]["volume"] += abs(entry.amount_acre_feet)

        for row in sorted(rows.values(), key=lambda r: (r["parcel_number"], r["month"])):
            writer.writerow([
                row["parcel_number"], row["area"], row["month"],
                row["volume"], row["method"],
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

    # Build pod→[(parcel_id, fraction)] map from PointOfDiversionParcel
    pod_parcel_map = {}
    for podp in PointOfDiversionParcel.objects.all():
        pod_parcel_map.setdefault(podp.point_of_diversion_id, []).append(
            (podp.parcel_id, podp.fraction)
        )

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
