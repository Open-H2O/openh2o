from collections import defaultdict
from decimal import Decimal

from django.db.models import Count

from parcels.models import ParcelLedger
from surface.models import DiversionRecord, PointOfDiversion
from wells.models import Well, WellIrrigatedParcel


def validate_report(reporting_period, report_type):
    warnings = []

    if not reporting_period.is_finalized:
        warnings.append({
            "level": "warning",
            "message": f"Period '{reporting_period.name}' is not finalized.",
        })

    if report_type in ("gears_by_well", "gears_by_et"):
        ledger_count = ParcelLedger.objects.filter(
            effective_date__gte=reporting_period.start_date,
            effective_date__lte=reporting_period.end_date,
        ).count()

        if ledger_count == 0:
            warnings.append({
                "level": "error",
                "message": "No ledger entries found for this period. GEARS report will be empty.",
            })

        if report_type == "gears_by_well":
            source_filter = "meter_reading"
            source_count = ParcelLedger.objects.filter(
                source_type=source_filter,
                effective_date__gte=reporting_period.start_date,
                effective_date__lte=reporting_period.end_date,
            ).count()
            if source_count == 0:
                warnings.append({
                    "level": "error",
                    "message": "No meter_reading entries found. GEARS by-well report requires meter readings.",
                })

            missing_reg = Well.objects.filter(
                status="active",
                well_registration_id__isnull=True,
            ).count()
            missing_reg += Well.objects.filter(
                status="active",
                well_registration_id="",
            ).count()
            if missing_reg > 0:
                warnings.append({
                    "level": "warning",
                    "message": f"{missing_reg} active well(s) missing well_registration_id.",
                })

            dupes = (
                ParcelLedger.objects.filter(
                    source_type="meter_reading",
                    effective_date__gte=reporting_period.start_date,
                    effective_date__lte=reporting_period.end_date,
                )
                .values("parcel_id", "effective_date__month", "effective_date__year")
                .annotate(cnt=Count("id"))
                .filter(cnt__gt=1)
            )
            dupe_count = dupes.count()
            if dupe_count > 0:
                warnings.append({
                    "level": "error",
                    "message": f"{dupe_count} duplicate parcel-month combination(s) in meter readings.",
                })

            # Warn if any well's fractions don't sum to 1.0 (auto-normalized for report).
            well_fractions = defaultdict(Decimal)
            for wip in WellIrrigatedParcel.objects.all():
                well_fractions[wip.well_id] += wip.fraction
            bad_wells = [
                wid for wid, total in well_fractions.items()
                if abs(total - Decimal("1")) > Decimal("0.01")
            ]
            if bad_wells:
                warnings.append({
                    "level": "warning",
                    "message": (
                        f"{len(bad_wells)} well(s) have fractions not summing to 1.0 "
                        "(auto-normalized for report)."
                    ),
                })

            active_wells = Well.objects.filter(status="active").count()
            if active_wells > 0 and source_count > 0:
                wells_with_data = (
                    WellIrrigatedParcel.objects.filter(
                        parcel__parcelledger__source_type="meter_reading",
                        parcel__parcelledger__effective_date__gte=reporting_period.start_date,
                        parcel__parcelledger__effective_date__lte=reporting_period.end_date,
                    )
                    .values("well_id")
                    .distinct()
                    .count()
                )
                coverage = (wells_with_data / active_wells) * 100
                if coverage < 80:
                    warnings.append({
                        "level": "warning",
                        "message": f"Data completeness: {coverage:.0f}% of active wells have data ({wells_with_data}/{active_wells}).",
                    })

        elif report_type == "gears_by_et":
            et_count = ParcelLedger.objects.filter(
                source_type="et_estimate",
                effective_date__gte=reporting_period.start_date,
                effective_date__lte=reporting_period.end_date,
            ).count()
            if et_count == 0:
                warnings.append({
                    "level": "error",
                    "message": "No et_estimate entries found. GEARS by-ET report requires ET data.",
                })

    elif report_type in ("calwatrs_a1", "calwatrs_a2"):
        diversion_type = "direct_use" if report_type == "calwatrs_a1" else "to_storage"
        div_count = DiversionRecord.objects.filter(
            reporting_period=reporting_period,
            diversion_type=diversion_type,
        ).count()

        if div_count == 0:
            warnings.append({
                "level": "error",
                "message": f"No {diversion_type} diversion records found for this period.",
            })

        dupes = (
            DiversionRecord.objects.filter(
                reporting_period=reporting_period,
                diversion_type=diversion_type,
            )
            .values("point_of_diversion_id", "month")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        dupe_count = dupes.count()
        if dupe_count > 0:
            warnings.append({
                "level": "error",
                "message": f"{dupe_count} duplicate POD-month combination(s) in diversion records.",
            })

        # Warn about PODs missing water rights — CalWATRS rows will show empty right_id.
        pods_no_wr = PointOfDiversion.objects.filter(
            water_right__isnull=True,
            diversionrecord__reporting_period=reporting_period,
        ).distinct().count()
        if pods_no_wr > 0:
            warnings.append({
                "level": "warning",
                "message": f"{pods_no_wr} point(s) of diversion have no linked water right.",
            })

        active_pods = PointOfDiversion.objects.filter(status="active").count()
        if active_pods > 0 and div_count > 0:
            pods_with_data = (
                DiversionRecord.objects.filter(
                    reporting_period=reporting_period,
                    diversion_type=diversion_type,
                )
                .values("point_of_diversion_id")
                .distinct()
                .count()
            )
            coverage = (pods_with_data / active_pods) * 100
            if coverage < 80:
                warnings.append({
                    "level": "warning",
                    "message": f"Data completeness: {coverage:.0f}% of active PODs have data ({pods_with_data}/{active_pods}).",
                })

    return warnings
