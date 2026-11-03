# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reporting periods: the list, a period's detail page, creating one, running its calculation and finalizing it."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.history import change_note
from accounting.engine_run import create_request, start_calculation
from accounting.locks import finalized_message
from accounting.forms import PeriodFinalizeForm, ReportingPeriodForm
from accounting.models import AllocationPlan, CalculationRequest, ReportingPeriod
from accounting.statements import (
    cached_comparison,
    card_context,
    newest_statement,
    take_statement,
)
from core.access import admin_required
from accounting.services import attach_orphans_to_period
from parcels.models import ParcelLedger


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


#: Who a finished calculation is credited to when no person pressed the button.
_CALCULATION_WHO = {
    "schedule": "the nightly schedule",
    "diversion_saved": "a saved record",
    "ledger_saved": "a saved record",
    "record_voided": "a voided record",
    "record_corrected": "a corrected record",
    "command": "the command line",
}


#: What the card's badge says for each finished state (badge class, words).
_CALCULATION_BADGE = {
    "succeeded": ("badge-green", "Finished"),
    "finished_with_notes": ("badge-amber", "Finished, with notes"),
    "failed": ("badge-orange", "Stopped"),
}


def _calculation_card_context(period):
    """What the period page's Calculation card shows: the latest run for this period.

    ``error_detail`` is deliberately never put here: it is for an
    administrator on Site Health, not for the period page's readers.
    """
    latest = (
        CalculationRequest.objects.filter(reporting_period=period)
        .select_related("requested_by")
        .order_by("-requested_at", "-pk")
        .first()
    )
    if latest is None:
        return {"calculation": None, "calculation_active": False}
    active = latest.status in ("queued", "running")
    total = len(latest.months or [])
    context = {
        "calculation": latest,
        "calculation_active": active,
        "calculation_month_number": min(latest.months_done + 1, total) if total else 0,
        "calculation_month_total": total,
    }
    if latest.trigger == "screen":
        context["calculation_who"] = (
            str(latest.requested_by) if latest.requested_by else "a person"
        )
    else:
        context["calculation_who"] = _CALCULATION_WHO.get(latest.trigger, "")
    # The run's notes: sentences above, table groups in one table below them
    # (2026-10-12). A run from before stores sentences only.
    notes = latest.notes or []
    context["calculation_note_sentences"] = [n for n in notes if not isinstance(n, dict)]
    context["calculation_note_table"] = [n for n in notes if isinstance(n, dict)]
    badge = _CALCULATION_BADGE.get(latest.status)
    if badge:
        context["calculation_badge_class"], context["calculation_badge_text"] = badge
    return context


def _period_detail_context(period, finalize_form=None, comparison=None):
    """The period page's context, shared by ``period_detail`` and by
    ``period_finalize`` re-rendering the same page on a rejected note.

    ``finalize_form`` lets ``period_finalize`` hand back the bound form
    carrying its validation error; a fresh unbound one is built otherwise.
    ``comparison`` is the figures-as-filed comparison when the page prints it in
    place (the figures route opened without scripts); otherwise the card loads it.
    """
    allocations = AllocationPlan.objects.filter(
        reporting_period=period
    ).select_related("zone", "water_type").order_by("water_type__name", "zone__name")
    ledger_count = ParcelLedger.objects.current().filter(reporting_period=period).count()

    # Same shape as the allocations list's per-period subtotals (rule 5's
    # label: what makes a group of rows addable), so the lead panel's figures
    # and the table's footer are read from the one query, not recomputed twice.
    allocation_subtotals = list(
        allocations.values("water_type__name")
        .annotate(total=Sum("allocation_acre_feet"), plans=Count("pk"))
        .order_by("water_type__name")
    )

    return {
        "period": period,
        "allocations": allocations,
        "allocation_subtotals": allocation_subtotals,
        "ledger_count": ledger_count,
        "finalize_form": finalize_form
        or PeriodFinalizeForm(reopening=period.is_finalized),
        # The Figures as filed card: its first line now, the comparison after the page loads.
        "filed_card": card_context(period, comparison=comparison),
        **_calculation_card_context(period),
    }


@login_required
def period_detail(request, pk):
    """Detail view for a single reporting period.

    The period leads with what it IS (its dates, its
    finalized status) and the one figure it exists for — its allocations by
    water type, in the same ``.budget-panel`` shape and the same subtotal
    grouping the allocations list uses for one period, so the two screens
    never say this water year's totals two different ways. The Allocations
    table below is that list's own columns, link and footer, brought here
    rather than re-derived (zone as the link, no Name column).
    """
    period = get_object_or_404(ReportingPeriod, pk=pk)
    return render(
        request, "accounting/period_detail.html", _period_detail_context(period)
    )


