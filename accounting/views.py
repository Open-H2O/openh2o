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
from django.db.models import Count, Q, Sum
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
from accounting.carryover_math import available_with_carryover, water_year_of
from core.access import admin_required
from core.models import SiteConfig
from core.modules import is_enabled
from accounting.services import (
    account_consumptive_balance,
    parcel_consumptive_balance,
    parse_ledger_csv,
    zone_carryover,
    zone_consumptive_balance,
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

    has_allocations = False

    if selected_period is not None:
        has_allocations = AllocationPlan.objects.filter(
            reporting_period=selected_period,
        ).exists()

        # Account summaries — the Budget Summary grand totals below roll up ONLY
        # active accounts (an inactive account is not a live water user), whereas
        # the Zone Details block sums every parcel in each zone regardless of
        # account status. The two describe deliberately different populations, so
        # the dashboard labels this block "Active Water Accounts" to keep the two
        # columns from being read as one (ISS-032 / F-math-03 stream-2).
        active_accounts = WaterAccount.objects.filter(status="active").order_by("account_number")
        for account in active_accounts:
            cu = account_consumptive_balance(account, reporting_period=selected_period)

            if has_allocations:
                # Allocation: pro-rated by account's parcel count in each zone.
                # Formula: for each zone, allocation * (account_parcels / total_parcels).
                # Uses parcel count (not area) because area data may be incomplete.
                parcel_ids = WaterAccountParcel.objects.filter(
                    water_account=account,
                    removed_date__isnull=True,
                ).values_list("parcel_id", flat=True)
                zone_ids = ParcelZone.objects.filter(
                    parcel_id__in=parcel_ids
                ).values_list("zone_id", flat=True).distinct()
                allocation = Decimal("0")
                for zone_id in zone_ids:
                    zone_alloc = AllocationPlan.objects.filter(
                        zone_id=zone_id,
                        reporting_period=selected_period,
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
                # Budget basis (57-02): a budget is consumed by measured
                # consumptive use (gross ET), NOT by the old groundwater-only
                # "usage". net-of-rainfall is a secondary display, not the budget
                # basis. Allocation/carryover logic itself is unchanged — only the
                # quantity subtracted.
                remaining = allocation - cu["consumptive_use_gross"]
            else:
                allocation = None
                remaining = None

            account_summaries.append({
                "account": account,
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

        # Water year of the selected period, so we can pull the carry-over that
        # rolled INTO it from the prior year (labelled by the year it ends in,
        # default Oct-anchor — matches carryover_math + rollover_allocations).
        sel_end = selected_period.end_date
        selected_water_year = water_year_of(f"{sel_end.year}-{sel_end.month:02d}")

        # Zone summaries
        for zone in Zone.objects.order_by("name"):
            zcu = zone_consumptive_balance(zone, reporting_period=selected_period)
            if has_allocations:
                zone_allocation = AllocationPlan.objects.filter(
                    zone=zone,
                    reporting_period=selected_period,
                ).aggregate(total=Sum("allocation_acre_feet"))["total"] or Decimal("0")
                # Prior-year carry-over (signed): + surplus rolled in, − debt
                # borrowed against this year. available_with_carryover applies the
                # surplus-depreciates / debt-doesn't rule centrally; periods
                # elapsed = 0 because this is the opening balance for the very
                # next year (no aging yet), so it is a plain signed adjustment.
                zone_carryover_af = zone_carryover(zone, selected_water_year)
                zone_available = available_with_carryover(
                    zone_allocation, zone_carryover_af
                )
                # Same allocation basis as accounts: subtract estimated consumptive use.
                zone_remaining = zone_available - zcu["consumptive_use_gross"]
            else:
                zone_allocation = None
                zone_carryover_af = None
                zone_remaining = None
            zone_summaries.append({
                "zone": zone,
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
            })

    # Bottom-line: supplies minus estimated consumptive use.
    grand_net = grand_supply_total - grand_consumptive_use

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
    if is_enabled("datasync"):
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

    # Active accounts whose consumptive use has passed their allocation this
    # period (only meaningful once the period has allocations; remaining is None
    # otherwise, so those accounts never count).
    accounts_over_budget = sum(
        1
        for s in account_summaries
        if s["remaining"] is not None and s["remaining"] < 0
    )

    attention_total = periods_to_close + stations_down + accounts_over_budget

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
        "has_allocations": has_allocations,
        "periods_to_close": periods_to_close,
        "accounts_over_budget": accounts_over_budget,
        "attention_total": attention_total,
    }
    if is_enabled("datasync"):
        context["stations_down"] = stations_down

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

    # Total allocated volume over the WHOLE filtered set (every matching row, not
    # just the visible page) — the dense-table "how much, in total?" answer that
    # makes this a Bucket-2 data table (docs/2.0-UX-PATTERN-SPEC.md). Unlike the
    # ledger, allocations are unsigned positive volumes (no credit/debit polarity),
    # so this is a single sum, not a credits/debits split. Zone is a ForeignKey,
    # not an M2M, so the queryset has no row duplication and aggregates directly
    # without the ledger's pk-refilter.
    allocation_total = queryset.aggregate(total=Sum("allocation_acre_feet"))["total"]

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    periods = ReportingPeriod.objects.order_by("-start_date")

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "allocation_total": allocation_total or 0,
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
    assignments = (
        WaterAccountParcel.objects.filter(water_account=account, removed_date__isnull=True)
        .select_related("parcel", "reporting_period")
        .order_by("-added_date")
    )
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
        })

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

    assignments = (
        WaterAccountParcel.objects.filter(water_account=account, removed_date__isnull=True)
        .select_related("parcel", "reporting_period")
        .order_by("-added_date")
    )

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

    assignments = (
        WaterAccountParcel.objects.filter(water_account=account, removed_date__isnull=True)
        .select_related("parcel", "reporting_period")
        .order_by("-added_date")
    )

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

    queryset = ParcelLedger.objects.select_related(
        "parcel", "water_type", "reporting_period"
    ).order_by("-effective_date", "-created_at")

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
    # newest-first default set on the queryset above. A stable -created_at
    # tiebreak keeps pagination deterministic when the sort field ties.
    if sort in LEDGER_SORTABLE:
        prefix = "-" if direction == "desc" else ""
        queryset = queryset.order_by(f"{prefix}{LEDGER_SORTABLE[sort]}", "-created_at")

    # Column totals over the WHOLE filtered set (every matching row, not just the
    # visible page) — the "how much, in total?" answer that makes this a dense
    # data table (Bucket 2, docs/2.0-UX-PATTERN-SPEC.md). Amounts are signed:
    # supplies/credits are >= 0, debits/usage are < 0, so split the sum into
    # credits + debits + net. Re-filter by PK to drop the zone M2M join, whose row
    # duplication (a parcel in N zones) would otherwise multiply amounts in SUM.
    ledger_totals = ParcelLedger.objects.filter(
        pk__in=queryset.values("pk")
    ).aggregate(
        net=Sum("amount_acre_feet"),
        credits=Sum("amount_acre_feet", filter=Q(amount_acre_feet__gte=0)),
        debits=Sum("amount_acre_feet", filter=Q(amount_acre_feet__lt=0)),
    )

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "ledger_total_net": ledger_totals["net"] or 0,
        "ledger_total_credits": ledger_totals["credits"] or 0,
        "ledger_total_debits": ledger_totals["debits"] or 0,
        "q": q,
        "period_id": period_id,
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
        "source_type_choices": ParcelLedger.SOURCE_TYPE_CHOICES,
        "period_auto_defaulted": period_auto_defaulted,
        "auto_default_period_name": auto_default_period_name,
        "auto_default_calculated": auto_default_calculated,
        "active_areas": active_areas,
        "current_period_id": current_period_id,
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

    return render(request, "accounting/delivery_settings.html", {"form": form})


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
