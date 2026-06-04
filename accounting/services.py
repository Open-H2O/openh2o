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

from accounting.carryover_math import water_year_of
from accounting.models import (
    AllocationCarryover,
    AllocationPlan,
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
            amount_acre_feet=-abs(diversion_record.volume_acre_feet),
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
        # Distribute by fraction with rounding residual on last entry
        total_volume = abs(diversion_record.volume_acre_feet)
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
                amount_acre_feet=-abs(diversion_record.volume_acre_feet),
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
    """Parse a CSV file and create ledger entries.

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
                     parcel_number, effective_date, amount, source_type).
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

    valid_source_types = {choice[0] for choice in ParcelLedger.SOURCE_TYPE_CHOICES}
    parcel_cache: dict = {}
    water_type_cache: dict = {}

    required_columns = {"parcel_number", "effective_date", "amount_acre_feet", "source_type"}

    errors = []
    entries_to_create = []
    preview = []

    reader = csv.DictReader(text_file)

    if reader.fieldnames is None:
        return {
            "created_count": 0,
            "error_count": 1,
            "errors": [{"line": 1, "messages": ["CSV file appears empty or has no headers."]}],
            "preview": [],
        }

    actual_columns = {c.strip().lower() for c in reader.fieldnames}
    missing = required_columns - actual_columns
    if missing:
        return {
            "created_count": 0,
            "error_count": 1,
            "errors": [{"line": 1, "messages": [f"Missing required columns: {', '.join(sorted(missing))}"]}],
            "preview": [],
        }

    for line_num, row in enumerate(reader, start=2):
        row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        row_errors = []
        parcel_number = row.get("parcel_number", "")
        effective_date_raw = row.get("effective_date", "")
        amount_raw = row.get("amount_acre_feet", "")
        source_type = row.get("source_type", "")
        water_type_code = row.get("water_type_code", "")
        description = row.get("description", "")
        transaction_date_raw = row.get("transaction_date", "")

        # Validate parcel
        parcel = None
        if not parcel_number:
            row_errors.append("missing parcel_number")
        else:
            if parcel_number not in parcel_cache:
                try:
                    parcel_cache[parcel_number] = Parcel.objects.get(parcel_number=parcel_number)
                except Parcel.DoesNotExist:
                    parcel_cache[parcel_number] = None
            parcel = parcel_cache[parcel_number]
            if parcel is None:
                row_errors.append(f"parcel not found: {parcel_number}")

        # Validate amount
        amount = None
        if not amount_raw:
            row_errors.append("missing amount_acre_feet")
        else:
            try:
                amount = Decimal(amount_raw)
            except InvalidOperation:
                row_errors.append(f"invalid amount: {amount_raw}")

        # Validate effective_date
        effective_date = None
        if not effective_date_raw:
            row_errors.append("missing effective_date")
        else:
            effective_date = _parse_date(effective_date_raw)
            if effective_date is None:
                row_errors.append(f"invalid effective_date: {effective_date_raw}")

        # Validate source_type
        if not source_type:
            row_errors.append("missing source_type")
        elif source_type not in valid_source_types:
            row_errors.append(f"invalid source_type: {source_type}")

        # Validate sign matches source_type: usage types must be <= 0
        USAGE_SOURCE_TYPES = {"meter_reading", "et_estimate", "surface_diversion"}
        if source_type in USAGE_SOURCE_TYPES and amount is not None and amount > 0:
            row_errors.append(
                f"positive amount ({amount}) not allowed for usage source_type "
                f"'{source_type}' — usage entries must be negative or zero"
            )

        # Validate optional water_type_code
        water_type = None
        if water_type_code:
            if water_type_code not in water_type_cache:
                try:
                    water_type_cache[water_type_code] = WaterType.objects.get(code=water_type_code)
                except WaterType.DoesNotExist:
                    water_type_cache[water_type_code] = None
            water_type = water_type_cache[water_type_code]
            if water_type is None:
                row_errors.append(f"water_type not found: {water_type_code}")

        # Parse optional transaction_date
        transaction_date = None
        if transaction_date_raw:
            transaction_date = _parse_date(transaction_date_raw)
            if transaction_date is None:
                row_errors.append(f"invalid transaction_date: {transaction_date_raw}")

        if row_errors:
            errors.append({"line": line_num, "messages": row_errors})
            continue

        if transaction_date is None:
            transaction_date = effective_date

        entries_to_create.append(
            ParcelLedger(
                parcel=parcel,
                transaction_date=transaction_date,
                effective_date=effective_date,
                amount_acre_feet=amount,
                water_type=water_type,
                source_type=source_type,
                description=description,
                reporting_period=reporting_period,
            )
        )

        if len(preview) < 5:
            preview.append({
                "parcel_number": parcel_number,
                "effective_date": effective_date,
                "amount": amount,
                "source_type": source_type,
            })

    created_count = 0
    if not dry_run and entries_to_create:
        batch_size = 500
        with transaction.atomic():
            for i in range(0, len(entries_to_create), batch_size):
                batch = entries_to_create[i: i + batch_size]
                ParcelLedger.objects.bulk_create(batch)
        created_count = len(entries_to_create)
    else:
        created_count = len(entries_to_create)

    return {
        "created_count": created_count,
        "error_count": len(errors),
        "errors": errors,
        "preview": preview,
    }


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
    stored negative, so summing every row double-counts ET. This applies the
    settled prefer-calculated-else-et_estimate rule:

      - Where a ``calculated`` row exists for a ``(parcel_id, effective_date)``,
        the matching ``et_estimate`` row is suppressed (the netted row bills).
      - Where no ``calculated`` row exists, the ``et_estimate`` row stands in so
        no parcel-month silently drops to zero (the fallback).
      - Every other row (meter_reading, surface_diversion, recharge, the
        calculated rows themselves) passes through unchanged.

    The join key is ``(parcel_id, effective_date)``: both ET-family rows are
    dated to the first of the month, so the pair matches exactly. The
    suppression is source-type-driven (not reporting-period-driven), so it holds
    whether or not a period filter has already been applied to ``queryset``.

    Empty queryset → empty.
    """
    calculated_keys = list(
        queryset.filter(source_type="calculated").values_list(
            "parcel_id", "effective_date"
        )
    )
    if not calculated_keys:
        return queryset

    # OR of EXACT (parcel_id, effective_date) pairs. A flat
    # ``parcel_id__in + effective_date__in`` would over-exclude the cross-product
    # (any calculated parcel × any calculated date), wrongly suppressing an
    # et_estimate row that has no calculated counterpart of its own. District
    # scale is monthly and small, so the per-pair OR is cheap and correct.
    suppression = Q()
    for parcel_id, effective_date in calculated_keys:
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

      - ``et_estimate`` and ``calculated`` rows are groundwater extraction by
        definition (the platform derives groundwater from satellite ET), so they
        bucket to "GW" regardless of a possibly-null water_type column.
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
