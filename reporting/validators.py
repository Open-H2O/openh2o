# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-flight data-quality checks for the state report filings.

Produces warning/error/info messages for a reporting period and report type,
covering GEARS (well registration, meter-reading and ET completeness, parcel
linkage) and CalWATRS (POD water-right linkage, PINs, return-flow passthrough).
Each message names the state outcome it predicts so an operator knows what will
happen at the portal before filing.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Count

from parcels.models import ParcelLedger
from reporting.models import ReportingProfile
from wells.models import Well, WellIrrigatedParcel

if TYPE_CHECKING:
    from accounting.models import ReportingPeriod

#: One pre-flight message: {"level": "error" | "warning" | "info", "message": str}.
PreflightMessage = dict[str, str]


def validate_report(reporting_period: ReportingPeriod, report_type: str) -> list[PreflightMessage]:
    """Pre-flight checks phrased as the state outcome they predict.

    Messages name the system (GEARS / CalWATRS) and what it will do — a hard
    reject, an empty filing, or enforcement exposure — rather than just naming a
    missing internal field. The goal is that the user reads a warning and knows
    what will happen at the portal.
    """
    warnings: list[PreflightMessage] = []

    if not reporting_period.is_finalized:
        warnings.append({
            "level": "warning",
            "message": (
                f"Water year '{reporting_period.name}' is not finalized; finalize it so the "
                "numbers can't change after you certify the filing."
            ),
        })

    if report_type in ("gears_by_well", "gears_by_et"):
        warnings.extend(_gears_filing_warnings(reporting_period))

        if report_type == "gears_by_well":
            warnings.extend(_gears_by_well_warnings(reporting_period))

        elif report_type == "gears_by_et":
            warnings.extend(_gears_by_et_warnings(reporting_period))

    elif report_type in ("calwatrs_a1", "calwatrs_a2"):
        warnings.extend(_calwatrs_warnings(reporting_period, report_type))

    return warnings


def _gears_filing_warnings(reporting_period: ReportingPeriod) -> list[PreflightMessage]:
    """Checks every GEARS filing needs: the Correspondence ID and some ledger entries at all."""
    warnings: list[PreflightMessage] = []

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
    return warnings


def _gears_by_well_warnings(reporting_period: ReportingPeriod) -> list[PreflightMessage]:
    """Checks for the GEARS by-well filing, in the order the portal would trip on them."""
    warnings: list[PreflightMessage] = []

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

    warnings.extend(_missing_registration_warnings())
    warnings.extend(_duplicate_reading_warnings(reporting_period))
    warnings.extend(_well_split_warnings())
    warnings.extend(_well_coverage_warnings(reporting_period, source_count))
    warnings.extend(_unlinked_parcel_warnings(reporting_period))
    return warnings


def _missing_registration_warnings() -> list[PreflightMessage]:
    """Error when an active well has no registration ID."""
    missing_reg = Well.objects.filter(
        status="active",
        well_registration_id__isnull=True,
    ).count()
    missing_reg += Well.objects.filter(
        status="active",
        well_registration_id="",
    ).count()
    if missing_reg > 0:
        return [{
            "level": "error",
            "message": (
                f"{missing_reg} active well(s) have no well registration ID — GEARS "
                "rejects well rows without one. Register them before you upload."
            ),
        }]
    return []


def _duplicate_reading_warnings(reporting_period: ReportingPeriod) -> list[PreflightMessage]:
    """Error when a parcel has more than one meter reading in a month."""
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
        return [{
            "level": "error",
            "message": (
                f"{dupe_count} duplicate parcel-month reading(s) — GEARS rejects more "
                "than one volume per well per month."
            ),
        }]
    return []


def _well_split_warnings() -> list[PreflightMessage]:
    """Warn on wells whose hand-set parcel split does not add up to 100%."""
    # Warn ONLY on a genuine hand-set inconsistency. Under derive-at-read-
    # time, an untouched well leaves every parcel at the default
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
        return [{
            "level": "warning",
            "message": (
                f"{len(bad_wells)} well(s) have a hand-set parcel split that doesn't "
                "add up to 100% — check those entries (the file normalizes it anyway)."
            ),
        }]
    return []


def _well_coverage_warnings(reporting_period: ReportingPeriod, source_count: int) -> list[PreflightMessage]:
    """Warn when under 80% of active wells have a meter reading in the period."""
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
            return [{
                "level": "warning",
                "message": (
                    f"Only {coverage:.0f}% of active wells have data "
                    f"({wells_with_data}/{active_wells}) — the GEARS file will only "
                    "contain wells with readings."
                ),
            }]
    return []


def _unlinked_parcel_warnings(reporting_period: ReportingPeriod) -> list[PreflightMessage]:
    """Warn about metered parcels with no well link."""
    # A metered parcel with no well link can't be attributed to a
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
        return [{
            "level": "warning",
            "message": (
                f"{len(unlinked)} metered parcel(s) have no well link — their "
                "extraction appears in the GEARS file as an unallocated "
                "[INCOMPLETE] row with no registration ID. Link each parcel to "
                "its well so the volume is attributed."
            ),
        }]
    return []


