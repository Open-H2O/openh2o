# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Accounting views.

The dashboards and balance surfaces of the platform. dashboard plus the
account/zone/parcel balance views present estimated consumptive use (ET) against
the reconciled supplies; ledger_list and the CSV upload/template/export views
manage the raw ParcelLedger rows; calculation_run_detail explains a single
engine run step by step. Reporting-period, allocation, and account CRUD live
here too, alongside the admin-gated delivery_settings and methodology_settings
that tune the calculation engine.
"""
from decimal import Decimal

import csv as csv_module
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.csv_safe import safe_row
from datasync import freshness
from datasync.models import MonitoredStation
from accounting.calculation import evaluate_chain
from accounting.forms import (
    AllocationPlanForm,
    CsvUploadForm,
    ParcelLedgerForm,
    ReportingPeriodForm,
    WaterAccountForm,
)
from accounting.models import (
    AllocationPlan,
    CalculationPlan,
    CalculationRun,
    CalculationStep,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterCreditDraw,
    WaterType,
)
from core.access import admin_required
from core.models import SiteConfig
from core.modules import is_enabled
from accounting.services import (
    account_consumptive_balance,
    parcel_consumptive_balance,
    parse_ledger_csv,
    runs_in_period,
    unmet_demand_by_parcel,
    zone_consumptive_balance,
    zone_groundwater_budget,
)
from geography.models import ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger


# Methodology tuning is an administrator's job, gated by the shared, switch-aware
# @admin_required from core.access (ISS-021). It honors the two-tier model and
# deliberately bounces an authenticated non-admin back into the app rather than
# to Django's /admin/ login (which staff_member_required would do).


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def dashboard(request):
    """Water-data overview dashboard with period selector."""
    periods = ReportingPeriod.objects.order_by("-start_date")

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

    account_summaries = []
    zone_summaries = []
    # v1.10 lens: the grand totals roll up ESTIMATED CONSUMPTIVE USE (gross ET) as
    # the demand line and the three SUPPLIES that met it (surface + groundwater +
    # precip). grand_consumptive_use replaces the old grand_usage (which only ever
    # counted groundwater); grand_supply_total replaces grand_supply.
    grand_consumptive_use = Decimal("0")
    grand_supply_total = Decimal("0")
    grand_supply_surface = Decimal("0")
    grand_supply_groundwater = Decimal("0")
    grand_supply_precip = Decimal("0")
    # 143-04 (2026-09-11): the parts of the panel's Consumptive use and Balance
    # figures, as COUNTS over the same population as the totals (active
    # accounts, this period). Coverage is how many of those accounts the
    # estimate reaches and how many calculation runs the sum came from;
    # surplus/deficit is judged ONLY among accounts with an estimate, on the
    # ISS-099 rule the table below already applies: an account with no runs
    # has no balance and is dashed, so it is neither in surplus nor in deficit.
    accounts_with_estimates = 0
    grand_calculation_runs = 0
    accounts_in_surplus = 0
    accounts_in_deficit = 0

    has_allocations = False

    if selected_period is not None:
        has_allocations = AllocationPlan.objects.filter(
            reporting_period=selected_period,
        ).exists()

        # 136-01 (ISS-151, option A, Brent 2026-09-05): the budget columns on
        # both tables are the GROUNDWATER budget, so only groundwater plans
        # count towards an allocation and only groundwater use is subtracted
        # from it. Like with like. Resolved once, by code, because the water
        # types are seeded reference data whose ids differ between deployments
        # (STATE.md records exactly this for another table). A deployment with
        # no groundwater type has no groundwater budget to show: allocations
        # read as absent rather than guessed.
        groundwater_type = WaterType.objects.filter(code__iexact="GW").first()

        # Account summaries — the Budget Summary grand totals below roll up ONLY
        # active accounts (an inactive account is not a live water user), whereas
        # the Zone Details block sums every parcel in each zone regardless of
        # account status. The two describe deliberately different populations, so
        # the dashboard labels this block "Active Water Accounts" to keep the two
        # columns from being read as one (ISS-032 / F-math-03 stream-2).
        active_accounts = WaterAccount.objects.filter(status="active").order_by("account_number")
        for account in active_accounts:
            cu = account_consumptive_balance(account, reporting_period=selected_period)

            if has_allocations and groundwater_type is not None:
                # Allocation: pro-rated by account's parcel count in each zone.
                # Formula: for each zone, allocation * (account_parcels / total_parcels).
                # Uses parcel count (not area) because area data may be incomplete.
                # GROUNDWATER plans only (136-01): six of the eleven demonstration
                # accounts also sit in a surface-water service area, and summing
                # every plan gave MER-ACCT-001 2,901.42 AF of groundwater
                # allocation plus 16,200.00 AF of surface entitlement as one
                # number. Subtracting pumping from that would print a surface
                # entitlement as spare groundwater.
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
                # Budget basis, 136-01 (ISS-151; option A, Brent 2026-09-05): a
                # groundwater budget is spent by GROUNDWATER USE, the metered or
                # calculated pumping the Groundwater column already shows. This
                # REVERSES 57-02, which deliberately subtracted gross ET on the
                # reasoning that "a budget is consumed by measured consumptive
                # use (gross ET), NOT by the old groundwater-only usage". Gross
                # ET is what the crop transpires whatever the water's source,
                # and it FALLS in a drought (every demonstration zone, 2026-09-05
                # measurement), so no basin could ever cross its budget because
                # of one. Pumping rises in a drought; that is what the column is
                # for. An account whose zones carry no groundwater plan has no
                # groundwater budget: absent, not zero, so the template dashes it
                # rather than printing its pumping as an overdraft of nothing.
                if groundwater_plans.exists():
                    remaining = allocation - cu["supplies"]["groundwater"]
                else:
                    allocation = None
                    remaining = None
            else:
                allocation = None
                remaining = None

            account_summaries.append({
                "account": account,
                # ISS-099: a row with no runs behind it has no consumptive-use
                # measurement, and 0.00 would read as one. The template shows a
                # dash instead — for the derived Net and Remaining columns too,
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
            })
            grand_consumptive_use += cu["consumptive_use_gross"]
            grand_supply_total += cu["supply_total"]
            grand_supply_surface += cu["supplies"]["surface"]
            grand_supply_groundwater += cu["supplies"]["groundwater"]
            grand_supply_precip += cu["supplies"]["precip"]
            grand_calculation_runs += cu["calculation_runs"]
            if cu["calculation_runs"] > 0:
                accounts_with_estimates += 1
                if cu["net_vs_supply"] >= 0:
                    accounts_in_surplus += 1
                else:
                    accounts_in_deficit += 1

        # Zone summaries
        for zone in Zone.objects.order_by("name"):
            zcu = zone_consumptive_balance(zone, reporting_period=selected_period)
            # 136-01: groundwater plans only, and a zone that carries none (the
            # five surface service areas hold SW plans only) has no groundwater
            # budget. Its three budget cells are absent rather than zero, so the
            # template renders a dash; a surface allocation minus pumping is not
            # a number anyone manages.
            #
            # 137-02: the three budget cells come from `zone_groundwater_budget`,
            # which the district page's Allocation vs. use table now calls too.
            # They used to be computed here and again over there, and the two
            # answers differed — the district page added no carry-over and spent
            # the groundwater allocation against canal deliveries as well as
            # pumping (ISS-154). One quantity, one computation.
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
                # ISS-099, same rule as the account rows above. Counted per zone
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
                # 142-01 (R-010): the generic, truthful grouping key is not the
                # zone's type but whether a groundwater plan exists for the
                # period -- exactly what dashes the three budget cells above.
                "has_groundwater_budget": zone_allocation is not None,
            })
        # Budgeted zones first, alphabetical within each group, so the template
        # can put one divider row before each group instead of a "no budget"
        # note on five rows. Tests that read these rows select by zone identity,
        # never by position.
        zone_summaries.sort(key=lambda z: (not z["has_groundwater_budget"], z["zone"].name))

    # Bottom-line: supplies minus estimated consumptive use.
    grand_net = grand_supply_total - grand_consumptive_use

    # ISS-099 — "the engine has never run here", told apart from "demand really
    # was zero". Both render 0.00, and the second is a finding while the first is
    # a missing step, so a dashboard that cannot tell them apart reports a basin
    # in perfect balance when nobody has measured it. That is what staging showed
    # for two days after its 2026-07-28 rebuild.
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

    # ISS-157, surface 2: WHICH fields recorded water use that no reported supply
    # explains. The figure has been stored on every calculation run since the
    # engine was written and the field's own page shows it (137-01); this is the
    # district-wide list, which is the half a water master acts on.
    #
    # Stood down when the engine has never run here, on the same rule as the
    # attention strip (ISS-099): the shortfall is an engine OUTPUT, so with no
    # run there is nothing to list — and "no field recorded water use without a
    # reported supply" would then be a claim the database never made.
    unmet_demand_rows = []
    unmet_demand_total = Decimal("0")
    if selected_period is not None and not engine_has_never_run:
        unmet_demand_rows, unmet_demand_total = unmet_demand_by_parcel(
            selected_period
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

    # Active monitoring stations whose data has gone dead, judged against each
    # source's OWN expected cadence (reuses the Monitoring screen's classifier so
    # the two never disagree). "dead" = down; "stale" (amber) is not counted here.
    # Guarded on the module rather than on the row count: `datasync` is
    # schema-resident from Phase 88, so with it switched off the table is still
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

    # 143-04 (2026-09-11): the period card's "Latest data" band -- when water
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

    # Active accounts whose groundwater use has passed their groundwater
    # allocation this period (136-01). Only meaningful once the period has
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
        "grand_consumptive_use": grand_consumptive_use,
        "grand_supply_total": grand_supply_total,
        "grand_supply_surface": grand_supply_surface,
        "grand_supply_groundwater": grand_supply_groundwater,
        "grand_supply_precip": grand_supply_precip,
        "grand_net": grand_net,
        "accounts_with_estimates": accounts_with_estimates,
        "grand_calculation_runs": grand_calculation_runs,
        "accounts_in_surplus": accounts_in_surplus,
        "accounts_in_deficit": accounts_in_deficit,
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


# ---------------------------------------------------------------------------
# Reporting Periods
# ---------------------------------------------------------------------------


@login_required
def periods_list(request):
    """Paginated list of reporting periods with HTMX search."""
    q = request.GET.get("q", "").strip()

    queryset = ReportingPeriod.objects.order_by("-start_date")

    if q:
        queryset = queryset.filter(Q(name__icontains=q))

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
    }

    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_periods_list_results.html", context
        )

    return render(request, "accounting/periods_list.html", context)


@login_required
def period_detail(request, pk):
    """Detail view for a single reporting period."""
    period = get_object_or_404(ReportingPeriod, pk=pk)
    allocations = AllocationPlan.objects.filter(reporting_period=period).select_related(
        "zone", "water_type"
    )
    ledger_count = ParcelLedger.objects.filter(reporting_period=period).count()

    context = {
        "period": period,
        "allocations": allocations,
        "ledger_count": ledger_count,
    }
    return render(request, "accounting/period_detail.html", context)


@login_required
def period_create(request):
    """Create a new reporting period."""
    if request.method == "POST":
        form = ReportingPeriodForm(request.POST)
        if form.is_valid():
            period = form.save()
            return redirect("accounting:period_detail", pk=period.pk)
    else:
        form = ReportingPeriodForm()

    return render(request, "accounting/period_create.html", {"form": form})


@login_required
@require_POST
def period_finalize(request, pk):
    """Toggle finalized status on a reporting period."""
    period = get_object_or_404(ReportingPeriod, pk=pk)

    if period.is_finalized:
        period.is_finalized = False
        period.finalized_at = None
        period.finalized_by = None
    else:
        period.is_finalized = True
        period.finalized_at = timezone.now()
        period.finalized_by = request.user

    period.save()
    return redirect("accounting:period_detail", pk=period.pk)


# ---------------------------------------------------------------------------
# Allocation Plans
# ---------------------------------------------------------------------------


@login_required
def allocations_list(request):
    """Paginated list of allocation plans with HTMX search and period filter."""
    q = request.GET.get("q", "").strip()
    period_id = request.GET.get("period", "").strip()

    queryset = AllocationPlan.objects.select_related(
        "zone", "water_type", "reporting_period"
    ).order_by("-reporting_period__start_date", "name")

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q)
            | Q(zone__name__icontains=q)
            | Q(water_type__name__icontains=q)
        )
    if period_id:
        queryset = queryset.filter(reporting_period_id=period_id)

    # Allocated volume over the WHOLE filtered set (every matching row, not just
    # the visible page) — the dense-table "how much, in total?" answer that makes
    # this a Bucket-2 data table (docs/2.0-UX-PATTERN-SPEC.md). Zone is a
    # ForeignKey, not an M2M, so the queryset has no row duplication and
    # aggregates directly without the ledger's pk-refilter.
    #
    # **Subtotalled by water type, and never summed across them (ISS-156).** This
    # footer printed one number until 2026-09-06: 159,671.46 AF for WY 2025-2026,
    # which was 148,500.00 AF of a surface-water district's diversion entitlement
    # plus 11,171.46 AF of a groundwater sustainability agency's pumping
    # allowance. Different agencies, different law, and nobody manages the sum —
    # so a reader could not act on the one figure the footer gave them. The
    # arithmetic was never wrong; the label was. Any figure that adds rows has to
    # be able to say what makes them addable, and "both are measured in acre-feet"
    # is not an answer.
    allocation_subtotals = list(
        queryset.values("water_type__name")
        .annotate(total=Sum("allocation_acre_feet"), plans=Count("pk"))
        .order_by("water_type__name")
    )

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    periods = ReportingPeriod.objects.order_by("-start_date")

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "allocation_subtotals": allocation_subtotals,
        "q": q,
        "period_id": period_id,
        "periods": periods,
    }

    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_allocations_list_results.html", context
        )

    return render(request, "accounting/allocations_list.html", context)


@login_required
def allocation_create(request):
    """Create a new allocation plan."""
    if request.method == "POST":
        form = AllocationPlanForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounting:allocations_list")
    else:
        form = AllocationPlanForm()

    return render(request, "accounting/allocation_create.html", {"form": form})


# ---------------------------------------------------------------------------
# Water Accounts
# ---------------------------------------------------------------------------


@login_required
def accounts_list(request):
    """Master-detail workspace for water accounts.

    Left pane: the HTMX-searchable account list. Right pane: the selected
    account's detail — its info, balance, and assigned use areas — swapped in
    place when a row is clicked. A ``?selected=<pk>`` query param pre-renders that
    account server-side so a reload or deep link lands on the same workspace view
    (the row click pushes that URL). Bucket 1 (docs/2.0-UX-PATTERN-SPEC.md).

    Returns the ``_accounts_list_results`` partial for an HTMX list refresh
    (search / filter / pagination, which target ``#results``), and the full
    workspace page otherwise.
    """
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = (
        WaterAccount.objects.annotate(parcel_count=Count("wateraccountparcel"))
        .order_by("account_number")
    )

    if q:
        queryset = queryset.filter(
            Q(account_number__icontains=q) | Q(name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Pre-load the selected account (deep link / reload) into the detail pane.
    selected_account = None
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        selected_account = WaterAccount.objects.filter(pk=selected_raw).first()

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": WaterAccount.STATUS_CHOICES,
        "selected_account": selected_account,
    }
    if selected_account is not None:
        context.update(_account_detail_context(selected_account))

    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_accounts_list_results.html", context
        )

    return render(request, "accounting/accounts_list.html", context)


def _account_assignments(account):
    """This account's live use-area assignments, in use-area-number order.

    One definition because THREE views render the same rows — the detail
    context, and the assign / remove handlers that re-render the assignment card
    over HTMX. They each held their own copy of this queryset, so an ordering
    fixed in one place would have left the table re-shuffling itself the moment
    an operator assigned or removed a use area.

    R-040 (143-01): the order used to be ``-added_date``, which is not an order a
    reader can name. Measured 2026-09-08 on the demonstration data: all 18 of
    account 12's assignments carry the same ``added_date``, so the tie broke
    however PostgreSQL liked and two use areas were stranded at the end of both
    tables, reading as an error. They are not a different kind of row — same
    period, same day, same everything.
    """
    return (
        WaterAccountParcel.objects.filter(water_account=account, removed_date__isnull=True)
        .select_related("parcel", "reporting_period")
        .order_by("parcel__parcel_number")
    )


def _account_detail_context(account, period_param=None):
    """Build the per-account detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.

    ``period_param`` selects the reporting period for the balance card:
      * ``None``  → default to the period where this account has real activity
                    (so the page never opens on an empty / allocation-only year).
      * ``""``    → All Time (no period filter; an explicit user choice).
      * ``"<pk>"`` → that specific period.
    """
    assignments = _account_assignments(account)
    acct_parcel_ids = list(assignments.values_list("parcel_id", flat=True))

    # Period selector
    periods = ReportingPeriod.objects.order_by("-start_date")
    selected_period = None

    if period_param:
        selected_period = ReportingPeriod.objects.filter(pk=period_param).first()
    elif period_param is None:
        # No explicit period: land on the period where THIS account actually has
        # activity, so the page never opens on an allocation-only (or empty) year
        # that hides the supply/usage story — the simple-vs-complex contrast is
        # invisible when usage reads 0 everywhere. Prefer the most recent period
        # carrying real transactions (deliveries / extraction / calculated usage)
        # for the account's parcels; fall back to the most recent open period. An
        # explicit ``period_param == ""`` means the user chose All Time, so we
        # leave selected_period None and skip this default.
        activity_period_id = (
            ParcelLedger.objects.filter(
                parcel_id__in=acct_parcel_ids, reporting_period__isnull=False
            )
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
            selected_period = periods.filter(is_finalized=False).first()

    # Account-level balance, in the corrected v1.10 lens: estimated consumptive
    # use (gross ET) against the surface / groundwater / precip supplies that met
    # it (57-02). account_consumptive_balance selects the SAME active assignments
    # account_balance did, so the roll-up partitions identically.
    balance = account_consumptive_balance(account, reporting_period=selected_period)

    # Per-parcel breakdown, same consumptive lens. parcel_consumptive_balance
    # reuses the billable primitive (groundwater supply == _balance_dict usage),
    # so per-parcel rows sum to the account total (57-01 case #5 proves the helper
    # is additive) and the page stays internally consistent. The conjunctive-vs-
    # surface-only story is now VISIBLE: a canal-district parcel shows real
    # consumptive use met entirely by surface; a conjunctive parcel shows surface +
    # groundwater.
    parcel_balances = []
    for assignment in assignments:
        p = assignment.parcel
        pcb = parcel_consumptive_balance(p, reporting_period=selected_period)
        parcel_balances.append({
            "parcel": p,
            "consumptive_use_gross": pcb["consumptive_use_gross"],
            "consumptive_use_net": pcb["consumptive_use_net"],
            "surface": pcb["supplies"]["surface"],
            "groundwater": pcb["supplies"]["groundwater"],
            "precip": pcb["supplies"]["precip"],
            "supply_total": pcb["supply_total"],
            "net_vs_supply": pcb["net_vs_supply"],
            "calculation_runs": pcb["calculation_runs"],
        })

    # The parts of the panel's other two figures (143-03, 2026-09-11): how many
    # of the account's use areas the consumptive-use estimate actually covers,
    # and how the balance splits across them. Counts, not AF: they are read off
    # the per-use-area rows the table below already renders, so they cannot
    # disagree with it.
    use_areas_estimated = sum(1 for pb in parcel_balances if pb["calculation_runs"])
    use_areas_in_surplus = sum(1 for pb in parcel_balances if pb["net_vs_supply"] >= 0)
    use_areas_in_deficit = len(parcel_balances) - use_areas_in_surplus

    # Curtailment narrative (ISS / Phase 52-02): surface the cut as a story, not
    # just lower numbers. An account is "curtailed" when any of its parcels is
    # served by a water right under a curtailment order. Match the active order to
    # the right by priority-date cutoff (the same date the right carries).
    curtailment_orders = []
    is_curtailed = False
    if is_enabled("surface"):
        # Local import: `surface` is an optional module (Phase 87), so this must
        # not run at module scope — importing surface.models with the app
        # uninstalled raises RuntimeError before any useful error prints. The
        # guard matters as well as the import: an account page is `accounting`,
        # which stays enabled, so this block would otherwise run unconditionally.
        from surface.models import CurtailmentOrder, WaterRight

        is_curtailed = WaterRight.objects.filter(
            status="curtailed", water_right_parcels__parcel_id__in=acct_parcel_ids
        ).exists()
        if is_curtailed:
            cutoffs = list(
                WaterRight.objects.filter(
                    status="curtailed",
                    water_right_parcels__parcel_id__in=acct_parcel_ids,
                    priority_date__isnull=False,
                ).values_list("priority_date", flat=True)
            )
            curtailment_orders = list(
                CurtailmentOrder.objects.filter(
                    status="active", priority_date_cutoff__in=cutoffs
                )
            )

    return {
        "account": account,
        "assignments": assignments,
        "balance": balance,
        "parcel_balances": parcel_balances,
        "use_areas_estimated": use_areas_estimated,
        "use_areas_in_surplus": use_areas_in_surplus,
        "use_areas_in_deficit": use_areas_in_deficit,
        "periods": periods,
        "selected_period": selected_period,
        "is_curtailed": is_curtailed,
        "curtailment_orders": curtailment_orders,
    }


@login_required
def account_detail(request, pk):
    """A single water account's detail.

    Three render paths off the one shared context:
      * HX-Request with a ``period`` param → just the ``_account_balances``
        fragment (the in-card period selector swaps this).
      * Any other HX-Request → the ``_account_detail_pane`` body (a row click in
        the accounts workspace swaps this into ``#detail-body``).
      * No HX-Request → the standalone ``account_detail`` page (deep links and
        no-HTMX clients).
    """
    account = get_object_or_404(WaterAccount, pk=pk)
    # "period" present (even empty = All Time) means an explicit choice; absent
    # means "default to the activity period" — _account_detail_context maps the
    # tri-state of None / "" / "<pk>".
    period_param = request.GET.get("period") if "period" in request.GET else None
    context = _account_detail_context(account, period_param=period_param)

    if request.headers.get("HX-Request") and "period" in request.GET:
        return render(
            request, "accounting/partials/_account_balances.html", context
        )
    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_account_detail_pane.html", context
        )
    return render(request, "accounting/account_detail.html", context)


@login_required
def account_create(request):
    """Create a new water account."""
    if request.method == "POST":
        form = WaterAccountForm(request.POST)
        if form.is_valid():
            account = form.save()
            return redirect("accounting:account_detail", pk=account.pk)
    else:
        form = WaterAccountForm()

    return render(request, "accounting/account_create.html", {"form": form})


@login_required
@require_POST
def assign_parcel(request, pk):
    """Assign a parcel to a water account."""
    account = get_object_or_404(WaterAccount, pk=pk)
    parcel_id = request.POST.get("parcel_id")
    parcel = get_object_or_404(Parcel, pk=parcel_id)

    wap, created = WaterAccountParcel.objects.get_or_create(
        water_account=account,
        parcel=parcel,
        reporting_period=None,
    )
    # Re-assigning a previously-removed parcel: remove_parcel soft-deletes by
    # setting removed_date, and the (water_account, parcel, reporting_period)
    # unique key means get_or_create returns that tombstoned row unchanged. Clear
    # the tombstone and re-stamp added_date so the parcel actually reappears in
    # the removed_date__isnull=True list below (otherwise the assign is a silent
    # no-op the operator cannot recover from).
    if not created and wap.removed_date is not None:
        wap.removed_date = None
        wap.added_date = timezone.now().date()
        wap.save(update_fields=["removed_date", "added_date"])

    assignments = _account_assignments(account)

    return render(
        request,
        "accounting/partials/_parcel_assignment.html",
        {"account": account, "assignments": assignments},
    )


@login_required
@require_POST
def remove_parcel(request, pk, wap_pk):
    """Remove a parcel from a water account (soft delete by setting removed_date)."""
    account = get_object_or_404(WaterAccount, pk=pk)
    wap = get_object_or_404(WaterAccountParcel, pk=wap_pk, water_account=account)
    wap.removed_date = timezone.now().date()
    wap.save(update_fields=["removed_date"])

    assignments = _account_assignments(account)

    return render(
        request,
        "accounting/partials/_parcel_assignment.html",
        {"account": account, "assignments": assignments},
    )


@login_required
def parcel_search_for_assignment(request, pk):
    """HTMX endpoint: search for parcels to assign to an account."""
    account = get_object_or_404(WaterAccount, pk=pk)
    q = request.GET.get("q", "").strip()

    results = []
    if q:
        already_assigned = WaterAccountParcel.objects.filter(
            water_account=account, removed_date__isnull=True
        ).values_list("parcel_id", flat=True)

        results = (
            Parcel.objects.filter(
                Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
            )
            .exclude(pk__in=already_assigned)
            .order_by("parcel_number")[:10]
        )

    return render(
        request,
        "accounting/partials/_parcel_search_results.html",
        {"account": account, "results": results, "q": q},
    )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

# Whitelist of sortable columns → ORM fields. An unbounded order_by() fed from a
# GET param is a 500 / injection vector, so we map a small set of safe keys and
# fail closed to the newest-first default for anything else (Phase 63).
LEDGER_SORTABLE = {
    "date": "effective_date",
    "parcel": "parcel__parcel_number",
    "amount": "amount_acre_feet",
    "source": "source_type",
    "water_type": "water_type__name",
}

# Page-size options offered in the ledger toolbar. 100 is the at-scale default
# (replaces the historic hardcoded 50); anything outside the set falls back to 100.
LEDGER_PAGE_SIZES = (25, 100, 500)

#: Which module owns each ledger source type, for the Source FILTER only.
#:
#: ``ParcelLedger.SOURCE_TYPE_CHOICES`` is the full historical vocabulary and has
#: to stay that way. A ``surface_diversion`` row written before the module was
#: switched off is still a real row, ``accounting/ledger_words.py::
#: ledger_row_words`` still names it, and hiding it would be lying about the
#: ledger — the same call 88-03 made for
#: ``/drinking/``'s Well column. What this table gates is the OFFER: on a
#: deployment with no Surface module, a "Surface Diversion" option in the filter
#: invites an operator to filter for a row type this deployment can never
#: produce. Same class as 89-02's guarded enumerations; 90-02 is simply where a
#: gate could first SEE it, because ``/accounting/ledger/`` had no ``_PAGES`` row
#: until then and so had never been read by any assertion.
#:
#: **Declared, never derived.** A source type absent from this table is offered
#: in every configuration, which is the safe direction to fail;
#: ``tests/test_module_template_guards.py::
#: test_ledger_source_owners_still_describe_real_source_types`` fails if a row
#: outlives the choice it names.
LEDGER_SOURCE_TYPE_OWNERS = {
    "surface_diversion": "surface",
    "recharge": "recharge",
}


#: 143-05 (second checkpoint, 2026-09-12): the Source FILTER's option words.
#: The filter still narrows on the stored ``source_type`` value — only the
#: option LABELS changed, to the shortest true words the checkpoint ruling
#: settled on (a filter option is one word or a short phrase, not the fuller
#: "{Water type}, metered" sentence the merged Water column prints per row —
#: that sentence needs the row's own water type, which no single filter
#: option can name). Keep this table in sync with
#: ``accounting/ledger_words.py`` by hand; a value missing here falls back to
#: the model's own label below.
LEDGER_SOURCE_TYPE_LABELS = {
    "meter_reading": "Metered",
    "calculated": "Estimated",
    "et_estimate": "ET estimate",
    "surface_diversion": "Diverted",
    "manual_entry": "Entered by hand",
    "csv_import": "Imported from CSV",
    "adjustment": "Adjusted",
    "allocation": "Allocation",
    "recharge": "Recharge credit",
}


def ledger_source_type_choices():
    """``SOURCE_TYPE_CHOICES`` minus the ones whose module this deployment lacks,
    with the Source filter's own sentence-case words (``LEDGER_SOURCE_TYPE_LABELS``)."""
    return [
        (value, LEDGER_SOURCE_TYPE_LABELS.get(value, label))
        for value, label in ParcelLedger.SOURCE_TYPE_CHOICES
        if value not in LEDGER_SOURCE_TYPE_OWNERS
        or is_enabled(LEDGER_SOURCE_TYPE_OWNERS[value])
    ]


@login_required
def ledger_list(request):
    """Paginated list of ledger entries with HTMX search and filters."""
    q = request.GET.get("q", "").strip()
    # "period" absent entirely (bare landing) is distinct from "period="
    # (the "All Periods" choice, which the HTMX filters always send). Only the
    # former gets an auto-default applied below.
    period_present = "period" in request.GET
    period_id = request.GET.get("period", "").strip()
    source_type = request.GET.get("source_type", "").strip()
    water_type_id = request.GET.get("water_type", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    # "Active Use Areas" preset chip: restrict to ledger rows on a parcel whose
    # status is active (an inactive use area is not a live water user). Any
    # truthy value means "on"; the chip sends "1".
    active_areas = request.GET.get("active_areas", "").strip()

    # Phase 63 navigation params: sort column + direction, Zone facet, page size.
    sort = request.GET.get("sort", "").strip()
    direction = request.GET.get("dir", "desc").strip()
    if direction not in ("asc", "desc"):
        direction = "desc"
    zone_id = request.GET.get("zone", "").strip()
    try:
        page_size = int(request.GET.get("page_size", 100))
    except (TypeError, ValueError):
        page_size = 100
    if page_size not in LEDGER_PAGE_SIZES:
        page_size = 100

    # 143-05 (R-020): the tiebreak orders by use-area number ascending, not
    # just -created_at, so within one date a reader sees a field's meter
    # reading beside its delivery instead of raw seed-insertion order.
    queryset = ParcelLedger.objects.select_related(
        "parcel", "water_type", "reporting_period"
    ).order_by("-effective_date", "parcel__parcel_number", "-created_at")

    periods = ReportingPeriod.objects.order_by("-start_date")
    water_types = WaterType.objects.order_by("name")
    zones = Zone.objects.order_by("name")

    # ISS-022: landing on the ledger with no filters at all should not bury the
    # audit trail. The "How was this calculated?" links only render on
    # calculated rows, so default to the most recent period that HAS calculated
    # rows (falling back to the most recent period with any rows, then to no
    # filter on an empty table). An explicit "All Periods" (period=) is honored.
    # The "current" period: the most recent period with calculated records, then
    # any activity, then simply the most recent period. This single value is both
    # the auto-default target on a bare landing AND the destination of the "This
    # Period" preset chip, so the two always point at the same period.
    calculated_period_id = (
        ParcelLedger.objects.filter(
            source_type="calculated", reporting_period__isnull=False
        )
        .order_by("-reporting_period__start_date")
        .values_list("reporting_period_id", flat=True)
        .first()
    )
    current_period_id = calculated_period_id or (
        ParcelLedger.objects.filter(reporting_period__isnull=False)
        .order_by("-reporting_period__start_date")
        .values_list("reporting_period_id", flat=True)
        .first()
    )
    if current_period_id is None and periods.exists():
        current_period_id = periods.first().pk

    period_auto_defaulted = False
    auto_default_period_name = ""
    auto_default_calculated = calculated_period_id is not None
    no_other_filters = not (
        q or source_type or water_type_id or start_date or end_date or zone_id
        or active_areas
    )
    if not period_present and no_other_filters and current_period_id is not None:
        period_id = str(current_period_id)
        period_auto_defaulted = True
        default_period = next(
            (p for p in periods if p.pk == current_period_id), None
        )
        auto_default_period_name = default_period.name if default_period else ""

    if q:
        queryset = queryset.filter(
            Q(parcel__parcel_number__icontains=q) | Q(description__icontains=q)
        )
    if period_id:
        queryset = queryset.filter(reporting_period_id=period_id)
    if source_type:
        queryset = queryset.filter(source_type=source_type)
    if water_type_id:
        queryset = queryset.filter(water_type_id=water_type_id)
    if start_date:
        queryset = queryset.filter(effective_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(effective_date__lte=end_date)
    if active_areas:
        queryset = queryset.filter(parcel__status="active")
    if zone_id:
        # parcel ↔ zone is many-to-many through ParcelZone, so a parcel in N
        # zones would duplicate its ledger rows — .distinct() collapses them.
        # select_related already pulls the parcel/water_type columns, so ordering
        # by those joined fields stays valid under SELECT DISTINCT.
        queryset = queryset.filter(parcel__parcel_zones__zone_id=zone_id).distinct()

    # Sort: only a whitelisted key re-orders; everything else keeps the
    # newest-first default set on the queryset above. A stable
    # parcel__parcel_number, -created_at tiebreak (143-05) keeps pagination
    # deterministic when the sort field ties, and reproduces the same
    # use-area ordering the default view carries; skipped for the "parcel"
    # key itself, which already sorts by that field.
    if sort in LEDGER_SORTABLE:
        field = LEDGER_SORTABLE[sort]
        prefix = "-" if direction == "desc" else ""
        order_fields = [f"{prefix}{field}"]
        if field != "parcel__parcel_number":
            order_fields.append("parcel__parcel_number")
        order_fields.append("-created_at")
        queryset = queryset.order_by(*order_fields)

    # Two subtotals over the WHOLE filtered set (every matching row, not just the
    # visible page), named by kind and never netted (136-01, ISS-155). Credits
    # are the non-negative rows: allocation and recharge entries, paper or
    # banked water. The water figure is the negative rows: canal deliveries and
    # pumping, stored negative by the ledger's convention and handed to the
    # template as a positive magnitude. The two are not addable, so there is no
    # net: this footer used to print one, and it stated WY 2025-2026 at
    # -1,504.32 AF while the dashboard read the same 1,130 rows as +1,249.07 AF,
    # because the dashboard calls a delivery a supply and this footer called it
    # a debit (DESIGN.md rule 12, review question 3). Re-filter by PK to drop
    # the zone M2M join, whose row duplication (a parcel in N zones) would
    # otherwise multiply amounts in SUM.
    ledger_totals = ParcelLedger.objects.filter(
        pk__in=queryset.values("pk")
    ).aggregate(
        credits=Sum("amount_acre_feet", filter=Q(amount_acre_feet__gte=0)),
        water=Sum("amount_acre_feet", filter=Q(amount_acre_feet__lt=0)),
    )

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # 143-05: the subtitle line names the period and the active filters
    # instead of the template re-deriving them from raw ids. period_name is
    # "All periods" on an explicit ?period= (or no period at all); on a bare
    # auto-defaulted landing the template folds in the separate auto-default
    # sentence instead of using this value. active_filter_labels lists every
    # OTHER facet currently narrowing the set, in filter-bar order, so
    # "filtered: Zone Halvern, Active use areas" always names what changed.
    source_type_choices = ledger_source_type_choices()
    period_name = "All periods"
    if period_id:
        period_name = next(
            (p.name for p in periods if str(p.pk) == period_id), period_name
        )
    active_filter_labels = []
    if q:
        active_filter_labels.append('Search "{}"'.format(q))
    if zone_id:
        zone_name = next((z.name for z in zones if str(z.pk) == zone_id), None)
        if zone_name:
            active_filter_labels.append(f"Zone {zone_name}")
    if source_type:
        source_type_label = next(
            (label for val, label in source_type_choices if val == source_type),
            source_type,
        )
        active_filter_labels.append(source_type_label)
    if water_type_id:
        water_type_name = next(
            (wt.name for wt in water_types if str(wt.pk) == water_type_id), None
        )
        if water_type_name:
            active_filter_labels.append(water_type_name)
    if start_date and end_date:
        active_filter_labels.append(f"{start_date} to {end_date}")
    elif start_date:
        active_filter_labels.append(f"From {start_date}")
    elif end_date:
        active_filter_labels.append(f"Through {end_date}")
    if active_areas:
        active_filter_labels.append("Active use areas")

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "ledger_total_credits": ledger_totals["credits"] or Decimal("0"),
        "ledger_total_water": abs(ledger_totals["water"] or Decimal("0")),
        "q": q,
        "period_id": period_id,
        "period_name": period_name,
        "active_filter_labels": active_filter_labels,
        "source_type": source_type,
        "water_type_id": water_type_id,
        "start_date": start_date,
        "end_date": end_date,
        "periods": periods,
        "water_types": water_types,
        "zones": zones,
        "zone_id": zone_id,
        "sort": sort,
        "direction": direction,
        "page_size": page_size,
        "page_sizes": LEDGER_PAGE_SIZES,
        "source_type_choices": source_type_choices,
        "period_auto_defaulted": period_auto_defaulted,
        "auto_default_period_name": auto_default_period_name,
        "auto_default_calculated": auto_default_calculated,
        "active_areas": active_areas,
        "current_period_id": current_period_id,
        # The page description names "recharge" (copy rule 11's settled
        # sentence); a deployment without the recharge module must not see
        # that noun (tests/droppability/checks.py::
        # test_kept_pages_never_name_a_dropped_module), so the template
        # drops the clause rather than the view rewriting the whole sentence.
        "recharge_enabled": is_enabled("recharge"),
    }

    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_ledger_list_results.html", context
        )

    return render(request, "accounting/ledger_list.html", context)


@login_required
def ledger_create(request):
    """Create a single ParcelLedger entry."""
    if request.method == "POST":
        form = ParcelLedgerForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.created_by = request.user
            entry.save()
            return redirect("accounting:ledger_list")
    else:
        form = ParcelLedgerForm()
        # Pre-fill parcel if provided via query string
        parcel_pk = request.GET.get("parcel", "").strip()
        if parcel_pk:
            try:
                parcel = Parcel.objects.get(pk=parcel_pk)
                form.initial["parcel"] = parcel.pk
            except Parcel.DoesNotExist:
                pass

    return render(request, "accounting/ledger_create.html", {"form": form})


@login_required
def csv_upload(request):
    """Upload a CSV file to bulk-import ledger entries."""
    if request.method == "POST":
        form = CsvUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES["file"]
            period = form.cleaned_data.get("reporting_period")
            dry_run = form.cleaned_data.get("dry_run", False)
            results = parse_ledger_csv(csv_file, reporting_period=period, dry_run=dry_run)
            context = {"form": form, "results": results, "dry_run": dry_run}
            if request.headers.get("HX-Request"):
                return render(request, "accounting/partials/_csv_upload_results.html", context)
            return render(request, "accounting/csv_upload.html", context)
        else:
            context = {"form": form}
            # An HTMX submit targets #upload-results: return just the results
            # partial (carrying the form errors), never the full page — grafting
            # the whole document in would nest a <form> and duplicate IDs.
            if request.headers.get("HX-Request"):
                return render(request, "accounting/partials/_csv_upload_results.html", context)
            return render(request, "accounting/csv_upload.html", context)

    form = CsvUploadForm()
    return render(request, "accounting/csv_upload.html", {"form": form})


@login_required
def csv_template(request):
    """Download a blank CSV template with the required column headers."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ledger_import_template.csv"'
    writer = csv_module.writer(response)
    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow(["DEMONSTRATION DATA — sample values, not an official submission"])
    writer.writerow([
        "parcel_number",
        "effective_date",
        "amount_acre_feet",
        "source_type",
        "water_type_code",
        "description",
        "transaction_date",
    ])
    return response


@login_required
def ledger_export(request):
    """Export filtered ledger entries as CSV."""
    q = request.GET.get("q", "").strip()
    period_id = request.GET.get("period", "").strip()
    source_type = request.GET.get("source_type", "").strip()
    water_type_id = request.GET.get("water_type", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    active_areas = request.GET.get("active_areas", "").strip()

    queryset = ParcelLedger.objects.select_related(
        "parcel", "water_type", "reporting_period"
    ).order_by("-effective_date", "-created_at")

    if q:
        queryset = queryset.filter(
            Q(parcel__parcel_number__icontains=q) | Q(description__icontains=q)
        )
    if period_id:
        queryset = queryset.filter(reporting_period_id=period_id)
    if source_type:
        queryset = queryset.filter(source_type=source_type)
    if water_type_id:
        queryset = queryset.filter(water_type_id=water_type_id)
    if start_date:
        queryset = queryset.filter(effective_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(effective_date__lte=end_date)
    if active_areas:
        queryset = queryset.filter(parcel__status="active")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ledger_export.csv"'
    writer = csv_module.writer(response)
    if getattr(SiteConfig.objects.first(), "demonstration_mode", False):
        writer.writerow(["DEMONSTRATION DATA — sample values, not an official submission"])
    # Round-trip contract: emit EXACTLY the columns the importer reads
    # (import_ledger_csv / parse_ledger_csv), in their order, so a downloaded
    # export re-imports losslessly. Previously this wrote a water_type *name* and a
    # reporting_period the importer ignores, and omitted transaction_date — so the
    # app's own export could not be fed back into its own import.
    writer.writerow([
        "parcel_number", "effective_date", "amount_acre_feet", "source_type",
        "water_type_code", "description", "transaction_date",
    ])
    for entry in queryset.iterator():
        # safe_row neutralizes CSV formula injection in the free-text cells
        # (parcel_number, water_type code, description) without touching the
        # numeric/date cells. See core.csv_safe.
        writer.writerow(safe_row([
            entry.parcel.parcel_number,
            entry.effective_date,
            entry.amount_acre_feet,
            entry.source_type,
            entry.water_type.code if entry.water_type else "",
            entry.description,
            entry.transaction_date,
        ]))
    return response


# ---------------------------------------------------------------------------
# Calculation Run audit trail — "How was this calculated?"
# ---------------------------------------------------------------------------


def _fmt(value, places=4):
    """Round a Decimal-ish breakdown value to `places` for display, defaulting
    to a dash when the value is missing."""
    if value is None or value == "":
        return "—"
    try:
        return f"{Decimal(str(value)):.{places}f}"
    except (ArithmeticError, ValueError, TypeError):
        return str(value)


def _step_detail_summary(step):
    """The salient, human-readable detail for one breakdown step.

    Each primitive stores different keys (et_gross has et_mm/area; the precip step
    has the method + effective_precip_af; clamp_floor has floor/surplus), so we
    surface only the line that explains what THAT step did to the running total.
    """
    detail = step.get("detail", {}) or {}
    step_type = step.get("step_type")

    if step_type == "et_gross":
        return f"{_fmt(detail.get('et_mm'), 2)} mm × {_fmt(detail.get('area_acres'), 2)} ac"
    if step_type == "subtract_effective_precip":
        method = detail.get("method", "usda_scs")
        return f"{method}: −{_fmt(detail.get('effective_precip_af'))} AF effective precip"
    if step_type == "subtract_surface_water":
        return f"−{_fmt(detail.get('surface_water_af'))} AF surface water delivered"
    if step_type == "facility_only_zero":
        return "facility-only — zeroed" if detail.get("facility_only") else "has irrigation — unchanged"
    if step_type == "clamp_floor":
        surplus = Decimal(str(detail.get("surplus_af", "0") or "0"))
        base = f"floor {_fmt(detail.get('floor'), 2)}"
        if surplus > 0:
            return f"{base}; {_fmt(surplus)} AF surplus banked"
        return base
    return ""


@login_required
def calculation_run_detail(request, parcel_id, period):
    """Read-only audit page reconstructing one parcel-month's gross→net waterfall.

    Keyed on the STABLE (parcel, period), not the run's pk: the calculated ledger
    row is delete-recreated every run (its pk churns) and the ledger list iterates
    rows, not runs, so this key lets a ledger link resolve without threading a run
    pk through the list and survives re-runs. Most-recent run wins if more than one
    ever exists; 404 when none.
    """
    parcel = get_object_or_404(Parcel, pk=parcel_id)
    run = (
        CalculationRun.objects.filter(parcel=parcel, period=period)
        .order_by("-created_at")
        .first()
    )
    if run is None:
        raise Http404("No calculation run for this parcel and period.")

    # Classify each row by what it does to the running total so the template can
    # shade the waterfall: the first row is the starting gross figure; after that
    # a smaller output is a reduction (subtraction), a larger output is an
    # addition, an equal output is a pass-through. Lets the gross→net descent be
    # read at a glance instead of decoded from the In/Out columns.
    steps = []
    for i, s in enumerate(run.breakdown):
        inp = s.get("input_af")
        out = s.get("output_af")
        # breakdown is JSON, so the AF figures arrive as strings — compare them
        # numerically (a lexical compare reads "9.81" as greater than "16.89").
        try:
            inp_n, out_n = float(inp), float(out)
        except (TypeError, ValueError):
            inp_n = out_n = None
        if i == 0:
            kind = "start"
        elif inp_n is None or out_n is None or out_n == inp_n:
            kind = "same"
        elif out_n < inp_n:
            kind = "reduce"
        else:
            kind = "add"
        steps.append(
            {
                "label": s.get("label") or s.get("step_type"),
                "input_af": inp,
                "output_af": out,
                "detail_text": _step_detail_summary(s),
                "kind": kind,
            }
        )

    draws = (
        WaterCreditDraw.objects.filter(credit__parcel=parcel, draw_period=period)
        .select_related("credit")
        .order_by("credit__origin_period")
    )

    context = {
        "parcel": parcel,
        "period": period,
        "run": run,
        "steps": steps,
        "draws": draws,
        "has_banking": run.banked_af > 0 or run.drawn_af > 0,
        # 42-01: the methodology fingerprint behind this number. Blank on a
        # pre-42 run, which the template renders as dashes (honest: "ran before
        # provenance was recorded").
        "config_hash": run.config_hash,
        "methodology_plan_name": run.methodology_plan_name,
    }
    return render(request, "accounting/calculation_run_detail.html", context)


# ---------------------------------------------------------------------------
# Delivery Settings — agency-wide efficiency + year-end-unused-water policy (55-03)
# ---------------------------------------------------------------------------
#
# Plans 01-02 put two agency-wide knobs on the SiteConfig singleton
# (default_irrigation_efficiency + default_recovery_horizon). This staff-only
# page is their plain-language home: two questions a non-coder analyst answers
# once for the whole agency. Mirrors methodology_settings' @login_required +
# @admin_required gate.


@login_required
@admin_required
def delivery_settings(request):
    """Staff-only agency delivery-policy page (efficiency + year-end policy).

    GET renders the current SiteConfig values through DeliverySettingsForm
    (efficiency shown as a percent, stored as a Decimal fraction). POST validates
    and writes them back onto the one SiteConfig row, then redirects with a
    success message. SiteConfig is a singleton: we get_or_create the single row so
    a fresh install (no SiteConfig yet) still renders rather than 500-ing, and we
    never create a second row.
    """
    from core.forms import DeliverySettingsForm

    config, _ = SiteConfig.objects.get_or_create(
        defaults={"agency_name": "Agency"}
    )

    if request.method == "POST":
        form = DeliverySettingsForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Delivery settings saved.")
            return redirect("accounting:delivery_settings")
    else:
        form = DeliverySettingsForm(instance=config)

    # The eyebrows count what is rendered, not what the form class declares:
    # `efficiency_percent` belongs to `surface` and is gone when that module is
    # (see DeliverySettingsForm). A hardcoded "of 2" is the 88-03 defect.
    return render(
        request,
        "accounting/delivery_settings.html",
        {"form": form, "settings_total": 2 if form.shows_efficiency else 1},
    )


# ---------------------------------------------------------------------------
# Methodology Settings — the self-serve face of the calculation engine (38-07)
# ---------------------------------------------------------------------------
#
# Staff tune the config-as-data methodology (reorder / enable-disable steps, edit
# each step's knobs and the WaterCredit banking levers) and preview the effect on
# a sample parcel before it touches a real billing run. Every view here is gated
# with BOTH @login_required and @admin_required.


def _latest_calculated_period():
    """The most recent period that actually has a calculation run, as 'YYYY-MM'.

    Used to seed the preview picker so a staff user lands on a period with data
    rather than an empty one. Returns '' when the engine has never run.
    """
    run = CalculationRun.objects.order_by("-period").first()
    return run.period if run else ""


@login_required
@admin_required
def methodology_settings(request):
    """The staff-only methodology settings page (GET).

    Renders the active plan's ordered steps plus the parcel/period picker for the
    live preview. With no active plan we show a friendly empty state rather than
    letting evaluate_chain's ValueError become a 500.
    """
    plan = CalculationPlan.active()
    steps = list(plan.steps.order_by("order")) if plan is not None else []

    context = {
        "plan": plan,
        "steps": steps,
        "parcels": Parcel.objects.order_by("parcel_number")[:200],
        "default_period": _latest_calculated_period(),
    }
    return render(request, "accounting/methodology_settings.html", context)


def _to_float(raw, default):
    """Coerce a posted form value to float, falling back to `default` on blank
    or garbage. The step primitives read these via Decimal(str(...)), so a clean
    float survives the round-trip without binary-noise surprises at these scales."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _to_int_or_none(raw):
    """Coerce expiry_months: blank → None (never expires), else an int month-count.

    Must be None and not "" — banking_math.is_expired / run_calculations treat
    None as 'never' and otherwise call _add_months(period, expiry_months) which
    needs a real integer.
    """
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _render_steps(request, plan):
    """Render the steps-editor partial for an HTMX swap of #methodology-steps."""
    steps = list(plan.steps.order_by("order")) if plan is not None else []
    return render(
        request,
        "accounting/partials/_methodology_steps.html",
        {"plan": plan, "steps": steps},
    )


@login_required
@admin_required
@require_POST
def methodology_step_toggle(request, step_id):
    """Flip one step's enabled flag, then re-render the steps list.

    Any toggle is allowed: the evaluator fails loud on a half-built chain and the
    preview surfaces the effect, so disabling et_gross (yielding 0) is a
    legitimate, visible outcome rather than something to guard against here.
    """
    step = get_object_or_404(CalculationStep, pk=step_id)
    step.enabled = not step.enabled
    step.save(update_fields=["enabled"])
    return _render_steps(request, step.plan)


@login_required
@admin_required
@require_POST
def methodology_step_move(request, step_id, direction):
    """Move a step up or down one slot, then re-render the steps list.

    unique_together(plan, order) forbids two rows sharing an order even mid-swap
    (Postgres checks the unique constraint per statement, not at commit), so we
    never swap two values in place. Instead we compute the desired sequence in
    Python and renumber the WHOLE list 1..N in a transaction — first lifting every
    row out of the 1..N namespace (+10000) so the final write can never collide.
    """
    step = get_object_or_404(CalculationStep, pk=step_id)
    plan = step.plan
    ordered = list(plan.steps.order_by("order"))
    idx = next(i for i, s in enumerate(ordered) if s.pk == step.pk)

    if direction == "up" and idx > 0:
        ordered[idx - 1], ordered[idx] = ordered[idx], ordered[idx - 1]
    elif direction == "down" and idx < len(ordered) - 1:
        ordered[idx + 1], ordered[idx] = ordered[idx], ordered[idx + 1]
    # No-op cleanly at the ends (first can't move up, last can't move down).

    with transaction.atomic():
        for s in ordered:
            s.order = s.order + 10000
            s.save(update_fields=["order"])
        for i, s in enumerate(ordered, start=1):
            s.order = i
            s.save(update_fields=["order"])

    return _render_steps(request, plan)


@login_required
@admin_required
@require_POST
def methodology_step_config(request, step_id):
    """Edit one step's config knobs (+ its audit label), then re-render the list.

    The cardinal rule (38-02 silent-zero trap): MERGE the posted keys into the
    existing config dict, never replace it — so et_gross's model/variable plumbing
    survives a save on a different step. Only the knobs relevant to the step_type
    are touched; the rest of the dict is left exactly as it was.
    """
    step = get_object_or_404(CalculationStep, pk=step_id)
    config = dict(step.config or {})  # MERGE base — preserve every existing key.

    if step.step_type == "subtract_effective_precip":
        method = request.POST.get("method", config.get("method", "usda_scs"))
        if method in ("raw", "fraction", "usda_scs"):
            config["method"] = method
        config["fraction"] = _to_float(
            request.POST.get("fraction"), config.get("fraction", 0.70)
        )
        config["soil_storage_in"] = _to_float(
            request.POST.get("soil_storage_in"), config.get("soil_storage_in", 3.0)
        )
    elif step.step_type == "clamp_floor":
        # The four WaterCredit banking levers.
        config["floor"] = _to_float(request.POST.get("floor"), config.get("floor", 0))
        config["bank"] = "bank" in request.POST
        config["depreciation_rate"] = _to_float(
            request.POST.get("depreciation_rate"), config.get("depreciation_rate", 0)
        )
        config["expiry_months"] = _to_int_or_none(request.POST.get("expiry_months"))
    # et_gross / subtract_surface_water / facility_only_zero: no editable knobs;
    # their config is left untouched (et_gross keeps its model/variable plumbing).

    step.config = config
    label = request.POST.get("label", "").strip()
    if label:
        step.label = label
    step.save(update_fields=["config", "label"])
    return _render_steps(request, step.plan)


@login_required
@admin_required
def methodology_preview(request):
    """Live preview of the CURRENTLY-SAVED methodology on one sample parcel.

    Calls evaluate_chain, which is side-effect-FREE by the 38-04 design contract:
    it reads the active DB plan and writes NOTHING — no ledger row, no
    WaterCredit, no CalculationRun (run_calculations is the only writer). So the
    self-serve loop is: edit a knob → Save → Preview, and the preview reflects the
    saved chain. Degrades to a friendly message (never a 500) on a missing parcel,
    a blank/malformed period, or a no-active-plan state.
    """
    parcel_id = (request.POST.get("parcel_id") or request.GET.get("parcel_id") or "").strip()
    period = (request.POST.get("period") or request.GET.get("period") or "").strip()

    context = {
        "parcel": None,
        "period": period,
        "steps": [],
        "final_af": None,
        "error": None,
    }

    parcel = None
    if parcel_id:
        try:
            parcel = Parcel.objects.filter(pk=parcel_id).first()
        except (ValueError, TypeError):
            parcel = None
    if parcel is None:
        context["error"] = "Pick a parcel to preview."
        return render(request, "accounting/partials/_methodology_preview.html", context)
    context["parcel"] = parcel

    if not period:
        context["error"] = "Enter a period (YYYY-MM) to preview."
        return render(request, "accounting/partials/_methodology_preview.html", context)

    try:
        final_af, breakdown = evaluate_chain(parcel, period)
    except ValueError as exc:
        # No active plan, malformed period ("2024" / "abc-de"), etc. — surface it.
        context["error"] = f"Cannot preview: {exc}"
        return render(request, "accounting/partials/_methodology_preview.html", context)

    context["final_af"] = final_af
    context["steps"] = [
        {
            "label": s.get("label") or s.get("step_type"),
            "input_af": s.get("input_af"),
            "output_af": s.get("output_af"),
            "detail_text": _step_detail_summary(s),
        }
        for s in breakdown
    ]
    return render(request, "accounting/partials/_methodology_preview.html", context)
