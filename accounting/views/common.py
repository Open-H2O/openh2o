# SPDX-License-Identifier: AGPL-3.0-or-later
"""A helper the dashboard and the account list both use: the one row of balance figures for a water account."""
from accounting.services import account_consumptive_balance, account_groundwater_budget


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

    if has_allocations and groundwater_type is not None and selected_period is not None:
        # One computation of the account's groundwater budget, shared with the
        # account page: its acre share of each zone's groundwater allocation
        # (groundwater plans only: an account can also sit in a surface-water
        # service area, and summing every plan would add its groundwater
        # allocation to its surface entitlement as one number), plus its own
        # credit rows (carried forward, managed recharge, canal seepage), less
        # the groundwater it was charged: the metered or calculated pumping, a
        # calculated row at its run's EXTRACTED figure. An account whose zones
        # carry no groundwater plan has no groundwater budget: absent, not
        # zero, so the template dashes it.
        budget = account_groundwater_budget(account, selected_period)
        allocation = budget["allocation"]
        remaining = budget["remaining"]
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
        "water_not_consumed": cu["water_not_consumed"],
        "net_vs_supply": cu["net_vs_supply"],
        "allocation": allocation,
        "remaining": remaining,
        "calculation_runs": cu["calculation_runs"],
    }