@login_required
@require_POST
def period_calculate(request, pk):
    """Start the calculation for an open reporting period.

    Operators and administrators may press it; a viewer's POST never gets here
    (``core.access.ReadOnlyMiddleware`` refuses every viewer write, whichever
    way ``ACCESS_CONTROL_ENFORCED`` is set). A finalized period is refused
    with the same sentence the other write screens use. While a calculation
    for this period is waiting or running, pressing it again starts nothing:
    the page shows the one already under way.
    """
    period = get_object_or_404(ReportingPeriod, pk=pk)
    if period.is_finalized:
        messages.error(request, finalized_message(period.name))
        return redirect("accounting:period_detail", pk=period.pk)

    under_way = CalculationRequest.objects.filter(
        reporting_period=period, status__in=("queued", "running")
    ).exists()
    if not under_way:
        calculation = create_request(
            "screen", reporting_period=period, requested_by=request.user
        )
        start_calculation(calculation)
    return redirect("accounting:period_detail", pk=period.pk)


@login_required
@require_GET
def period_calculation_status(request, pk):
    """The Calculation card's status block, re-fetched every 3 seconds while it runs."""
    period = get_object_or_404(ReportingPeriod, pk=pk)
    return render(
        request,
        "accounting/partials/_calculation_status.html",
        {"period": period, "oob": True, **_calculation_card_context(period)},
    )


@login_required
def period_create(request):
    """Create a new reporting period.

    A record saved before this period existed can attach to it the moment
    the period is saved, with no separate edit step. The counts are shown once, in the
    success message on the period page this redirects to.
    """
    if request.method == "POST":
        form = ReportingPeriodForm(request.POST)
        if form.is_valid():
            period = form.save()
            counts = attach_orphans_to_period(period)
            messages.success(
                request,
                f"Water year created. OpenH2O attached "
                f"{counts['diversion_records']} diversion records and "
                f"{counts['ledger_rows']} ledger entries dated inside it to this "
                f"water year.",
            )
            return redirect("accounting:period_detail", pk=period.pk)
    else:
        form = ReportingPeriodForm()

    return render(request, "accounting/period_create.html", {"form": form})


@login_required
@admin_required
@require_POST
def period_finalize(request, pk):
    """Toggle finalized status on a reporting period, administrators only.

    Reopening keeps the history intact (the earlier finalizer stays on
    the change history; only the live ``finalized_by``/``finalized_at`` are
    nulled) and requires a reason, 10-500 characters, via
    ``PeriodFinalizeForm``; finalizing takes the same note, optional. Either
    way the note is attached with ``change_note`` so it lands on the period's
    change-history event. An invalid note re-renders the period page with the
    form's error and saves nothing (status 200) -- never a redirect, so the
    error survives to be shown.

    When ``ACCESS_CONTROL_ENFORCED`` is off, ``admin_required`` passes every
    signed-in user through by design (the hosted demo's documented posture);
    this view does not touch that switch.
    """
    period = get_object_or_404(ReportingPeriod, pk=pk)
    reopening = period.is_finalized
    form = PeriodFinalizeForm(request.POST, reopening=reopening)

    if not form.is_valid():
        return render(
            request,
            "accounting/period_detail.html",
            _period_detail_context(period, finalize_form=form),
        )

    with change_note(form.cleaned_data.get("note")), transaction.atomic():
        # Held until the save commits, so two presses of Finalize at once cannot
        # each write a statement; the second finds the year already changed.
        period = ReportingPeriod.objects.select_for_update().get(pk=period.pk)
        if period.is_finalized != reopening:
            return redirect("accounting:period_detail", pk=period.pk)
        if reopening:
            period.is_finalized = False
            period.finalized_at = None
            period.finalized_by = None
        else:
            # Write down every figure the year prints BEFORE it is marked
            # finalized (the lock lets the rows in while the year is open).
            # Reopening keeps every statement, so finalizing again restates.
            take_statement(
                period,
                kind="restated" if newest_statement(period) else "filed",
                user=request.user,
            )
            period.is_finalized = True
            period.finalized_at = timezone.now()
            period.finalized_by = request.user
        period.save()

    return redirect("accounting:period_detail", pk=period.pk)


@login_required
@require_GET
def period_figures(request, pk):
    """The Figures as filed comparison: the figures filed beside the figures now, and what moved them.

    Read-only, for every signed-in reader. The card on the water year page asks
    for it with HTMX once the page has loaded (the comparison reads every
    figure the pages print), and the answer is kept in the cache under the
    statement and a token of the records the figures read. Opened by address,
    without scripts, it is the water year page with the comparison printed in
    the card.
    """
    period = get_object_or_404(ReportingPeriod, pk=pk)
    comparison = cached_comparison(period)
    if comparison is None:
        raise Http404("This water year has no figures on file.")
    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/partials/_figures_moved.html",
            {"comparison": comparison, "oob": True, "period": period},
        )
    return render(
        request,
        "accounting/period_detail.html",
        _period_detail_context(period, comparison=comparison),
    )
