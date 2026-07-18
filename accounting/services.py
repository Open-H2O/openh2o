# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Accounting service functions.

Diversion/recharge ledger integration utilities and balance calculations.
"""

# --- Unit conversion constants ---
# 1 acre-foot (AF) = 1,233.48 cubic meters = 325,851 US gallons
# 1 CFS (cubic foot per second) flowing for 1 day = 1.9835 AF
#   Derivation: 1 CFS × 86,400 s/day × 0.0283168 m³/ft³ / 1,233.48 m³/AF = 1.9835
# 1 GPM (gallon per minute) = 0.002228 CFS = 0.004419 AF/day
#   Well capacity_gpm field uses this; convert to CFS for hydraulic calcs.
# 1 mm of ET over 1 acre = 1/304.8 AF = 0.003281 AF
#   See et_mm_to_acre_feet() for full derivation.
# Reference: USGS Water Science School; California DWR unit conversion tables.
#
# DecimalField precision audit (all fields adequate for CA district scale):
#   ParcelLedger.amount_acre_feet        max_digits=12, decimal_places=4 → max 99,999,999 AF
#   DiversionRecord.volume_acre_feet     max_digits=12, decimal_places=4 → same
#   AllocationPlan.allocation_acre_feet  max_digits=12, decimal_places=4 → same
#   WaterRight.face_value_acre_feet      max_digits=12, decimal_places=4 → same
#   WellIrrigatedParcel.fraction         max_digits=5,  decimal_places=4 → range 0–9.9999 (sufficient)
#   Well.capacity_gpm                    max_digits=8,  decimal_places=2 → max 999,999 GPM
#   PointOfDiversion.max_rate_cfs        max_digits=10, decimal_places=4 → max 999,999 CFS

import csv
import io
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from geography.models import ParcelZone
from parcels.models import Parcel, ParcelLedger

from core.constants import CARRY_FORWARD

from accounting.carryover_math import water_year_of
from accounting.ledger_import import import_ledger_rows
from accounting.models import (
    AllocationCarryover,
    AllocationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterAccountParcel,
    WaterType,
)

logger = logging.getLogger(__name__)

# Basin-pool origins on AllocationCarryover (52.6-02, ISS-053). Managed and
# incidental recharge are tracked as separate pool rows so each contributor can
# reset its own slice idempotently; they are summed for display/recovery.
BASIN_RECHARGE_POOL = "basin_recharge_pool"
INCIDENTAL_RECHARGE_POOL = "incidental_recharge_pool"


def deposit_to_basin_pool(
    zone, water_type, water_year, amount_af, origin=BASIN_RECHARGE_POOL
):
    """Add ``amount_af`` to the GSA basin recharge pool for a (zone, water_type, year).

    The basin pool is an ``AllocationCarryover`` row marked with a pool ``origin``
    (default ``basin_recharge_pool`` for managed recharge; the engine passes
    ``incidental_recharge_pool`` for deep-percolation). Recharge that infiltrates
    the shared aquifer but belongs to no single parcel accumulates here instead of
    being smeared onto surface-only parcels (the ISS-053 phantom).

    Upserts on ``(zone, water_type, water_year, origin)`` and increments
    ``amount_af`` by ``amount_af`` (additive — two deposits to the same key SUM
    into one row). ``amount_af`` is normally positive, but the engine passes a
    signed *delta* to keep a re-run idempotent, so a negative value is honoured.
    ``select_for_update`` inside a transaction serialises the read-modify-write so
    the engine's per-parcel loop can deposit many times for one key without losing
    an increment. Returns the pool row.
    """
    amount = Decimal(str(amount_af))
    with transaction.atomic():
        row, _created = (
            AllocationCarryover.objects.select_for_update().get_or_create(
                zone=zone,
                water_type=water_type,
                water_year=water_year,
                origin=origin,
                defaults={"amount_af": Decimal("0")},
            )
        )
        row.amount_af = (row.amount_af + amount).quantize(Decimal("0.0001"))
        row.save(update_fields=["amount_af"])
        return row


def create_diversion_ledger_entries(diversion_record, parcel=None):
    """Create negative ledger entries for a surface water diversion.

    Distributes the diversion volume across all parcels linked to the point of
    diversion via PointOfDiversionParcel, using each link's fraction field.

    Args:
        diversion_record: A surface.models.DiversionRecord instance.
        parcel: Optional Parcel instance. When supplied, creates a single entry
            for that parcel (backward-compatible behavior).

    Returns:
        List of created ParcelLedger entries.

    Raises:
        ValueError: If no parcel supplied and no links found via
            PointOfDiversionParcel or WaterRightParcel.
    """
    if parcel is not None:
        # Backward-compatible: explicit parcel gets a single entry
        entry = ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=timezone.now().date(),
            effective_date=diversion_record.month,
            amount_acre_feet=-diversion_record.consumed_acre_feet(),
            source_type="surface_diversion",
            description=(
                f"Diversion from {diversion_record.point_of_diversion.name}: "
                f"{diversion_record.volume_acre_feet} AF "
                f"({diversion_record.get_diversion_type_display()})"
            ),
            reporting_period=diversion_record.reporting_period,
            water_type=None,
        )
        return [entry]

    from surface.models import PointOfDiversionParcel, WaterRightParcel

    pod = diversion_record.point_of_diversion
    pod_parcels = list(
        PointOfDiversionParcel.objects.filter(
            point_of_diversion=pod
        ).select_related("parcel")
    )

    if pod_parcels:
        # Distribute by fraction with rounding residual on last entry. Only the
        # consumed magnitude is apportioned, so returned water never reaches the
        # spine; the description still shows gross volume_acre_feet.
        total_volume = diversion_record.consumed_acre_feet()
        today = timezone.now().date()
        entries = []
        distributed = Decimal("0")

        for i, pod_parcel in enumerate(pod_parcels):
            if i == len(pod_parcels) - 1:
                amount = total_volume - distributed
            else:
                amount = (total_volume * pod_parcel.fraction).quantize(
                    Decimal("0.0001")
                )
                distributed += amount

            entries.append(
                ParcelLedger(
                    parcel=pod_parcel.parcel,
                    transaction_date=today,
                    effective_date=diversion_record.month,
                    amount_acre_feet=-amount,
                    source_type="surface_diversion",
                    description=(
                        f"Diversion from {pod.name}: "
                        f"{diversion_record.volume_acre_feet} AF "
                        f"({diversion_record.get_diversion_type_display()}) "
                        f"fraction={pod_parcel.fraction}"
                    ),
                    reporting_period=diversion_record.reporting_period,
                    water_type=None,
                )
            )

        return list(ParcelLedger.objects.bulk_create(entries))

    # Fallback: use WaterRightParcel if no POD-parcel links
    water_right = pod.water_right
    if water_right is not None:
        link = WaterRightParcel.objects.filter(water_right=water_right).first()
        if link is not None:
            entry = ParcelLedger.objects.create(
                parcel=link.parcel,
                transaction_date=timezone.now().date(),
                effective_date=diversion_record.month,
                amount_acre_feet=-diversion_record.consumed_acre_feet(),
                source_type="surface_diversion",
                description=(
                    f"Diversion from {pod.name}: "
                    f"{diversion_record.volume_acre_feet} AF "
                    f"({diversion_record.get_diversion_type_display()})"
                ),
                reporting_period=diversion_record.reporting_period,
                water_type=None,
            )
            return [entry]

    raise ValueError(
        f"No parcel supplied and no PointOfDiversionParcel or WaterRightParcel "
        f"link for POD '{pod.name}'"
    )


# Backward-compatible alias
def create_diversion_ledger_entry(diversion_record, parcel=None):
    """Deprecated alias for create_diversion_ledger_entries. Returns a single entry."""
    entries = create_diversion_ledger_entries(diversion_record, parcel=parcel)
    return entries[0] if entries else None


def create_recharge_ledger_entries(recharge_event, zone=None, parcel=None):
    """Route a managed recharge event to the GSA basin pool — or one has-well parcel.

    The old behaviour smeared the event volume area-weighted across EVERY parcel
    in the zone, inventing a recoverable groundwater credit on surface-only
    parcels that have no well to pump it back (the ISS-053 phantom — MER-APN-031's
    12.57 AF). The water physically infiltrates the shared aquifer, so by default
    the WHOLE event volume is deposited to the zone's managed basin recharge pool
    (an ``AllocationCarryover`` row, origin ``basin_recharge_pool``) and NO
    per-parcel ledger rows are written.

    The single per-parcel personal-credit path is the conjunctive case: when a
    caller ties the event to a specific has-well parcel, that parcel CAN recover
    its recharge, so it gets one personal groundwater ledger row instead of
    pooling. (The Merced demo never passes a parcel, so it always pools.)

    Args:
        recharge_event: A recharge.models.RechargeEvent instance.
        zone: Zone to pool into. If None, falls back to
            ``recharge_event.recharge_site.zone``.
        parcel: Optional has-well Parcel the event is tied to (personal path).

    Returns:
        ``[the one personal ParcelLedger row]`` on the personal path, else ``[]``
        — the pool deposit is an AllocationCarryover row, not a ledger row.

    Raises:
        ValueError: If no zone supplied and the recharge site has no zone FK set.
    """
    from accounting.recharge_policy import recharge_routes_to_personal

    if zone is None:
        zone = recharge_event.recharge_site.zone
        if zone is None:
            raise ValueError(
                f"No zone supplied and recharge site "
                f"'{recharge_event.recharge_site.name}' has no zone set"
            )

    water_type = recharge_event.water_type
    if water_type is None:
        water_type, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )
    volume = recharge_event.volume_acre_feet

    # Personal path: a conjunctive (has-well) parcel tied to this event recovers
    # its own recharge, so it gets one personal groundwater credit, not the pool.
    if parcel is not None and recharge_routes_to_personal(parcel):
        entry = ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=timezone.now().date(),
            effective_date=recharge_event.start_date,
            amount_acre_feet=volume,
            source_type="recharge",
            description=(
                f"Recharge from {recharge_event.recharge_site.name}: "
                f"{volume} AF personal credit (has-well parcel)"
            ),
            reporting_period=None,
            water_type=water_type,
        )
        return [entry]

    # Default basin/GSA path: the whole event infiltrates the shared aquifer, so
    # it deposits to the zone's managed basin pool and writes NO per-parcel rows.
    water_year = water_year_of(
        f"{recharge_event.start_date.year}-{recharge_event.start_date.month:02d}"
    )
    deposit_to_basin_pool(
        zone, water_type, water_year, volume, origin=BASIN_RECHARGE_POOL
    )
    return []


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


def _parse_date(date_str):
    """Parse a date string in YYYY-MM-DD or MM/DD/YYYY format. Returns None on failure."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def parse_ledger_csv(csv_file, reporting_period=None, dry_run=False):
    """Parse a CSV file and create ledger entries (web-upload entry point).

    A thin adapter over ``accounting.ledger_import.import_ledger_rows``, which is
    the single import service shared with the ``import_ledger_csv`` management
    command. This function's only job is turning an uploaded file into a text
    stream; every rule lives in that module.

    Merged onto the shared core by the math eval's item 3 (2026-07-18). Uploading
    through the UI previously skipped the duplicate check (re-uploading a file
    doubled every row), could write into a finalized reporting period, and used a
    usage-source set that omitted ``calculated``. It now behaves exactly like the
    command.

    Args:
        csv_file: A file-like object (from request.FILES or open()).
        reporting_period: Optional ReportingPeriod to assign to all entries.
        dry_run: If True, validate only without creating records.

    Returns:
        dict with keys:
            created_count (int),
            error_count (int),
            errors (list of {"line": int, "messages": list[str]}),
            preview (list of first 5 created/validated entries as dicts with
                     parcel_number, effective_date, amount, source_type),
            skipped_duplicate (int),
            sign_normalized (int) — rows whose sign was corrected to the ledger
                convention; the upload page shows this so it is never silent.
    """
    # Wrap binary upload files in a text reader; already-text files pass through
    if hasattr(csv_file, "read"):
        try:
            text_file = io.TextIOWrapper(csv_file, encoding="utf-8-sig")
        except TypeError:
            # Already a text-mode file
            text_file = csv_file
    else:
        text_file = csv_file

    return import_ledger_rows(
        text_file,
        reporting_period=reporting_period,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# OpenET conversion helpers
# ---------------------------------------------------------------------------


def et_mm_to_acre_feet(et_mm, area_acres):
    """Convert evapotranspiration in mm to acre-feet consumed.

    ET (AF) = ET (mm) × area (acres) / 304.8

    Derivation:
      1 acre-foot = 1 acre × 1 foot = 43,560 ft² × 0.3048 m/ft = 1,233.48 m³
      1 mm over 1 acre = 0.001 m × 4,046.86 m² = 4.04686 m³
      1 AF / 4.04686 m³ per (mm·acre) = 304.8 mm·acre per AF

    Returns a negative value because ET is water consumption (usage).
    Reference: USGS Water Science School unit conversions; CA DWR ET guidance.
    """
    return -(Decimal(str(et_mm)) / Decimal("304.8")) * area_acres


# ---------------------------------------------------------------------------
# Balance calculations
# ---------------------------------------------------------------------------


def billable_ledger(queryset):
    """Return the billable subset of a ParcelLedger queryset.

    The calculation engine (Phase 38) writes a netted ``calculated`` row per
    parcel-month alongside the pre-existing gross ``et_estimate`` row. Both are
    stored negative, so summing every row double-counts ET. A metered parcel has
    the same shape one layer down: the meter row is the authoritative usage
    (58-03 — the engine deliberately writes NO ``calculated`` row for it), yet
    ``sync_openet_to_ledger`` still writes the parcel's ``et_estimate`` row, so
    summing both double-counts the metered month. This applies the settled
    authority ladder — calculated ≻ meter_reading ≻ et_estimate:

      - Where a ``calculated`` row exists for a ``(parcel_id, month)``, the
        matching ``et_estimate`` row is suppressed (the netted row bills).
      - Where a ``meter_reading`` row exists for a ``(parcel_id, month)``, the
        matching ``et_estimate`` row is likewise suppressed (measured pumping
        outranks the satellite estimate of the same month's use).
      - Where neither exists, the ``et_estimate`` row stands in so no
        parcel-month silently drops to zero (the fallback).
      - Every other row (meter_reading itself, surface_diversion, recharge, the
        calculated rows) passes through unchanged.

    Join keys: ET-family rows are dated to the first of the month, so
    ``calculated`` pairs on exact ``(parcel_id, effective_date)``;
    ``meter_reading`` rows carry the reading's real in-month date, so their key
    is normalized to the first of the month before matching. The suppression is
    source-type-driven (not reporting-period-driven), so it holds whether or not
    a period filter has already been applied to ``queryset``.

    Empty queryset → empty.
    """
    suppression_keys = set(
        queryset.filter(source_type="calculated").values_list(
            "parcel_id", "effective_date"
        )
    )
    suppression_keys.update(
        (parcel_id, effective_date.replace(day=1))
        for parcel_id, effective_date in queryset.filter(
            source_type="meter_reading"
        ).values_list("parcel_id", "effective_date")
    )
    if not suppression_keys:
        return queryset

    # OR of EXACT (parcel_id, effective_date) pairs. A flat
    # ``parcel_id__in + effective_date__in`` would over-exclude the cross-product
    # (any suppressing parcel × any suppressing date), wrongly suppressing an
    # et_estimate row that has no counterpart of its own. District scale is
    # monthly and small, so the per-pair OR is cheap and correct.
    suppression = Q()
    for parcel_id, effective_date in suppression_keys:
        suppression |= Q(parcel_id=parcel_id, effective_date=effective_date)

    return queryset.exclude(Q(source_type="et_estimate") & suppression)


def parcel_balance(parcel, reporting_period=None):
    """Sum of all ledger entries for a parcel.

    Args:
        parcel: A Parcel instance.
        reporting_period: Optional ReportingPeriod to filter by.

    Returns:
        Decimal total (positive = net supply, negative = net usage).
    """
    qs = ParcelLedger.objects.filter(parcel=parcel)
    if reporting_period is not None:
        qs = qs.filter(reporting_period=reporting_period)
    qs = billable_ledger(qs)
    result = qs.aggregate(total=Sum("amount_acre_feet"))
    return result["total"] or Decimal("0")


def parcel_balance_breakdown(parcel, reporting_period=None):
    """supply/usage/net for ONE parcel, routed through billable_ledger.

    The per-parcel sibling of account_balance / zone_balance: it walks the SAME
    filter -> billable_ledger -> _balance_dict path, so a parcel's figures sit on
    the same billable basis as the account total it rolls up into. Because
    billable_ledger suppresses per exact (parcel_id, effective_date), partitioning
    an account's ledger by parcel and summing the per-parcel breakdowns reproduces
    the account-level breakdown exactly — the per-parcel rows reconcile with the
    account total instead of showing ~double it (ISS-026: a netted `calculated`
    row suppresses its gross `et_estimate` twin; no ET double-count).

    Returns the same dict shape as _balance_dict: {total, supply, usage, net}.
    """
    qs = ParcelLedger.objects.filter(parcel=parcel)
    if reporting_period is not None:
        qs = qs.filter(reporting_period=reporting_period)
    return _balance_dict(billable_ledger(qs))


def _balance_dict(queryset):
    """Compute supply/usage/net from a ParcelLedger queryset.

    Returns:
        dict with keys: total (alias for net), supply, usage, net.
        - supply: positive entries + surface-water delivered (Decimal, >= 0)
        - usage: absolute value of negative groundwater entries (Decimal, >= 0)
        - net: supply - usage (can be negative if usage exceeds supply)
        - total: alias for net

    Sign convention vs. semantics. Most rows split by sign: positive is supply
    (allocation, recharge), negative is usage (groundwater extraction —
    meter_reading / et_estimate / calculated). The ONE exception is
    ``surface_diversion``: it is stored NEGATIVE (the production convention the
    calc engine and CSV importer share — a delivered magnitude as a negative
    number), but a canal delivery is a SUPPLY to the parcel that offsets
    groundwater need, NOT consumption. So its magnitude is counted as supply
    regardless of stored sign. This keeps the dashboard's supply/usage story
    correct while the ledger stores the production-canonical negative sign.

    Edge cases:
        - Empty queryset: supply=0, usage=0, net=0
        - Zero-amount entries (amount=0) are excluded from both supply and usage.
    """
    agg = queryset.aggregate(
        supply_pos=Sum(
            "amount_acre_feet",
            filter=Q(amount_acre_feet__gt=0) & ~Q(source_type="surface_diversion"),
        ),
        usage_neg=Sum(
            "amount_acre_feet",
            filter=Q(amount_acre_feet__lt=0) & ~Q(source_type="surface_diversion"),
        ),
        surface=Sum(
            "amount_acre_feet",
            filter=Q(source_type="surface_diversion"),
        ),
    )
    supply = (agg["supply_pos"] or Decimal("0")) + abs(agg["surface"] or Decimal("0"))
    usage = abs(agg["usage_neg"] or Decimal("0"))
    net = supply - usage
    return {
        "total": net,
        "supply": supply,
        "usage": usage,
        "net": net,
    }


def account_balance(water_account, reporting_period=None):
    """Aggregate balance across all parcels assigned to a water account.

    Uses active assignments only (removed_date is null).

    Args:
        water_account: A WaterAccount instance.
        reporting_period: Optional ReportingPeriod to filter by.

    Returns:
        dict with keys: total, supply, usage, net (all Decimal).
    """
    parcel_ids = WaterAccountParcel.objects.filter(
        water_account=water_account,
        removed_date__isnull=True,
    ).values_list("parcel_id", flat=True)

    qs = ParcelLedger.objects.filter(parcel_id__in=parcel_ids)
    if reporting_period is not None:
        qs = qs.filter(reporting_period=reporting_period)

    return _balance_dict(billable_ledger(qs))


def zone_balance(zone, reporting_period=None):
    """Aggregate balance across all parcels in a zone.

    Args:
        zone: A geography.models.Zone instance.
        reporting_period: Optional ReportingPeriod to filter by.

    Returns:
        dict with keys: total, supply, usage, net (all Decimal).
    """
    parcel_ids = ParcelZone.objects.filter(zone=zone).values_list(
        "parcel_id", flat=True
    )

    qs = ParcelLedger.objects.filter(parcel_id__in=parcel_ids)
    if reporting_period is not None:
        qs = qs.filter(reporting_period=reporting_period)

    return _balance_dict(billable_ledger(qs))


# ---------------------------------------------------------------------------
# Per-parcel closing mass balance (52.6-03, ISS-053)
# ---------------------------------------------------------------------------

#: Decimal tolerance for "the books close" — absorbs 4-dp ledger rounding.
MASS_BALANCE_TOLERANCE = Decimal("0.01")

#: Corrected v1.10 acceptance band (58-03). Real water accounting never closes to
#: zero — a meter measures pumping (which exceeds the crop's consumptive use by the
#: on-farm loss / return flow), deficit irrigation under curtailment leaves a real
#: shortfall, etc. A residual within this fraction of gross ET is "small, realistic,
#: and not alarming" (Brent's bar): present it as a normal minor surplus/shortfall,
#: NOT a warning. Only a residual BEYOND it (e.g. a curtailed surface-only parcel
#: that lost its peak-season water) is flagged for attention.
REALISTIC_RESIDUAL_BAND = Decimal("0.25")


def residual_band_status(residual_af, gross_et_af, *, closes):
    """Classify a mass-balance residual for presentation (58-03).

    Returns one of ``"closes"`` (≈0, the books balance), ``"realistic"`` (a small,
    expected residual within ``REALISTIC_RESIDUAL_BAND`` of gross ET — a minor
    surplus from pump/return-flow loss or a minor shortfall), or ``"large"`` (a
    residual beyond the band — e.g. a curtailment-driven supply shortfall worth
    flagging). ``closes`` is the boolean the mass balance already computed.
    """
    if closes:
        return "closes"
    et = gross_et_af or Decimal("0")
    if et and abs(residual_af) <= REALISTIC_RESIDUAL_BAND * et:
        return "realistic"
    return "large"


def _incidental_recharge_af(breakdown):
    """Read deep-percolation recharge (AF) off a CalculationRun.breakdown.

    Mirrors the engine's reader (run_calculations._incidental_recharge_af): the
    clamp_floor step records ``incidental_recharge_af`` — the surface/precip
    over-delivery that percolated to the aquifer (ISS-052). Duplicated here as a
    few lines rather than imported, to keep services.py free of an import cycle
    with the management command (which imports from services). Returns a
    non-negative Decimal; 0 when no clamp_floor step ran.
    """
    for step in breakdown or []:
        if step.get("step_type") == "clamp_floor":
            detail = step.get("detail") or {}
            return Decimal(str(detail.get("incidental_recharge_af", "0")))
    return Decimal("0")


def runs_in_period(queryset, reporting_period):
    """Narrow a ``CalculationRun`` queryset to one reporting period, by DATE.

    THE single way to ask "which runs belong to this period" (math eval item 6).
    Before this, the codebase asked three different ways — a reporting_period FK
    on ledger rows, real date comparisons, and a LEXICAL string range over the
    ``"YYYY-MM"`` text column — and the string form is the one that could not
    express a period boundary falling mid-month.

    MEMBERSHIP RULE, stated plainly because it is a real limitation and not an
    accident: a CalculationRun covers a WHOLE month, so a month is included when
    it OVERLAPS the period at all. A period running 15 Mar – 15 Sep therefore
    pulls all of March and all of September, not half of each. Monthly runs
    cannot be split without pro-rating, and pro-rating would invent daily
    resolution the data does not have.

    This reproduces exactly the set the old lexical range selected — deliberately,
    so filed numbers do not shift underneath anyone — but it is now expressed in
    dates, and the truncation it implies is surfaced rather than hidden: see
    ``ReportingPeriod``'s mid-month check in ``health.checks``.

    ``reporting_period=None`` is a no-op (every run in the queryset).
    """
    if reporting_period is None:
        return queryset
    first_month = reporting_period.start_date.replace(day=1)
    return queryset.filter(
        period_start__gte=first_month,
        period_start__lte=reporting_period.end_date,
    )


def _calculation_runs_for_period(parcel, reporting_period):
    """CalculationRun rows for one parcel within a reporting period.

    Thin per-parcel wrapper over ``runs_in_period``; see it for the membership
    rule. ``reporting_period=None`` returns every run for the parcel.
    """
    return runs_in_period(
        CalculationRun.objects.filter(parcel=parcel), reporting_period
    )


def parcel_net_consumptive_use(parcel, reporting_period=None):
    """Sum a parcel's net consumptive use over a reporting period (Decimal AF).

    Net consumptive use (gross ET − effective precip) is the source-agnostic
    spine quantity recorded on every ET-bearing CalculationRun, independent of
    supply source or whether a well exists (54-01). This reader sums
    ``net_consumptive_use_af`` across the period's runs — the readable per-parcel
    demand signal that Phase 55 ET-demand allocation weights against.
    ``reporting_period=None`` sums every run for the parcel. Returns Decimal("0")
    when the parcel has no runs.
    """
    total = Decimal("0")
    for run in _calculation_runs_for_period(parcel, reporting_period):
        total += run.net_consumptive_use_af or Decimal("0")
    return total


def parcel_run_periods(parcel, reporting_period=None):
    """The distinct ``"YYYY-MM"`` months a parcel has a CalculationRun for.

    The per-parcel audit drill-down (57-03): each month a parcel was engine-run
    has its own gross→net waterfall at ``accounting:calculation_run_detail``
    (keyed on the stable ``(parcel_id, period)``). This returns the sorted list
    of those month strings within ``reporting_period`` so the parcel balance card
    can link each one to its audit page. Empty list when the parcel has no runs
    (the surface-only ISS-054 case — nothing to audit yet). Reuses
    ``_calculation_runs_for_period`` so it scopes identically to the balance read.
    """
    return sorted(
        _calculation_runs_for_period(parcel, reporting_period)
        .values_list("period", flat=True)
        .distinct()
    )


def parcel_mass_balance(parcel, reporting_period=None):
    """The closing water mass balance for one parcel over a reporting period.

    Proves the per-parcel books close (ISS-053): every unit of water flowing in
    is accounted for flowing out, with no phantom credit left on a parcel that
    cannot use it. The named identity is::

        surface + precip + gw_recovered = et + recharge + runoff + delta_storage

    Term sourcing — deliberately REUSING the existing billable/balance helpers
    so this never drifts from ``parcel_balance_breakdown``:

    * ``surface`` (input): magnitude of ``surface_diversion`` ledger rows (stored
      negative; a canal delivery is supply). Taken from the same billable
      queryset the breakdown uses.
    * ``precip`` (input): ``CalculationRun.effective_precip_af`` summed over the
      period's parcel-months.
    * ``gw_recovered`` (input): the billable groundwater usage — literally the
      ``_balance_dict`` usage term, so the two can never disagree. Credit-draw
      timing is carried by ``delta_storage`` (banked − drawn), not double-counted
      here.
    * ``et`` (output): ``CalculationRun.gross_et_af`` (gross actual ET).
    * ``recharge`` (output): deep-percolation that left the parcel, read from
      each month's engine breakdown (``incidental_recharge_af``). For a no-well
      parcel this water routes to the GSA basin pool, NOT a personal credit — the
      ISS-053 invariant — but it is still a real output of this parcel's balance.
    * ``runoff`` (output): an explicit bookkeeping term, always Decimal("0") under
      the "no real hydrology" boundary (CONTEXT). Named, never silently dropped.
    * ``delta_storage`` (output): change in banked credit over the period
      (``banked_af − drawn_af`` netted). The closure term that absorbs the timing
      between banking surplus in a wet month and recovering it later.

    Where no CalculationRun exists for a parcel-month, its ET/precip/recharge/
    storage terms are simply absent (0); surface always comes from the ledger.

    Args:
        parcel: A parcels.Parcel instance.
        reporting_period: Optional ReportingPeriod to scope to.

    Returns:
        dict: ``{"inputs": {surface, precip, gw_recovered},
        "outputs": {et, recharge, runoff, delta_storage}, "residual_af": Decimal,
        "closes": bool}``. ``residual_af = sum(inputs) − sum(outputs)``;
        ``closes`` iff ``abs(residual_af) <= MASS_BALANCE_TOLERANCE``.
    """
    # Ledger-sourced terms, on the SAME billable basis as parcel_balance_breakdown.
    qs = ParcelLedger.objects.filter(parcel=parcel)
    if reporting_period is not None:
        qs = qs.filter(reporting_period=reporting_period)
    billable = billable_ledger(qs)

    gw_recovered = _balance_dict(billable)["usage"]
    surface = abs(
        billable.filter(source_type="surface_diversion").aggregate(
            s=Sum("amount_acre_feet")
        )["s"]
        or Decimal("0")
    )

    # CalculationRun-sourced terms: ET, effective precip, banking, percolation.
    precip = Decimal("0")
    et = Decimal("0")
    recharge = Decimal("0")
    delta_storage = Decimal("0")
    for run in _calculation_runs_for_period(parcel, reporting_period):
        et += run.gross_et_af or Decimal("0")
        precip += run.effective_precip_af or Decimal("0")
        delta_storage += (run.banked_af or Decimal("0")) - (
            run.drawn_af or Decimal("0")
        )
        recharge += _incidental_recharge_af(run.breakdown)

    runoff = Decimal("0")  # bookkeeping boundary: no surface-hydrology model.

    inputs = {"surface": surface, "precip": precip, "gw_recovered": gw_recovered}
    outputs = {
        "et": et,
        "recharge": recharge,
        "runoff": runoff,
        "delta_storage": delta_storage,
    }
    residual = sum(inputs.values()) - sum(outputs.values())
    closes = abs(residual) <= MASS_BALANCE_TOLERANCE
    return {
        "inputs": inputs,
        "outputs": outputs,
        "residual_af": residual,
        "closes": closes,
        # 58-03: presentation classification — "closes" / "realistic" / "large".
        # A small realistic residual (meter pump loss, minor supplement) is normal,
        # not a warning; only a "large" residual (e.g. curtailment shortfall) flags.
        "band_status": residual_band_status(residual, et, closes=closes),
        # True when supplies exceeded measured use (a minor surplus / return flow);
        # False when measured use exceeded supplies (a shortfall). Drives the badge.
        "is_surplus": residual >= 0,
    }


# ---------------------------------------------------------------------------
# Consumptive-use balance read (Phase 57-01, the corrected v1.10 lens)
# ---------------------------------------------------------------------------
#
# The platform was built backwards: it framed surface water as "supply" and
# groundwater as "usage". The corrected v1.10 thesis is that OpenET MEASURES
# consumptive use for any field regardless of source, and that measured use is
# the spine — met by whatever supplies the parcel drew on (surface delivery,
# pumped groundwater, effective precipitation). This read reframes a parcel /
# account / zone in those terms WITHOUT mutating the billable primitive.
#
# It is a NEW read over the SAME rows: the groundwater supply IS the
# ``_balance_dict`` usage term and the surface supply IS the mass balance's
# surface term, so this lens can never disagree with the billable ledger or the
# closing mass balance. ``_balance_dict`` is deliberately left untouched — it
# feeds ``parcel_mass_balance`` (its ``gw_recovered`` term) and the dashboard's
# budget math, and mutating its shape would ripple into both. Presentation
# (57-02 dashboard reframe, 57-03 per-parcel summary + report) chooses the
# framing; the service computes gross ET, net consumptive use, AND the three
# supplies once, here.


def consumptive_use_balance(parcel_ids, reporting_period=None):
    """Estimated consumptive use vs. the supplies that met it, for a parcel set.

    Frames a collection of parcels as **consumptive use (gross ET and net CU)
    against surface + groundwater + precipitation supplies** — the corrected
    v1.10 lens. Every term is sourced from an EXISTING helper so this read can
    never drift from the billable ledger or the mass balance:

    * ``supplies["groundwater"]`` == ``_balance_dict(billable_ledger(qs))["usage"]``
      for the parcels — the pumped/extracted magnitude, identical to the mass
      balance's ``gw_recovered``. Not recomputed from raw rows.
    * ``supplies["surface"]`` == magnitude of billable ``surface_diversion`` rows
      (stored negative; a canal delivery is a supply), the same surface term
      ``parcel_mass_balance`` uses.
    * ``consumptive_use_gross`` / ``consumptive_use_net`` / ``supplies["precip"]``
      summed from each parcel's CalculationRuns over the period (via
      ``_calculation_runs_for_period``, mirroring ``parcel_net_consumptive_use``;
      None-safe → 0).

    ``reporting_period=None`` aggregates across all of each parcel's runs and
    ledger rows.

    Args:
        parcel_ids: iterable of Parcel primary keys.
        reporting_period: optional ReportingPeriod to scope to.

    Returns:
        dict::

            {"consumptive_use_gross": Decimal,   # Σ CalculationRun.gross_et_af
             "consumptive_use_net":   Decimal,   # Σ CalculationRun.net_consumptive_use_af
             "supplies": {"surface": Decimal, "groundwater": Decimal,
                          "precip": Decimal},
             "supply_total": Decimal,            # surface + groundwater + precip
             "net_vs_supply": Decimal}           # supply_total − consumptive_use_gross
    """
    parcel_ids = list(parcel_ids)

    # Ledger-sourced supplies, on the SAME billable basis as the mass balance.
    qs = ParcelLedger.objects.filter(parcel_id__in=parcel_ids)
    if reporting_period is not None:
        qs = qs.filter(reporting_period=reporting_period)
    billable = billable_ledger(qs)

    groundwater = _balance_dict(billable)["usage"]
    surface = abs(
        billable.filter(source_type="surface_diversion").aggregate(
            s=Sum("amount_acre_feet")
        )["s"]
        or Decimal("0")
    )

    # CalculationRun-sourced consumptive-use terms, summed per parcel-month.
    gross = Decimal("0")
    net = Decimal("0")
    precip = Decimal("0")
    for parcel in Parcel.objects.filter(id__in=parcel_ids):
        for run in _calculation_runs_for_period(parcel, reporting_period):
            gross += run.gross_et_af or Decimal("0")
            net += run.net_consumptive_use_af or Decimal("0")
            precip += run.effective_precip_af or Decimal("0")

    supply_total = surface + groundwater + precip
    return {
        "consumptive_use_gross": gross,
        "consumptive_use_net": net,
        "supplies": {
            "surface": surface,
            "groundwater": groundwater,
            "precip": precip,
        },
        "supply_total": supply_total,
        "net_vs_supply": supply_total - gross,
    }


def parcel_consumptive_balance(parcel, reporting_period=None):
    """Consumptive-use balance for ONE parcel (the single-parcel wrapper)."""
    return consumptive_use_balance([parcel.id], reporting_period)


def account_consumptive_balance(water_account, reporting_period=None):
    """Consumptive-use balance across a water account's active parcels.

    Uses the same active-assignment selection as ``account_balance``
    (``removed_date`` is null), so the consumptive lens rolls up the identical
    parcel set the billable balance does.
    """
    parcel_ids = WaterAccountParcel.objects.filter(
        water_account=water_account,
        removed_date__isnull=True,
    ).values_list("parcel_id", flat=True)
    return consumptive_use_balance(list(parcel_ids), reporting_period)


def zone_consumptive_balance(zone, reporting_period=None):
    """Consumptive-use balance across a zone's parcels.

    Uses the same ParcelZone selection as ``zone_balance``.
    """
    parcel_ids = ParcelZone.objects.filter(zone=zone).values_list(
        "parcel_id", flat=True
    )
    return consumptive_use_balance(list(parcel_ids), reporting_period)


# ---------------------------------------------------------------------------
# Multi-year carry-over support (Phase 39-02)
# ---------------------------------------------------------------------------
#
# A "water year" is named by the calendar year it ENDS in (carryover_math
# convention). A ReportingPeriod is labelled by running water_year_of over its
# end_date, so both an annual period (Oct->Sep) and a monthly period land on the
# right year with the same rule. Usage is filtered by effective_date, NOT by the
# reporting_period FK: the calculation engine's gross ET rows carry
# reporting_period=None (38-06), so a FK filter would silently drop them.


def water_year_periods(water_year, anchor_month=10):
    """ReportingPeriods belonging to ``water_year`` (labelled by their end_date).

    The period is assigned to the water year its END month falls in, so a
    standard Oct->Sep period ending 2025-09-30 is WY2025, and a monthly period
    "2024-10" (ending in October) rolls into WY2025. Returns a list ordered by
    start_date; empty if no period covers that year.
    """
    result = []
    for period in ReportingPeriod.objects.order_by("start_date"):
        end = period.end_date
        label = water_year_of(f"{end.year}-{end.month:02d}", anchor_month)
        if label == water_year:
            result.append(period)
    return result


def water_year_usage_by_type(zone, date_start, date_end):
    """Billable usage (positive AF) in a zone over [date_start, date_end], by water-type code.

    Mirrors the dashboard's basis: ``billable_ledger`` is applied so a netted
    ``calculated`` row suppresses its gross ``et_estimate`` twin (no ET
    double-count). Each usage row (negative amount) is attributed to a water type:

      - ``et_estimate`` and ``calculated`` rows are the engine's groundwater-
        attributed usage (a ``calculated`` row is the derived groundwater estimate
        — the ET-minus-supplies residual, written only where a well exists; its
        gross ``et_estimate`` twin is the pre-netting source), so for per-type
        carryover they bucket to "GW" regardless of a possibly-null water_type
        column.
      - every other row uses its own water_type code (meter_reading -> its type,
        surface_diversion -> SW, ...).
      - a non-engine row with no water_type cannot be attributed and is skipped
        (rare; logged at debug). Summed across buckets this equals the zone's
        total billable usage, so per-type carry-over re-aggregates to exactly the
        per-zone number the dashboard shows.

    Returns a dict {water_type_code: Decimal usage (positive)}.
    """
    parcel_ids = ParcelZone.objects.filter(zone=zone).values_list(
        "parcel_id", flat=True
    )
    qs = ParcelLedger.objects.filter(
        parcel_id__in=parcel_ids,
        effective_date__gte=date_start,
        effective_date__lte=date_end,
        amount_acre_feet__lt=0,
    )
    qs = billable_ledger(qs).select_related("water_type")

    buckets = {}
    for row in qs:
        if row.source_type in ("et_estimate", "calculated"):
            code = "GW"
        elif row.water_type_id:
            code = row.water_type.code
        else:
            logger.debug(
                "skipping untyped usage row %s (%s) — cannot attribute to a "
                "water type",
                row.pk,
                row.source_type,
            )
            continue
        buckets[code] = buckets.get(code, Decimal("0")) + (-row.amount_acre_feet)
    return buckets


def zone_carryover(zone, water_year):
    """Signed sum of carried-forward budget for a zone in a water year (AF).

    Positive = net surplus rolled in; negative = net debt borrowed against this
    year. Sums across water types so it folds into the dashboard's per-zone
    "remaining" the same way the per-zone allocation already aggregates types.
    Returns Decimal("0") when no rollover has been run for this zone-year.
    """
    return AllocationCarryover.objects.filter(
        zone=zone, water_year=water_year
    ).aggregate(total=Sum("amount_af"))["total"] or Decimal("0")


def resolve_recovery_horizon(zone, *, agency_default=None):
    """A zone's effective recovery horizon: its own override, else the agency default.

    A surface district is its own Zone (seed_merced_ledgers DISTRICT_ZONE_PREFIX),
    so the per-district choice lives on ``Zone.recovery_horizon``. A blank/null
    override means "inherit the agency-wide ``SiteConfig.default_recovery_horizon``".
    Pass ``agency_default`` to resolve it once for a whole rollover sweep without
    re-querying SiteConfig per zone; omitted, it reads SiteConfig directly (and
    falls back to ``CARRY_FORWARD`` when the platform has no SiteConfig yet, so an
    unconfigured install keeps the historic carry-forward behavior).
    """
    override = getattr(zone, "recovery_horizon", None)
    if override:
        return override
    if agency_default is not None:
        return agency_default
    from core.models import SiteConfig

    cfg = SiteConfig.objects.first()
    return cfg.default_recovery_horizon if cfg else CARRY_FORWARD
