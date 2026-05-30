from collections import defaultdict
from decimal import Decimal

from django.db.models import Count

from parcels.models import ParcelLedger
from reporting.models import ReportingProfile
from surface.models import DiversionRecord, PointOfDiversion, WaterRight
from wells.models import Well, WellIrrigatedParcel


def validate_report(reporting_period, report_type):
    """Pre-flight checks phrased as the state outcome they predict.

    Messages name the system (GEARS / CalWATRS) and what it will do — a hard
    reject, an empty filing, or enforcement exposure — rather than just naming a
    missing internal field. The goal is that the user reads a warning and knows
    what will happen at the portal.
    """
    warnings = []

    if not reporting_period.is_finalized:
        warnings.append({
            "level": "warning",
            "message": (
                f"Period '{reporting_period.name}' is not finalized — finalize it so the "
                "numbers can't change after you certify the filing."
            ),
        })

    if report_type in ("gears_by_well", "gears_by_et"):
        # GEARS login requires the Correspondence ID the state mailed the agency.
        profile = ReportingProfile.objects.first()
        if not profile or not profile.gears_correspondence_id:
            warnings.append({
                "level": "warning",
                "message": (
                    "No GEARS Correspondence ID on file — you'll need it to log in and "
                    "upload. Add it to your Reporting Profile."
                ),
            })

        ledger_count = ParcelLedger.objects.filter(
            effective_date__gte=reporting_period.start_date,
            effective_date__lte=reporting_period.end_date,
        ).count()

        if ledger_count == 0:
            warnings.append({
                "level": "error",
                "message": "No ledger entries for this period — the GEARS upload would be empty.",
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
                    "message": (
                        "No meter readings for this period — GEARS by-well requires metered "
                        "extraction volumes."
                    ),
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
                    "level": "error",
                    "message": (
                        f"{missing_reg} active well(s) have no well registration ID — GEARS "
                        "rejects well rows without one. Register them before you upload."
                    ),
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
                    "message": (
                        f"{dupe_count} duplicate parcel-month reading(s) — GEARS rejects more "
                        "than one volume per well per month."
                    ),
                })

            # Warn if any well's fractions don't sum to 1.0 (auto-normalized for the file).
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
                        f"{len(bad_wells)} well(s) have parcel fractions not summing to 1.0 "
                        "(auto-normalized for the GEARS file)."
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
                        "message": (
                            f"Only {coverage:.0f}% of active wells have data "
                            f"({wells_with_data}/{active_wells}) — the GEARS file will only "
                            "contain wells with readings."
                        ),
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
                    "message": (
                        "No ET estimates for this period — GEARS by-ET requires ET-derived "
                        "consumptive-use data."
                    ),
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
                "message": (
                    f"No {diversion_type.replace('_', ' ')} diversion records for this period — "
                    "the CalWATRS form would have nothing to enter."
                ),
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
                "message": (
                    f"{dupe_count} duplicate POD-month record(s) — CalWATRS expects one entry "
                    "per point of diversion per month."
                ),
            })

        # PODs with no linked right are unauthorized-diversion exposure in CalWATRS.
        pods_no_wr = PointOfDiversion.objects.filter(
            water_right__isnull=True,
            diversionrecord__reporting_period=reporting_period,
        ).distinct().count()
        if pods_no_wr > 0:
            warnings.append({
                "level": "warning",
                "message": (
                    f"{pods_no_wr} point(s) of diversion have no linked water right — filing "
                    "these in CalWATRS may be flagged as an unauthorized diversion "
                    "(Water Code §1846). Link each POD to its right first."
                ),
            })

        # CalWATRS is filed per right under that right's PIN.
        rights_missing_pin = (
            WaterRight.objects.filter(
                pointofdiversion__diversionrecord__reporting_period=reporting_period,
                pointofdiversion__diversionrecord__diversion_type=diversion_type,
                calwatrs_pin="",
            )
            .distinct()
            .count()
        )
        if rights_missing_pin > 0:
            warnings.append({
                "level": "warning",
                "message": (
                    f"{rights_missing_pin} water right(s) in this filing have no CalWATRS PIN — "
                    "you need each right's PIN to file. Add it on the water right."
                ),
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
                    "message": (
                        f"Only {coverage:.0f}% of active PODs have data "
                        f"({pods_with_data}/{active_pods}) — CalWATRS will only contain the "
                        "diversions you entered."
                    ),
                })

    return warnings
