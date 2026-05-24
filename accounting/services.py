"""
Accounting service functions.

Diversion/recharge ledger integration utilities and balance calculations.
"""

from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from geography.models import ParcelZone
from parcels.models import Parcel, ParcelLedger

from accounting.models import ReportingPeriod, WaterAccountParcel


def create_diversion_ledger_entry(diversion_record, parcel):
    """Create a negative ledger entry for a surface water diversion.

    The plan references "the first parcel linked to the water right's holder,"
    but WaterRight.holder_name is a CharField with no FK to Parcel. The caller
    must supply the target parcel explicitly.

    Args:
        diversion_record: A surface.models.DiversionRecord instance.
        parcel: A parcels.models.Parcel instance to post the entry against.

    Returns:
        The created ParcelLedger entry.
    """
    return ParcelLedger.objects.create(
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


def create_recharge_ledger_entries(recharge_event, zone):
    """Create positive ledger entries distributing recharge volume across parcels in a zone.

    The plan references "the recharge site's zone," but RechargeSite has no zone FK.
    The caller must supply the target zone explicitly.

    Args:
        recharge_event: A recharge.models.RechargeEvent instance.
        zone: A geography.models.Zone instance whose parcels receive the credit.

    Returns:
        List of created ParcelLedger entries, or an empty list if the zone has
        no parcels.
    """
    parcel_ids = ParcelZone.objects.filter(zone=zone).values_list(
        "parcel_id", flat=True
    )
    parcels = list(Parcel.objects.filter(pk__in=parcel_ids))

    if not parcels:
        return []

    per_parcel_amount = recharge_event.volume_acre_feet / Decimal(
        str(len(parcels))
    )
    today = timezone.now().date()
    entries = []

    for parcel in parcels:
        entries.append(
            ParcelLedger(
                parcel=parcel,
                transaction_date=today,
                effective_date=recharge_event.start_date,
                amount_acre_feet=per_parcel_amount,
                source_type="recharge",
                description=(
                    f"Recharge from {recharge_event.recharge_site.name}: "
                    f"{recharge_event.volume_acre_feet} AF distributed "
                    f"across {len(parcels)} parcels"
                ),
                reporting_period=None,
                water_type=recharge_event.water_type,
            )
        )

    return ParcelLedger.objects.bulk_create(entries)


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
