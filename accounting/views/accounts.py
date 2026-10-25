# SPDX-License-Identifier: AGPL-3.0-or-later
"""Water accounts: the list, an account's detail page, creating and editing an account, and assigning or removing its parcels."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounting.locks import PeriodFinalized, refuse_if_period_finalized
from accounting.forms import WaterAccountForm
from accounting.models import (
    AllocationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterType,
)
from core.modules import is_enabled
from core.workspace import redirect_to_selected
from accounting.services import (
    account_consumptive_balance,
    balance_state,
    current_period_id as compute_current_period_id,
    parcel_consumptive_balance,
    runs_in_period,
)
from parcels.models import Parcel, ParcelLedger
from accounting.views.common import _account_summary_row


# ---------------------------------------------------------------------------
# Water Accounts
# ---------------------------------------------------------------------------


@login_required
def accounts_list(request):
    """Water accounts overview (143-13, "accounts-table"):
    the dashboard's own Active water accounts table, with a search and the
    period control that drives its figures. Replaces the earlier
    master-detail workspace (`workspace.html`), the shell Use Areas and Wells
    also left (candidate A, "the list is the page").

    A ``?selected=<pk>`` query param (the old workspace's deep-link shape)
    redirects to the account's own detail page so a bookmarked link still
    lands somewhere real.

    Returns the ``_accounts_list_results`` partial for an HTMX list refresh
    (search / period, which target ``#results``), and the full page
    otherwise.
    """
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        return redirect_to_selected(request, "accounting:account_detail", selected_raw)

    q = request.GET.get("q", "").strip()
    period_param = request.GET.get("period", "").strip()

    periods = ReportingPeriod.objects.order_by("-start_date")
    selected_period = None
    if period_param:
        selected_period = periods.filter(pk=period_param).first()
    else:
        # The same "current period" default the allocations and ledger
        # screens land on (accounting.services.current_period_id), so this
        # page never opens on a stale or empty year just because nobody
        # passed ?period=.
        default_period_id = compute_current_period_id()
        if default_period_id:
            selected_period = periods.filter(pk=default_period_id).first()

    all_active = WaterAccount.objects.filter(status="active")
    total_count = all_active.count()

    queryset = all_active.order_by("account_number")
    if q:
        queryset = queryset.filter(
            Q(account_number__icontains=q)
            | Q(name__icontains=q)
            | Q(contact_name__icontains=q)
        )

    has_allocations = False
    groundwater_type = None
    engine_has_never_run = False

    if selected_period is not None:
        has_allocations = AllocationPlan.objects.filter(
            reporting_period=selected_period,
        ).exists()
        groundwater_type = WaterType.objects.filter(code__iexact="GW").first()
        engine_has_never_run = (
            Parcel.objects.exists()
            and not runs_in_period(
                CalculationRun.objects.all(), selected_period
            ).exists()
        )

    # Built regardless of whether a period is selected: `selected_period=None`
    # reaches `_account_summary_row` -> `account_consumptive_balance` the same
    # way the account detail pane's own "All Time" choice does (reporting_period
    # is an optional filter there, not a requirement), so an account still
    # shows as a row, its identity, never invented figures, even on a
    # deployment with no reporting period yet. `has_allocations` is False in
    # that case, so every row's allocation/remaining stay the dash they always
    # are with no budget to show.
    account_summaries = []
    grand_consumptive_use = Decimal("0")
    grand_supply_total = Decimal("0")
    grand_supply_surface = Decimal("0")
    grand_supply_groundwater = Decimal("0")
    grand_supply_precip = Decimal("0")
    for account in queryset:
        row = _account_summary_row(
            account, selected_period, has_allocations, groundwater_type
        )
        account_summaries.append(row)
        grand_consumptive_use += row["consumptive_use_gross"]
        grand_supply_total += row["supply_total"]
        grand_supply_surface += row["surface"]
        grand_supply_groundwater += row["groundwater"]
        grand_supply_precip += row["precip"]
    grand_net = grand_supply_total - grand_consumptive_use

    context = {
        "account_summaries": account_summaries,
        "has_allocations": has_allocations,
        "engine_has_never_run": engine_has_never_run,
        "grand_consumptive_use": grand_consumptive_use,
        "grand_supply_total": grand_supply_total,
        "grand_supply_surface": grand_supply_surface,
        "grand_supply_groundwater": grand_supply_groundwater,
        "grand_supply_precip": grand_supply_precip,
        "grand_net": grand_net,
        "periods": periods,
        "selected_period": selected_period,
        "q": q,
        "total_count": total_count,
        "matched_count": len(account_summaries),
        "hx_request": bool(request.headers.get("HX-Request")),
    }

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


def _account_delivery_sentence(account):
    """"A farm unit" or "A farm unit · delivered through <point or well>"
    (Q8, 146-05 Task 3): the identity card's leading clause, plus its
    delivery system when one is set. Computed once here rather than in the
    template -- the same discipline `wells/views.py::_dwr_extraction_line`
    uses for the well page's identity line.

    `delivery_well` is a real field on `WaterAccount` (`wells` is
    schema-resident, so reading it needs no guard); the point-of-diversion
    side lives on `surface.WaterAccountDeliveryPoint` instead and is read
    through a guarded, function-scope import -- `surface` is optional and
    truly removable (Phase 87).
    """
    parts = [account.unit_kind_sentence()]
    delivery = None
    if account.delivery_well_id:
        delivery = account.delivery_well.name
    elif is_enabled("surface"):
        from surface.models import WaterAccountDeliveryPoint

        link = (
            WaterAccountDeliveryPoint.objects.filter(account=account)
            .select_related("point_of_diversion")
            .first()
        )
        if link:
            delivery = link.point_of_diversion.name
    if delivery:
        parts.append(f"delivered through {delivery}")
    return " · ".join(parts)


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
    # ISS-237: judged on the two decimals the page prints; 0.00 is balanced.
    use_area_states = [balance_state(pb["net_vs_supply"]) for pb in parcel_balances]
    use_areas_in_surplus = use_area_states.count("surplus")
    use_areas_in_deficit = use_area_states.count("deficit")
    use_areas_balanced = use_area_states.count("balanced")

    # The account's map card (ISS-175, 150-02): the head's two counts, read off
    # the rows the loop above already fetched (select_related parcel, so no
    # query). Counted by use area, not by row, because the map draws each use
    # area once; `?account=` on parcels:geojson selects the same active rows.
    assigned_parcels = {a.parcel_id: a.parcel for a in assignments}
    use_areas_all_count = len(assigned_parcels)
    use_areas_located_count = sum(
        1 for p in assigned_parcels.values() if p.geometry is not None
    )

    return {
        "account": account,
        "assignments": assignments,
        "balance": balance,
        "parcel_balances": parcel_balances,
        "use_areas_estimated": use_areas_estimated,
        "use_areas_in_surplus": use_areas_in_surplus,
        "use_areas_in_deficit": use_areas_in_deficit,
        "use_areas_balanced": use_areas_balanced,
        "use_areas_all_count": use_areas_all_count,
        "use_areas_located_count": use_areas_located_count,
        "periods": periods,
        "selected_period": selected_period,
        "delivery_sentence": _account_delivery_sentence(account),
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
def account_edit(request, pk):
    """Edit a water account, including Q8's unit kind and delivery system.

    146-05 Task 3's door: "the account create and edit forms" -- no account
    edit route existed before this (only the create form and the assign/
    remove-parcel actions), so this is new.
    """
    account = get_object_or_404(WaterAccount, pk=pk)
    if request.method == "POST":
        form = WaterAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            return redirect("accounting:account_detail", pk=account.pk)
    else:
        form = WaterAccountForm(instance=account)

    return render(
        request, "accounting/account_edit.html", {"form": form, "account": account}
    )


@login_required
@require_POST
def assign_parcel(request, pk):
    """Assign a parcel to a water account."""
    account = get_object_or_404(WaterAccount, pk=pk)
    parcel_id = request.POST.get("parcel_id")
    parcel = get_object_or_404(Parcel, pk=parcel_id)

    # This door writes the undated assignment (no reporting period), which
    # no finalized year locks (147-02: an assignment is locked only when it
    # names a finalized period), so it has nothing to refuse.
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
    try:
        refuse_if_period_finalized(wap.reporting_period)
    except PeriodFinalized as exc:
        return _assignment_refused(request, account, exc)
    wap.removed_date = timezone.now().date()
    wap.save(update_fields=["removed_date"])

    assignments = _account_assignments(account)

    return render(
        request,
        "accounting/partials/_parcel_assignment.html",
        {"account": account, "assignments": assignments},
    )


def _assignment_refused(request, account, exc):
    """The assignment section again, carrying the finalized-year refusal."""
    return render(
        request,
        "accounting/partials/_parcel_assignment.html",
        {
            "account": account,
            "assignments": _account_assignments(account),
            "assignment_error": str(exc),
        },
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
