# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import csv as csv_module
import io

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounting.forms import (
    AllocationPlanForm,
    CsvUploadForm,
    ParcelLedgerForm,
    ReportingPeriodForm,
    WaterAccountForm,
)
from accounting.models import (
    AllocationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterCreditDraw,
    WaterType,
)
from accounting.services import account_balance, parse_ledger_csv, parcel_balance, zone_balance
from geography.models import ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger


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

        # Account summaries
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

        # Zone summaries
        for zone in Zone.objects.order_by("name"):
            zbal = zone_balance(zone, reporting_period=selected_period)
            if has_allocations:
                zone_allocation = AllocationPlan.objects.filter(
                    zone=zone,
                    reporting_period=selected_period,
                ).aggregate(total=Sum("allocation_acre_feet"))["total"] or Decimal("0")
                zone_remaining = zone_allocation - zbal["usage"]
            else:
                zone_allocation = None
                zone_remaining = None
            zone_summaries.append({
                "zone": zone,
                "supply": zbal["supply"],
                "usage": zbal["usage"],
                "net": zbal["net"],
                "allocation": zone_allocation,
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

    # Period selector: default to most recent non-finalized, or all-time
    period_id = request.GET.get("period", "").strip()
    periods = ReportingPeriod.objects.order_by("-start_date")
    selected_period = None

    if period_id:
        try:
            selected_period = ReportingPeriod.objects.get(pk=period_id)
        except ReportingPeriod.DoesNotExist:
            pass
    elif not request.GET:
        # Auto-select most recent non-finalized period if available
        default_period = periods.filter(is_finalized=False).first()
        if default_period:
            selected_period = default_period

    # Account-level balance
    balance = account_balance(account, reporting_period=selected_period)

    # Per-parcel breakdown
    parcel_balances = []
    for assignment in assignments:
        p = assignment.parcel
        pb = parcel_balance(p, reporting_period=selected_period)
        # Compute supply/usage per parcel
        qs = ParcelLedger.objects.filter(parcel=p)
        if selected_period:
            qs = qs.filter(reporting_period=selected_period)
        agg = qs.aggregate(
            supply=Sum("amount_acre_feet", filter=Q(amount_acre_feet__gt=0)),
            usage=Sum("amount_acre_feet", filter=Q(amount_acre_feet__lt=0)),
        )
        supply = agg["supply"] or Decimal("0")
        usage = abs(agg["usage"] or Decimal("0"))
        parcel_balances.append({
            "parcel": p,
            "supply": supply,
            "usage": usage,
            "net": supply - usage,
        })

    context = {
        "account": account,
        "assignments": assignments,
        "balance": balance,
        "parcel_balances": parcel_balances,
        "periods": periods,
        "selected_period": selected_period,
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

    paginator = Paginator(queryset, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    periods = ReportingPeriod.objects.order_by("-start_date")
    water_types = WaterType.objects.order_by("name")

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
    }
    return render(request, "accounting/calculation_run_detail.html", context)
