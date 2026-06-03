# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import csv as csv_module
import io

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

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
from accounting.services import (
    account_balance,
    parse_ledger_csv,
    parcel_balance_breakdown,
    zone_balance,
    zone_carryover,
)
from geography.models import ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger
from surface.models import CurtailmentOrder, WaterRight


# Methodology tuning is an administrator's job, gated by the shared, switch-aware
# @admin_required from core.access (ISS-021). It honors the two-tier model and
# deliberately bounces an authenticated non-admin back into the app rather than
# to Django's /admin/ login (which staff_member_required would do).


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def dashboard(request):
    """Water budget overview dashboard with period selector."""
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
    grand_supply = Decimal("0")
    grand_usage = Decimal("0")

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
            bal = account_balance(account, reporting_period=selected_period)

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
                remaining = allocation - bal["usage"]
            else:
                allocation = None
                remaining = None

            account_summaries.append({
                "account": account,
                "supply": bal["supply"],
                "usage": bal["usage"],
                "net": bal["net"],
                "allocation": allocation,
                "remaining": remaining,
            })
            grand_supply += bal["supply"]
            grand_usage += bal["usage"]

        # Water year of the selected period, so we can pull the carry-over that
        # rolled INTO it from the prior year (labelled by the year it ends in,
        # default Oct-anchor — matches carryover_math + rollover_allocations).
        sel_end = selected_period.end_date
        selected_water_year = water_year_of(f"{sel_end.year}-{sel_end.month:02d}")

        # Zone summaries
        for zone in Zone.objects.order_by("name"):
            zbal = zone_balance(zone, reporting_period=selected_period)
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
                zone_remaining = zone_available - zbal["usage"]
            else:
                zone_allocation = None
                zone_carryover_af = None
                zone_remaining = None
            zone_summaries.append({
                "zone": zone,
                "supply": zbal["supply"],
                "usage": zbal["usage"],
                "net": zbal["net"],
                "allocation": zone_allocation,
                "carryover": zone_carryover_af,
                "remaining": zone_remaining,
            })

    grand_net = grand_supply - grand_usage

    context = {
        "periods": periods,
        "selected_period": selected_period,
        "account_summaries": account_summaries,
        "zone_summaries": zone_summaries,
        "grand_supply": grand_supply,
        "grand_usage": grand_usage,
        "grand_net": grand_net,
        "has_allocations": has_allocations,
    }

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

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    periods = ReportingPeriod.objects.order_by("-start_date")

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
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
    """Paginated list of water accounts with HTMX search and status filter."""
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

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": WaterAccount.STATUS_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(
            request, "accounting/partials/_accounts_list_results.html", context
        )

    return render(request, "accounting/accounts_list.html", context)


