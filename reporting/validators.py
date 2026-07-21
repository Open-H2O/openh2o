# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-flight data-quality checks for the state report filings.

Produces warning/error/info messages for a reporting period and report type,
covering GEARS (well registration, meter-reading and ET completeness, parcel
linkage) and CalWATRS (POD water-right linkage, PINs, return-flow passthrough).
Each message names the state outcome it predicts so an operator knows what will
happen at the portal before filing.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count

from parcels.models import ParcelLedger
from reporting.models import ReportingProfile
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

            # Warn ONLY on a genuine hand-set inconsistency. Under derive-at-read-
            # time (Phase 56), an untouched well leaves every parcel at the default
            # 1.0 sentinel and the kernel splits it correctly — that is NOT an error,
            # so it must stay silent (else every shared well warns noisily). A well is
            # "hand-set" once any parcel's fraction is nudged off 1.0; only then does a
            # split that doesn't add up to 100% mean a real data-entry mistake.
            well_fractions = defaultdict(list)
            for wip in WellIrrigatedParcel.objects.all():
                well_fractions[wip.well_id].append(wip.fraction)
            bad_wells = [
                wid for wid, fracs in well_fractions.items()
                if any(f != Decimal("1.0") for f in fracs)
                and abs(sum(fracs) - Decimal("1")) > Decimal("0.01")
            ]
            if bad_wells:
                warnings.append({
                    "level": "warning",
                    "message": (
                        f"{len(bad_wells)} well(s) have a hand-set parcel split that doesn't "
                        "add up to 100% — check those entries (the file normalizes it anyway)."
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

            # ISS-027: a metered parcel with no well link can't be attributed to a
            # well row. The generator surfaces it as an unallocated [INCOMPLETE]
            # row rather than dropping the volume — warn so the operator links it.
            metered_parcel_ids = set(
                ParcelLedger.objects.filter(
                    source_type="meter_reading",
                    effective_date__gte=reporting_period.start_date,
                    effective_date__lte=reporting_period.end_date,
                ).values_list("parcel_id", flat=True)
            )
            linked_parcel_ids = set(
                WellIrrigatedParcel.objects.values_list("parcel_id", flat=True)
            )
            unlinked = metered_parcel_ids - linked_parcel_ids
            if unlinked:
                warnings.append({
                    "level": "warning",
                    "message": (
                        f"{len(unlinked)} metered parcel(s) have no well link — their "
                        "extraction appears in the GEARS file as an unallocated "
                        "[INCOMPLETE] row with no registration ID. Link each parcel to "
                        "its well so the volume is attributed."
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

            # ISS-031c: a parcel with ET but no recorded acreage leaves a blank Area
            # cell in the file (never a misleading 0). Name them so they get fixed.
            null_area_parcels = sorted(
                set(
                    ParcelLedger.objects.filter(
                        source_type__in=["et_estimate", "calculated"],
                        effective_date__gte=reporting_period.start_date,
                        effective_date__lte=reporting_period.end_date,
                        parcel__area_acres__isnull=True,
                    ).values_list("parcel__parcel_number", flat=True)
                )
            )
            if null_area_parcels:
                names = ", ".join(null_area_parcels)
                warnings.append({
                    "level": "warning",
                    "message": (
                        f"{len(null_area_parcels)} parcel(s) with ET have no recorded "
                        f"acreage ({names}) — the GEARS by-ET file leaves their Area "
                        "blank rather than reporting a misleading 0. Record acreage for "
                        "each."
                    ),
                })

    elif report_type in ("calwatrs_a1", "calwatrs_a2"):
        # Local import: `surface` is an optional module (Phase 87), so this must
        # not run at module scope. Every surface reference in this function lives
        # inside this branch, and CalWATRS is a surface-water filing — the branch
        # is unreachable on a deployment without the module.
        from surface.models import (
            DiversionRecord,
            PointOfDiversion,
            PointOfDiversionParcel,
            WaterRight,
        )

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

        # A record saved while no reporting period covered its month carries
        # reporting_period=None and is invisible to every period-scoped filing —
        # it exists on the POD page but would silently never reach CalWATRS.
        orphans_in_range = DiversionRecord.objects.filter(
            reporting_period__isnull=True,
            diversion_type=diversion_type,
            month__gte=reporting_period.start_date,
            month__lte=reporting_period.end_date,
        ).count()
        if orphans_in_range > 0:
            warnings.append({
                "level": "error",
                "message": (
                    f"{orphans_in_range} diversion record(s) dated inside this period are "
                    "attached to NO reporting period — they would be silently missing from "
                    "this CalWATRS filing. Re-save them (or edit and save) so they attach "
                    "to the period."
                ),
            })

        orphans_elsewhere = DiversionRecord.objects.filter(
            reporting_period__isnull=True,
            diversion_type=diversion_type,
        ).exclude(
            month__gte=reporting_period.start_date,
            month__lte=reporting_period.end_date,
        ).count()
        if orphans_elsewhere > 0:
            warnings.append({
                "level": "warning",
                "message": (
                    f"{orphans_elsewhere} diversion record(s) outside this period belong to "
                    "NO reporting period at all — they will never appear in any filing "
                    "until a period covering their month exists."
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

        # ISS-031b: PODs with no linked right produce a blank Water Right ID. The
        # generator WITHHOLDS those rows (a blank key is rejected/orphaned by the
        # portal); name the PODs here so the withheld volume is never lost from
        # view and the operator knows exactly what to link before filing.
        pods_no_wr_names = sorted(
            PointOfDiversion.objects.filter(
                water_right__isnull=True,
                diversionrecord__reporting_period=reporting_period,
            ).distinct().values_list("name", flat=True)
        )
        if pods_no_wr_names:
            names = ", ".join(pods_no_wr_names)
            warnings.append({
                "level": "warning",
                "message": (
                    f"{len(pods_no_wr_names)} point(s) of diversion have no linked water "
                    f"right ({names}) — their rows are withheld from the CalWATRS file "
                    "(a blank Water Right ID is flagged as an unauthorized diversion, "
                    "Water Code §1846). Link each POD to its right first."
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

        # ISS-028, reconciled for Phase 56: warn ONLY on a genuine hand-set
        # inconsistency. An untouched POD leaves every parcel at the 1.0 sentinel and
        # the kernel splits it correctly at read time — silent. A POD is "hand-set"
        # once any parcel's fraction is nudged off 1.0; only then does a deliberate
        # split that doesn't add up to 100% signal a real data-entry mistake. The
        # mirror of the by-well fraction-sum warning above.
        pod_fractions = defaultdict(list)
        for podp in PointOfDiversionParcel.objects.all():
            pod_fractions[podp.point_of_diversion_id].append(podp.fraction)
        bad_pods = [
            pid for pid, fracs in pod_fractions.items()
            if any(f != Decimal("1.0") for f in fracs)
            and abs(sum(fracs) - Decimal("1")) > Decimal("0.01")
        ]
        if bad_pods:
            warnings.append({
                "level": "warning",
                "message": (
                    f"{len(bad_pods)} point(s) of diversion have a hand-set parcel split "
                    "that doesn't add up to 100% — check those entries (the file "
                    "normalizes it anyway)."
                ),
            })

        # Phase 67-02: return flow is INFORMATIONAL, never a volume discrepancy.
        # CalWATRS reports the GROSS diverted volume the state requires; the
        # returned portion rides in its own Return Flow (AF) column, never netted.
        # A POD that returns its FULL volume (hydropower / non-consumptive
        # passthrough) is intentional, not an error — name it so the operator sees
        # the gross figure is expected. Mirrors the pod-fraction informational note;
        # NEVER error-level.
        passthrough_pods = sorted(
            {
                rec.point_of_diversion.name
                for rec in DiversionRecord.objects.filter(
                    reporting_period=reporting_period,
                    diversion_type=diversion_type,
                ).select_related("point_of_diversion")
                if rec.returned_af > 0
                and rec.returned_af == abs(rec.volume_acre_feet)
            }
        )
        if passthrough_pods:
            names = ", ".join(passthrough_pods)
            warnings.append({
                "level": "info",
                "message": (
                    f"{len(passthrough_pods)} point(s) of diversion return the full "
                    f"diverted volume to the stream ({names}) — their Volume (AF) is "
                    "reported gross as the state requires, with the returned amount in "
                    "the Return Flow (AF) column. Expected for non-consumptive "
                    "(hydropower passthrough) use, not a volume discrepancy."
                ),
            })

    return warnings
