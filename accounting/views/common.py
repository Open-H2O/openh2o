# SPDX-License-Identifier: AGPL-3.0-or-later
"""A helper the dashboard and the account list both use: the one row of balance figures for a water account."""
from decimal import Decimal

from django.db.models import Sum

from accounting.models import AllocationPlan, WaterAccountParcel
from accounting.services import account_consumptive_balance
from geography.models import ParcelZone


def _account_summary_row(account, selected_period, has_allocations, groundwater_type):
    """One water account's row in the Active water accounts table: its
    consumptive balance, its supply breakdown, and (only when a groundwater
    budget exists this period) its pro-rated allocation and what remains.

    Shared by the dashboard's account_summaries loop and the accounts list
    (the same table, with a search), so both compute the identical figures
    rather than holding a second copy of the allocation arithmetic. Both callers pass the SAME
    ``has_allocations`` / ``groundwater_type`` (the period-wide facts, not
    per-account) so a row never disagrees with its own page about whether a
    budget exists at all.
    """
    cu = account_consumptive_balance(account, reporting_period=selected_period)

    if has_allocations and groundwater_type is not None:
        # Allocation: pro-rated by account's parcel count in each zone.
        # Formula: for each zone, allocation * (account_parcels / total_parcels).
        # Uses parcel count (not area) because area data may be incomplete.
        # GROUNDWATER plans only: an account can also sit in a surface-water
        # service area, and summing every plan would add its groundwater
        # allocation to its surface entitlement as one number. Subtracting
        # pumping from that would print a surface entitlement as spare
        # groundwater.
        parcel_ids = WaterAccountParcel.objects.filter(
            water_account=account,
            removed_date__isnull=True,
        ).values_list("parcel_id", flat=True)
        zone_ids = ParcelZone.objects.filter(
            parcel_id__in=parcel_ids
        ).values_list("zone_id", flat=True).distinct()
        groundwater_plans = AllocationPlan.objects.filter(
            zone_id__in=zone_ids,
            reporting_period=selected_period,
            water_type=groundwater_type,
        )
        allocation = Decimal("0")
        for zone_id in zone_ids:
            zone_alloc = groundwater_plans.filter(
                zone_id=zone_id,
            ).aggregate(total=Sum("allocation_acre_feet"))["total"] or Decimal("0")
            total_parcels_in_zone = ParcelZone.objects.filter(zone_id=zone_id).count()
            account_parcels_in_zone = ParcelZone.objects.filter(
                zone_id=zone_id, parcel_id__in=parcel_ids
            ).count()
            if total_parcels_in_zone > 0:
                allocation += (
                    zone_alloc
                    * Decimal(account_parcels_in_zone)
                    / Decimal(total_parcels_in_zone)
                )
        # Budget basis: a groundwater budget is spent by GROUNDWATER USE,
        # the metered or calculated pumping the Groundwater column already
        # shows, not by gross ET. Gross ET is what the crop transpires
        # whatever the water's source, and it falls in a drought, so no
        # basin could ever cross its budget because of one. Pumping rises
        # in a drought; that is what the column is for. An account whose zones carry no groundwater plan has no
        # groundwater budget: absent, not zero, so the template dashes it
        # rather than printing its pumping as an overdraft of nothing.
        #
        # Spends `groundwater_charged`, not `supplies["groundwater"]`: the
        # Groundwater column a few lines below shows the CONSUMED figure
        # (what reached the crop); the budget spends a calculated row at
        # its run's stamped EXTRACTED figure instead (an old run with no
        # extraction estimate, or a meter, charges as recorded).
        if groundwater_plans.exists():
            remaining = allocation - cu["groundwater_charged"]
        else:
            allocation = None
            remaining = None
    else:
        allocation = None
        remaining = None

    return {
        "account": account,
        # A row with no runs behind it has no consumptive-use
        # measurement, and 0.00 would read as one. The template shows a
        # dash instead, for the derived Net and Remaining columns too,
        # since both subtract a demand figure that does not exist.
        "has_calculations": cu["calculation_runs"] > 0,
        "consumptive_use_gross": cu["consumptive_use_gross"],
        "consumptive_use_net": cu["consumptive_use_net"],
        "surface": cu["supplies"]["surface"],
        "groundwater": cu["supplies"]["groundwater"],
        "precip": cu["supplies"]["precip"],
        "supply_total": cu["supply_total"],
        "net_vs_supply": cu["net_vs_supply"],
        "allocation": allocation,
        "remaining": remaining,
        "calculation_runs": cu["calculation_runs"],
    }
