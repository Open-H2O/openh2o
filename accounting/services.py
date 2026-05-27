"""
Accounting service functions.

Diversion/recharge ledger integration utilities and balance calculations.
"""

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

from accounting.models import ReportingPeriod, WaterAccountParcel, WaterType

logger = logging.getLogger(__name__)


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


def create_recharge_ledger_entries(recharge_event, zone=None):
    """Create positive ledger entries distributing recharge volume across parcels in a zone.

    Args:
        recharge_event: A recharge.models.RechargeEvent instance.
        zone: Optional Zone instance. If None, falls back to
            recharge_event.recharge_site.zone.

    Returns:
        List of created ParcelLedger entries, or an empty list if the zone has
        no parcels.

    Raises:
        ValueError: If no zone supplied and recharge site has no zone FK set.
    """
    if zone is None:
        zone = recharge_event.recharge_site.zone
        if zone is None:
            raise ValueError(
                f"No zone supplied and recharge site "
                f"'{recharge_event.recharge_site.name}' has no zone set"
            )
    parcel_ids = ParcelZone.objects.filter(zone=zone).values_list(
        "parcel_id", flat=True
    )
    parcels = list(Parcel.objects.filter(pk__in=parcel_ids))

    if not parcels:
        return []

    today = timezone.now().date()
    total_volume = recharge_event.volume_acre_feet
    total_area = sum(p.area_acres or Decimal("0") for p in parcels)
    entries = []

    if total_area == 0:
        # Fallback: equal distribution when no parcels have area data
        logger.warning(
            "All %d parcels in zone '%s' have null/zero area_acres; "
            "distributing recharge equally",
            len(parcels),
            zone.name,
        )
        distributed = Decimal("0")
        for i, parcel in enumerate(parcels):
            if i == len(parcels) - 1:
                amount = total_volume - distributed
            else:
                amount = (total_volume / Decimal(str(len(parcels)))).quantize(
                    Decimal("0.0001")
                )
                distributed += amount
            entries.append(
                ParcelLedger(
                    parcel=parcel,
                    transaction_date=today,
                    effective_date=recharge_event.start_date,
                    amount_acre_feet=amount,
                    source_type="recharge",
                    description=(
                        f"Recharge from {recharge_event.recharge_site.name}: "
                        f"{total_volume} AF distributed equally "
                        f"across {len(parcels)} parcels"
                    ),
                    reporting_period=None,
                    water_type=recharge_event.water_type,
                )
            )
    else:
        # Area-weighted distribution with rounding residual on last entry
        distributed = Decimal("0")
        for i, parcel in enumerate(parcels):
            area = parcel.area_acres or Decimal("0")
            if i == len(parcels) - 1:
                # Last entry gets residual to ensure exact sum
                amount = total_volume - distributed
            else:
                amount = (area / total_area * total_volume).quantize(
                    Decimal("0.0001")
                )
                distributed += amount
            entries.append(
                ParcelLedger(
                    parcel=parcel,
                    transaction_date=today,
                    effective_date=recharge_event.start_date,
                    amount_acre_feet=amount,
                    source_type="recharge",
                    description=(
                        f"Recharge from {recharge_event.recharge_site.name}: "
                        f"{total_volume} AF area-weighted "
                        f"across {len(parcels)} parcels"
                    ),
                    reporting_period=None,
                    water_type=recharge_event.water_type,
                )
            )

    return ParcelLedger.objects.bulk_create(entries)


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
# Balance calculations
# ---------------------------------------------------------------------------


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
    result = qs.aggregate(total=Sum("amount_acre_feet"))
    return result["total"] or Decimal("0")


def _balance_dict(queryset):
    """Compute supply/usage/net from a ParcelLedger queryset.

    Returns:
        dict with keys: total (alias for net), supply, usage, net.
    """
    agg = queryset.aggregate(
        supply=Sum(
            "amount_acre_feet",
            filter=Q(amount_acre_feet__gt=0),
        ),
        usage=Sum(
            "amount_acre_feet",
            filter=Q(amount_acre_feet__lt=0),
        ),
    )
    supply = agg["supply"] or Decimal("0")
    usage_raw = agg["usage"] or Decimal("0")
    usage = abs(usage_raw)
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

    return _balance_dict(qs)


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

    return _balance_dict(qs)