@login_required
def account_detail(request, pk):
    """Detail view for a single water account with assigned parcels and balances."""
    account = get_object_or_404(WaterAccount, pk=pk)
    assignments = (
        WaterAccountParcel.objects.filter(water_account=account, removed_date__isnull=True)
        .select_related("parcel", "reporting_period")
        .order_by("-added_date")
    )
    acct_parcel_ids = list(assignments.values_list("parcel_id", flat=True))

    # Period selector
    period_id = request.GET.get("period", "").strip()
    periods = ReportingPeriod.objects.order_by("-start_date")
    selected_period = None

    if period_id:
        try:
            selected_period = ReportingPeriod.objects.get(pk=period_id)
        except ReportingPeriod.DoesNotExist:
            pass
    elif not request.GET:
        # Land on the period where THIS account actually has activity, so the
        # page never opens on an allocation-only (or empty) year that hides the
        # supply/usage story — the simple-vs-complex contrast is invisible when
        # usage reads 0 everywhere. Prefer the most recent period carrying real
        # transactions (deliveries / extraction / calculated usage) for the
        # account's parcels; fall back to the most recent open period.
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

    # Account-level balance
    balance = account_balance(account, reporting_period=selected_period)

    # Per-parcel breakdown. ISS-026: route each parcel through billable_ledger
    # (via parcel_balance_breakdown) exactly as account_balance does, so a
    # parcel's gross `et_estimate` row is suppressed wherever its netted
    # `calculated` twin exists. The per-parcel rows then sum to the account total
    # instead of showing ~double it. The old raw
    # ParcelLedger.objects.filter(parcel=p) aggregate summed BOTH ET rows (the
    # double-count) and also discarded the parcel_balance it had just computed.
    parcel_balances = []
    for assignment in assignments:
        p = assignment.parcel
        pb = parcel_balance_breakdown(p, reporting_period=selected_period)
        parcel_balances.append({
            "parcel": p,
            "supply": pb["supply"],
            "usage": pb["usage"],
            "net": pb["net"],
        })

    # Curtailment narrative (ISS / Phase 52-02): surface the cut as a story, not
    # just lower numbers. An account is "curtailed" when any of its parcels is
    # served by a water right under a curtailment order. Match the active order to
    # the right by priority-date cutoff (the same date the right carries).
    curtailment_orders = []
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

    context = {
        "account": account,
        "assignments": assignments,
        "balance": balance,
        "parcel_balances": parcel_balances,
        "periods": periods,
        "selected_period": selected_period,
        "is_curtailed": is_curtailed,
        "curtailment_orders": curtailment_orders,
    }

    if request.headers.get("HX-Request") and "period" in request.GET:
        return render(
            request, "accounting/partials/_account_balances.html", context
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

    WaterAccountParcel.objects.get_or_create(
        water_account=account,
        parcel=parcel,
        reporting_period=None,
    )

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

    queryset = ParcelLedger.objects.select_related(
        "parcel", "water_type", "reporting_period"
    ).order_by("-effective_date", "-created_at")

    periods = ReportingPeriod.objects.order_by("-start_date")
    water_types = WaterType.objects.order_by("name")

    # ISS-022: landing on the ledger with no filters at all should not bury the
    # audit trail. The "How was this calculated?" links only render on
    # calculated rows, so default to the most recent period that HAS calculated
    # rows (falling back to the most recent period with any rows, then to no
    # filter on an empty table). An explicit "All Periods" (period=) is honored.
    period_auto_defaulted = False
    auto_default_period_name = ""
    auto_default_calculated = False
    no_other_filters = not (q or source_type or water_type_id or start_date or end_date)
    if not period_present and no_other_filters:
        default_period_id = (
            ParcelLedger.objects.filter(
                source_type="calculated", reporting_period__isnull=False
            )
            .order_by("-reporting_period__start_date")
            .values_list("reporting_period_id", flat=True)
            .first()
        )
        auto_default_calculated = default_period_id is not None
        if default_period_id is None:
            default_period_id = (
                ParcelLedger.objects.filter(reporting_period__isnull=False)
                .order_by("-reporting_period__start_date")
                .values_list("reporting_period_id", flat=True)
                .first()
            )
        if default_period_id is not None:
            period_id = str(default_period_id)
            period_auto_defaulted = True
            default_period = next(
                (p for p in periods if p.pk == default_period_id), None
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

    paginator = Paginator(queryset, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "period_id": period_id,
        "source_type": source_type,
        "water_type_id": water_type_id,
        "start_date": start_date,
        "end_date": end_date,
        "periods": periods,
        "water_types": water_types,
        "source_type_choices": ParcelLedger.SOURCE_TYPE_CHOICES,
        "period_auto_defaulted": period_auto_defaulted,
        "auto_default_period_name": auto_default_period_name,
        "auto_default_calculated": auto_default_calculated,
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
    writer.writerow([
        "parcel_number",
        "effective_date",
        "amount_acre_feet",
        "source_type",
        "water_type_code",
        "description",
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

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ledger_export.csv"'
    writer = csv_module.writer(response)
    writer.writerow([
        "parcel_number", "effective_date", "amount_acre_feet",
        "source_type", "water_type", "reporting_period", "description",
    ])
    for entry in queryset.iterator():
        writer.writerow([
            entry.parcel.parcel_number,
            entry.effective_date,
            entry.amount_acre_feet,
            entry.source_type,
            entry.water_type.name if entry.water_type else "",
            entry.reporting_period.name if entry.reporting_period else "",
            entry.description,
        ])
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

    steps = [
        {
            "label": s.get("label") or s.get("step_type"),
            "input_af": s.get("input_af"),
            "output_af": s.get("output_af"),
            "detail_text": _step_detail_summary(s),
        }
        for s in run.breakdown
    ]

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