def _gears_by_et_warnings(reporting_period: ReportingPeriod) -> list[PreflightMessage]:
    """Checks for the GEARS by-ET filing: ET estimates present, acreage recorded."""
    warnings: list[PreflightMessage] = []

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

    # A parcel with ET but no recorded acreage leaves a blank Area
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
    return warnings


def _calwatrs_warnings(reporting_period: ReportingPeriod, report_type: str) -> list[PreflightMessage]:
    """Checks for a CalWATRS A-1 or A-2 filing, in the order the portal would trip on them."""
    # Local import: `surface` is an optional module, so this must
    # not run at module scope. Every surface reference in this function lives
    # inside this branch, and CalWATRS is a surface-water filing — the branch
    # is unreachable on a deployment without the module.
    from surface.models import DiversionRecord

    warnings: list[PreflightMessage] = []

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

    warnings.extend(_orphan_diversion_warnings(reporting_period, diversion_type))
    warnings.extend(_duplicate_pod_month_warnings(reporting_period, diversion_type))
    warnings.extend(_pods_without_right_warnings(reporting_period))
    warnings.extend(_pod_coverage_warnings(reporting_period, diversion_type, div_count))
    warnings.extend(_pod_split_warnings())
    warnings.extend(_return_flow_passthrough_warnings(reporting_period, diversion_type))
    return warnings


def _orphan_diversion_warnings(reporting_period: ReportingPeriod, diversion_type: str) -> list[PreflightMessage]:
    """Diversion records attached to no water year, inside and outside this period."""
    from surface.models import DiversionRecord

    warnings: list[PreflightMessage] = []

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
                "attached to no water year; they would be silently missing from "
                "this CalWATRS filing. Create or edit the water year that covers these "
                "months; records attach when the year is saved, or open each record "
                "and save it."
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
                "no water year; they will never appear in any filing "
                "until a period covering their month exists."
            ),
        })
    return warnings


def _duplicate_pod_month_warnings(reporting_period: ReportingPeriod, diversion_type: str) -> list[PreflightMessage]:
    """Error when a point of diversion has more than one record in a month."""
    from surface.models import DiversionRecord

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
        return [{
            "level": "error",
            "message": (
                f"{dupe_count} duplicate POD-month record(s) — CalWATRS expects one entry "
                "per point of diversion per month."
            ),
        }]
    return []


def _pods_without_right_warnings(reporting_period: ReportingPeriod) -> list[PreflightMessage]:
    """Warn about points of diversion with no linked water right."""
    from surface.models import PointOfDiversion

    # PODs with no linked right produce a blank Water Right ID. The
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
        return [{
            "level": "warning",
            "message": (
                f"{len(pods_no_wr_names)} point(s) of diversion have no linked water "
                f"right ({names}) — their rows are withheld from the CalWATRS file "
                "(a blank Water Right ID is flagged as an unauthorized diversion, "
                "Water Code §1846). Link each POD to its right first."
            ),
        }]
    return []


def _pod_coverage_warnings(
    reporting_period: ReportingPeriod, diversion_type: str, div_count: int
) -> list[PreflightMessage]:
    """Warn when under 80% of active points of diversion have a record in the period."""
    from surface.models import DiversionRecord, PointOfDiversion

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
            return [{
                "level": "warning",
                "message": (
                    f"Only {coverage:.0f}% of active PODs have data "
                    f"({pods_with_data}/{active_pods}) — CalWATRS will only contain the "
                    "diversions you entered."
                ),
            }]
    return []


def _pod_split_warnings() -> list[PreflightMessage]:
    """Warn on points of diversion whose hand-set parcel split does not add up to 100%."""
    from surface.models import PointOfDiversionParcel

    # Warn ONLY on a genuine hand-set
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
        return [{
            "level": "warning",
            "message": (
                f"{len(bad_pods)} point(s) of diversion have a hand-set parcel split "
                "that doesn't add up to 100% — check those entries (the file "
                "normalizes it anyway)."
            ),
        }]
    return []


def _return_flow_passthrough_warnings(reporting_period: ReportingPeriod, diversion_type: str) -> list[PreflightMessage]:
    """Inform about points of diversion that return their full volume to the stream."""
    from surface.models import DiversionRecord

    # Return flow is INFORMATIONAL, never a volume discrepancy.
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
        return [{
            "level": "info",
            "message": (
                f"{len(passthrough_pods)} point(s) of diversion return the full "
                f"diverted volume to the stream ({names}) — their Volume (AF) is "
                "reported gross as the state requires, with the returned amount in "
                "the Return Flow (AF) column. Expected for non-consumptive "
                "(hydropower passthrough) use, not a volume discrepancy."
            ),
        }]
    return []
