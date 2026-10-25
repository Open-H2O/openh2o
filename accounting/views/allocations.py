# SPDX-License-Identifier: AGPL-3.0-or-later
"""Allocation plans: the list of plans with their groups, and creating a plan."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render

from accounting.locks import PeriodFinalized, refuse_if_period_finalized
from accounting.forms import AllocationPlanForm
from accounting.models import AllocationPlan, ReportingPeriod
from accounting.services import current_period_id as compute_current_period_id


# ---------------------------------------------------------------------------
# Allocation Plans
# ---------------------------------------------------------------------------


@login_required
def allocations_list(request):
    """Paginated list of allocation plans with HTMX search and period filter.

    143-06 (R-032, R-033, R-041/ISS-164, R-034): "period" absent entirely (a
    bare landing) is distinct from "period=" (the explicit "All periods"
    choice the Period select always sends), the same distinction the ledger
    view makes — only the former gets the current-period auto-default, via
    the helper the two views share (``accounting.services.current_period_id``).
    A bare landing's rows are therefore always addable (rule 5): the footer
    never has to sum across a water year to answer "how much, in total?".
    """
    q = request.GET.get("q", "").strip()
    period_present = "period" in request.GET
    period_id = request.GET.get("period", "").strip()

    if not period_present:
        default_period_id = compute_current_period_id()
        if default_period_id is not None:
            period_id = str(default_period_id)

    # Zone as the link (R-033, "link-zone"): the
    # allocation's own record is read against its use on the zone page, which
    # already draws on the same helper the dashboard's zone row calls
    # (zone_groundwater_budget) -- an allocation page of its own would show one
    # figure and four fields nothing else on the platform needs.
    queryset = AllocationPlan.objects.select_related(
        "zone", "water_type", "reporting_period"
    ).order_by("-reporting_period__start_date", "water_type__name", "zone__name")

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
    # this a Bucket-2 data table (DESIGN.md "Kinds of page"). Zone is a
    # ForeignKey, not an M2M, so the queryset has no row duplication and
    # aggregates directly without the ledger's pk-refilter.
    #
    # **Subtotalled by (period, water type), and never summed across either axis
    # (ISS-156, then R-041/ISS-164).** This footer printed one number until
    # 2026-09-06: 159,671.46 AF for WY 2025-2026, which was 148,500.00 AF of a
    # surface-water district's diversion entitlement plus 11,171.46 AF of a
    # groundwater sustainability agency's pumping allowance. "All periods" then
    # went on to add the SAME entitlement across two water years into
    # 304,200.00 AF, a quantity nobody manages. Different agencies, different
    # law, and different years never add either — so nobody could act on the one
    # figure the old footer gave them. The arithmetic was never wrong; the label
    # was, and shared units are not what makes two rows addable.
    allocation_subtotals = list(
        queryset.values(
            "reporting_period_id",
            "reporting_period__name",
            "reporting_period__start_date",
            "water_type__name",
        )
        .annotate(total=Sum("allocation_acre_feet"), plans=Count("pk"))
        .order_by("-reporting_period__start_date", "water_type__name")
    )
    subtotals_by_period = {}
    for row in allocation_subtotals:
        subtotals_by_period.setdefault(row["reporting_period_id"], []).append(row)

    # Per-period count (every water type together), for the "All periods" row-
    # group divider ("WY 2025-2026 · 8 allocations") — a different number from
    # any one subtotal's own ``plans`` count, which is per water type.
    # ``.order_by()`` clears the ordering `queryset` already carries: left in
    # place, Django folds those extra fields (water_type__name, zone__name)
    # into the GROUP BY alongside reporting_period_id, so every zone counts as
    # its own group of 1 instead of the period's whole count.
    period_counts = {
        row["reporting_period_id"]: row["count"]
        for row in queryset.order_by().values("reporting_period_id").annotate(
            count=Count("pk")
        )
    }

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Candidate A (2026-09-12): "All periods" groups the
    # rows by water year and closes each group with its own subtotal rows,
    # inside the table body, never a tfoot naming a cross-year sum. Marked per
    # row on THIS page only (not the whole filtered set), so a group a page
    # boundary splits still closes at the boundary — with the whole filtered
    # set's total, from subtotals_by_period above, not just this page's rows —
    # and reopens with its own divider on the next page.
    page_rows = list(page_obj)
    for index, alloc in enumerate(page_rows):
        starts_group = (
            index == 0
            or page_rows[index - 1].reporting_period_id != alloc.reporting_period_id
        )
        ends_group = (
            index == len(page_rows) - 1
            or page_rows[index + 1].reporting_period_id != alloc.reporting_period_id
        )
        alloc.starts_period_group = starts_group
        alloc.ends_period_group = ends_group
        alloc.period_group_count = period_counts.get(alloc.reporting_period_id, 0)
        alloc.period_group_subtotals = (
            subtotals_by_period.get(alloc.reporting_period_id, []) if ends_group else []
        )

    periods = ReportingPeriod.objects.order_by("-start_date")

    period_name = "All water years"
    if period_id:
        period_name = next(
            (p.name for p in periods if str(p.pk) == period_id), period_name
        )

    # The card head's facts line (rule 5's label, said once): why "All periods"
    # is here at all, plus a pagination caveat when the totals above cover rows
    # this page does not show.
    facts_parts = []
    if not period_id:
        facts_parts.append(
            "Each total covers one water year and one water type."
        )
    if page_obj.paginator.num_pages > 1:
        facts_parts.append("Totals are for the whole filtered set, not just this page.")
    facts_line = " ".join(facts_parts)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "allocation_subtotals": allocation_subtotals,
        "q": q,
        "period_id": period_id,
        "period_name": period_name,
        "facts_line": facts_line,
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
            try:
                refuse_if_period_finalized(form.cleaned_data["reporting_period"])
            except PeriodFinalized as exc:
                form.add_error("reporting_period", str(exc))
            else:
                form.save()
                return redirect("accounting:allocations_list")
    else:
        form = AllocationPlanForm()

    return render(request, "accounting/allocation_create.html", {"form": form})
