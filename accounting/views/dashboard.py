# SPDX-License-Identifier: AGPL-3.0-or-later
"""The accounting dashboard: per-account balance cards, needs-attention list and totals for the selected reporting period."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import HttpRequest
from django.shortcuts import render
from django.utils import timezone

from datasync import freshness
from datasync.models import MonitoredStation
from accounting.models import (
    AllocationPlan,
    CalculationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterAccount,
    WaterType,
)
from core.modules import is_enabled
from accounting.services import (
    balance_state,
    runs_in_period,
    unmet_demand_by_parcel,
    zone_consumptive_balance,
    zone_groundwater_budget,
)
from geography.models import Zone
from parcels.models import Parcel, ParcelLedger
from accounting.views.common import _account_summary_row


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _resolve_selected_period(request: HttpRequest, periods) -> ReportingPeriod | None:
    """The period named by ?period=, else the most recent one with real activity."""
    # Resolve selected period: from query param or default to most recent
    period_id = request.GET.get("period", "").strip()
    selected_period = None
    if period_id:
        try:
            selected_period = ReportingPeriod.objects.get(pk=period_id)
        except ReportingPeriod.DoesNotExist:
            pass
    if selected_period is None and periods.exists():
        # Default to the most recent period that has REAL activity (deliveries /
        # extraction / calculated usage), not the open year that holds only
        # allocations — otherwise the Budget Summary tiles show total usage 0 even
        # though a full year of use sits in the prior period. Mirrors the
        # account_detail default so every overview opens where the data is.
        activity_period_id = (
            ParcelLedger.objects.filter(reporting_period__isnull=False)
            .exclude(source_type="allocation")
            .order_by("-reporting_period__start_date")
            .values_list("reporting_period_id", flat=True)
            .first()
        )
        if activity_period_id:
            selected_period = ReportingPeriod.objects.filter(
                pk=activity_period_id
            ).first()
        else:
            selected_period = periods.first()
    return selected_period


def _account_rollup(
    selected_period: ReportingPeriod, has_allocations: bool, groundwater_type: WaterType | None
) -> dict[str, object]:
    """The active-account rows and the grand totals and counts rolled up from them."""
    account_summaries = []
    # v1.10 lens: the grand totals roll up ESTIMATED CONSUMPTIVE USE (gross ET) as
    # the demand line and the three SUPPLIES that met it (surface + groundwater +
    # precip). grand_consumptive_use replaces the old grand_usage (which only ever
    # counted groundwater); grand_supply_total replaces grand_supply.
    grand_consumptive_use = Decimal("0")
    grand_supply_total = Decimal("0")
    grand_supply_surface = Decimal("0")
    grand_supply_groundwater = Decimal("0")
    grand_supply_precip = Decimal("0")
    # The parts of the panel's Consumptive use and Balance
    # figures, as COUNTS over the same population as the totals (active
    # accounts, this period). Coverage is how many of those accounts the
    # estimate reaches and how many calculation runs the sum came from;
    # surplus/deficit is judged ONLY among accounts with an estimate, on the
    # rule the table below already applies: an account with no runs
    # has no balance and is dashed, so it is neither in surplus nor in deficit.
    accounts_with_estimates = 0
    grand_calculation_runs = 0
    accounts_in_surplus = 0
    accounts_in_deficit = 0
    accounts_balanced = 0

    # Account summaries — the Budget Summary grand totals below roll up ONLY
    # active accounts (an inactive account is not a live water user), whereas
    # the Zone Details block sums every parcel in each zone regardless of
    # account status. The two describe deliberately different populations, so
    # the dashboard labels this block "Active Water Accounts" to keep the two
    # columns from being read as one.
    active_accounts = WaterAccount.objects.filter(status="active").order_by("account_number")
    for account in active_accounts:
        row = _account_summary_row(
            account, selected_period, has_allocations, groundwater_type
        )
        account_summaries.append(row)
        grand_consumptive_use += row["consumptive_use_gross"]
        grand_supply_total += row["supply_total"]
        grand_supply_surface += row["surface"]
        grand_supply_groundwater += row["groundwater"]
        grand_supply_precip += row["precip"]
        grand_calculation_runs += row["calculation_runs"]
        if row["calculation_runs"] > 0:
            accounts_with_estimates += 1
            # Judged on the two decimals the page prints.
            state = balance_state(row["net_vs_supply"])
            if state == "surplus":
                accounts_in_surplus += 1
            elif state == "deficit":
                accounts_in_deficit += 1
            else:
                accounts_balanced += 1
    return {
        "account_summaries": account_summaries,
        "grand_consumptive_use": grand_consumptive_use,
        "grand_supply_total": grand_supply_total,
        "grand_supply_surface": grand_supply_surface,
        "grand_supply_groundwater": grand_supply_groundwater,
        "grand_supply_precip": grand_supply_precip,
        "accounts_with_estimates": accounts_with_estimates,
        "grand_calculation_runs": grand_calculation_runs,
        "accounts_in_surplus": accounts_in_surplus,
        "accounts_in_deficit": accounts_in_deficit,
        "accounts_balanced": accounts_balanced,
    }


def _zone_summary_rows(selected_period: ReportingPeriod, has_allocations: bool) -> list[dict[str, object]]:
    """One row per zone with its consumptive-use figures and groundwater budget cells."""
    zone_summaries = []
    for zone in Zone.objects.order_by("name"):
        zcu = zone_consumptive_balance(zone, reporting_period=selected_period)
        # Groundwater plans only, and a zone that carries none (a surface
        # service area holds SW plans only) has no groundwater
        # budget. Its three budget cells are absent rather than zero, so the
        # template renders a dash; a surface allocation minus pumping is not
        # a number anyone manages.
        #
        # The three budget cells come from `zone_groundwater_budget`,
        # which the district page's Allocation vs. use table calls too, so a
        # budget computed twice cannot give two answers (carry-over added or
        # not, canal deliveries spent against it or not). One quantity, one
        # computation.
        budget = zone_groundwater_budget(zone, selected_period)
        zone_allocation = budget["allocation"] if has_allocations else None
        if zone_allocation is not None:
            zone_carryover_af = budget["carryover"]
            zone_remaining = budget["remaining"]
        else:
            zone_carryover_af = None
            zone_remaining = None
        zone_summaries.append({
            "zone": zone,
            # Same rule as the account rows above. Counted per zone
            # rather than inherited from the deployment-wide flag: a zone
            # whose parcels were all added after the last engine run has no
            # measurement of its own even where the rest of the basin does.
            "has_calculations": zcu["calculation_runs"] > 0,
            "consumptive_use_gross": zcu["consumptive_use_gross"],
            "consumptive_use_net": zcu["consumptive_use_net"],
            "surface": zcu["supplies"]["surface"],
            "groundwater": zcu["supplies"]["groundwater"],
            "precip": zcu["supplies"]["precip"],
            "supply_total": zcu["supply_total"],
            "net_vs_supply": zcu["net_vs_supply"],
            "allocation": zone_allocation,
            "carryover": zone_carryover_af,
            "remaining": zone_remaining,
            # The generic, truthful grouping key is not the
            # zone's type but whether a groundwater plan exists for the
            # period -- exactly what dashes the three budget cells above.
            "has_groundwater_budget": zone_allocation is not None,
        })
    # Budgeted zones first, alphabetical within each group, so the template
    # can put one divider row before each group instead of a "no budget"
    # note on five rows. Tests that read these rows select by zone identity,
    # never by position.
    zone_summaries.sort(key=lambda z: (not z["has_groundwater_budget"], z["zone"].name))
    return zone_summaries


def _engine_run_status(selected_period: ReportingPeriod | None) -> tuple[bool, bool]:
    """Whether the engine has never run for the period, and whether an active plan exists."""
    # "The engine has never run here", told apart from "demand really
    # was zero". Both render 0.00, and the second is a finding while the first is
    # a missing step, so a dashboard that cannot tell them apart reports a basin
    # in perfect balance when nobody has measured it.
    #
    # Asked over EVERY parcel's runs, deliberately NOT by summing the per-row
    # `calculation_runs` above: those rows cover only parcels attached to an
    # ACTIVE water account, so a deployment whose accounts are all inactive — or
    # not yet created, which is every deployment on day one — would look
    # calculated when nothing had run. `runs_in_period` is the single membership
    # rule; asking any other way is how this codebase previously ended up with
    # three answers to one question.
    #
    # Skipped entirely with no period selected: the template renders the "create
    # your first reporting period" empty state there and never reaches the
    # banner, and `runs_in_period(qs, None)` is a no-op that would count every
    # run ever — an answer to a question nobody asked.
    engine_has_never_run = False
    has_calculation_plan = False
    if selected_period is not None:
        # Guarded on parcels existing: with no parcels this is a brand-new
        # instance whose empty tables are honest, and telling that operator to
        # run the calculation engine would send them at the wrong step entirely.
        engine_has_never_run = (
            Parcel.objects.exists()
            and not runs_in_period(
                CalculationRun.objects.all(), selected_period
            ).exists()
        )

        # Named separately because it is the FIRST thing that has to be true, and
        # the failure is otherwise cryptic: with no active plan
        # `run_calculations` does not run and produce nothing, it hard-fails with
        # `ValueError: no active CalculationPlan`. An operator told only to run
        # the engine walks straight into that.
        has_calculation_plan = CalculationPlan.active() is not None
    return engine_has_never_run, has_calculation_plan


def _station_counts(attention_now: datetime) -> tuple[int, int]:
    """Active monitoring stations and how many of them are dead, as (down, active)."""
    # Active monitoring stations whose data has gone dead, judged against each
    # source's OWN expected cadence (reuses the Monitoring screen's classifier so
    # the two never disagree). "dead" = down; "stale" (amber) is not counted here.
    # Guarded on the module rather than on the row count: `datasync` is
    # schema-resident, so with it switched off the table is still
    # there and still answers — with a zero that reads as "every station is
    # healthy" instead of "this deployment has no stations". `stations_down`
    # stays a local zero so `attention_total` still adds up, but the CONTEXT KEY
    # is only set inside the guard, so the pill is absent rather than quietly
    # never true.
    stations_down = 0
    stations_active = 0
    if is_enabled("datasync"):
        stations_active = MonitoredStation.objects.filter(is_active=True).count()
        stations_down = sum(
            1
            for s in MonitoredStation.objects.filter(is_active=True).select_related(
                "data_source"
            )
            if freshness.classify_freshness(
                s.data_source.code, s.last_data_at, attention_now
            )
            == "dead"
        )
    return stations_down, stations_active


def _latest_data_dates(selected_period: ReportingPeriod | None) -> tuple[date | None, datetime | None]:
    """When water was last recorded and last estimated for the period, as (ledger date, run time)."""
    # The period card's "Latest data" band -- when water
    # was last recorded and when it was last estimated, for THIS period. Both
    # scoped the way the figures above are: the ledger by reporting period,
    # the runs by `runs_in_period`, the one membership rule. None reads as
    # "none yet" / "not calculated" in the template, never as a date.
    last_ledger_date = None
    last_run_at = None
    if selected_period is not None:
        last_ledger_date = ParcelLedger.objects.filter(
            reporting_period=selected_period
        ).aggregate(d=Max("transaction_date"))["d"]
        last_run_at = runs_in_period(
            CalculationRun.objects.all(), selected_period
        ).aggregate(d=Max("created_at"))["d"]
    return last_ledger_date, last_run_at


def _period_budget_sections(
    selected_period: ReportingPeriod | None,
) -> tuple[bool, dict[str, object], list, list[dict[str, object]]]:
    """Whether the period has allocations, the grand totals, the account rows and the zone rows."""
    account_summaries: list = []
    zone_summaries: list[dict[str, object]] = []
    has_allocations = False
    totals: dict[str, object] = {
        "grand_consumptive_use": Decimal("0"),
        "grand_supply_total": Decimal("0"),
        "grand_supply_surface": Decimal("0"),
        "grand_supply_groundwater": Decimal("0"),
        "grand_supply_precip": Decimal("0"),
        "accounts_with_estimates": 0,
        "grand_calculation_runs": 0,
        "accounts_in_surplus": 0,
        "accounts_in_deficit": 0,
        "accounts_balanced": 0,
    }
    if selected_period is not None:
        has_allocations = AllocationPlan.objects.filter(
            reporting_period=selected_period,
        ).exists()

        # The budget columns on
        # both tables are the GROUNDWATER budget, so only groundwater plans
        # count towards an allocation and only groundwater use is subtracted
        # from it. Like with like. Resolved once, by code, because the water
        # types are seeded reference data whose ids differ between deployments
        # (for example, the ids of another seeded table differ too). A deployment with
        # no groundwater type has no groundwater budget to show: allocations
        # read as absent rather than guessed.
        groundwater_type = WaterType.objects.filter(code__iexact="GW").first()

        totals = _account_rollup(selected_period, has_allocations, groundwater_type)
        account_summaries = totals.pop("account_summaries")  # type: ignore[assignment]
        zone_summaries = _zone_summary_rows(selected_period, has_allocations)

    return has_allocations, totals, account_summaries, zone_summaries


def _unmet_demand(
    selected_period: ReportingPeriod | None, engine_has_never_run: bool
) -> tuple[list, Decimal]:
    """The fields that recorded water use no reported supply explains, and their total."""
    # WHICH fields recorded water use that no reported supply
    # explains. The figure is stored on every calculation run and the
    # field's own page shows it; this is the
    # district-wide list, which is the half a water master acts on.
    #
    # Stood down when the engine has never run here, on the same rule as the
    # attention strip: the shortfall is an engine OUTPUT, so with no
    # run there is nothing to list — and "no field recorded water use without a
    # reported supply" would then be a claim the database never made.
    unmet_demand_rows = []
    unmet_demand_total = Decimal("0")
    if selected_period is not None and not engine_has_never_run:
        unmet_demand_rows, unmet_demand_total = unmet_demand_by_parcel(
            selected_period
        )
    return unmet_demand_rows, unmet_demand_total


@login_required
def dashboard(request):
    """Water-data overview dashboard with period selector."""
    periods = ReportingPeriod.objects.order_by("-start_date")
    selected_period = _resolve_selected_period(request, periods)

    has_allocations, totals, account_summaries, zone_summaries = _period_budget_sections(
        selected_period
    )

    # Bottom-line: supplies minus estimated consumptive use.
    grand_net = totals["grand_supply_total"] - totals["grand_consumptive_use"]

    engine_has_never_run, has_calculation_plan = _engine_run_status(selected_period)

    unmet_demand_rows, unmet_demand_total = _unmet_demand(
        selected_period, engine_has_never_run
    )
    unmet_demand_count = len(unmet_demand_rows)

    # "What needs attention" strip (E1): three exception counts a returning admin
    # should see at a glance, each derived from data the dashboard already has.
    # Lives inside the HTMX-swapped content so the period-dependent over-budget
    # count refreshes when the period selector changes.
    attention_now = timezone.now()

    # Periods past their end date that still aren't finalized — filings in waiting.
    periods_to_close = ReportingPeriod.objects.filter(
        is_finalized=False, end_date__lt=attention_now.date()
    ).count()

    stations_down, stations_active = _station_counts(attention_now)
    last_ledger_date, last_run_at = _latest_data_dates(selected_period)

    # Active accounts whose groundwater use has passed their groundwater
    # allocation this period. Only meaningful once the period has
    # groundwater allocations; remaining is None otherwise, so those accounts
    # never count.
    accounts_over_budget = sum(
        1
        for s in account_summaries
        if s["remaining"] is not None and s["remaining"] < 0
    )

    attention_total = (
        periods_to_close
        + stations_down
        + accounts_over_budget
        + unmet_demand_count
    )

    context = {
        "periods": periods,
        "selected_period": selected_period,
        "account_summaries": account_summaries,
        "zone_summaries": zone_summaries,
        **totals,
        "grand_net": grand_net,
        "engine_has_never_run": engine_has_never_run,
        "has_calculation_plan": has_calculation_plan,
        "has_allocations": has_allocations,
        "periods_to_close": periods_to_close,
        "accounts_over_budget": accounts_over_budget,
        "unmet_demand_rows": unmet_demand_rows,
        "unmet_demand_total": unmet_demand_total,
        "unmet_demand_count": unmet_demand_count,
        "attention_total": attention_total,
        "last_ledger_date": last_ledger_date,
        "last_run_at": last_run_at,
    }
    if is_enabled("datasync"):
        context["stations_down"] = stations_down
        context["stations_active"] = stations_active
        context["stations_reporting"] = stations_active - stations_down

    if request.headers.get("HX-Request"):
        return render(request, "accounting/partials/_dashboard_content.html", context)

    return render(request, "accounting/dashboard.html", context)
