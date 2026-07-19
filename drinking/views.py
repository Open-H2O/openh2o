# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Drinking water views.

The three read surfaces for the PWS domain: the system overview (identity plus
its facilities), the sampling-point inventory, and the sample-result log.

**Prepare, never determine.** No view here compares a result against a limit or
colors a row by it. Showing a result and separately showing what the limit is
are both facts; rendering a verdict is a regulatory determination this platform
does not make. See ``drinking/models.py``.

Django admin is the write path until 78-03 ships the CSV importer, so these are
deliberately read-only — no inline ``edit_field`` surface yet.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import render
from django.utils.dateparse import parse_date

from core.workspace import list_response
from drinking.models import (
    POINT_TYPE_CHOICES,
    Analyte,
    SampleResult,
    SamplingPoint,
    SystemFacility,
    WaterSystem,
)


@login_required
def overview(request):
    """The water system(s) this deployment carries, each with its facilities.

    Usually one row, like SiteConfig — but a table, so a wholesaler or a
    consecutive system can be carried alongside. The facility rows link through
    to ``wells:detail`` wherever ``SystemFacility.well`` is set: that link is the
    quality-to-quantity join made visible, the same physical well seen from the
    sampling side and the extraction side.
    """
    facilities = (
        SystemFacility.objects
        .select_related("well")
        .annotate(sampling_point_count=Count("sampling_points"))
        .order_by("facility_id")
    )
    systems = (
        WaterSystem.objects
        .prefetch_related(Prefetch("facilities", queryset=facilities))
        .order_by("pwsid")
    )

    return render(request, "drinking/overview.html", {"systems": systems})


@login_required
def sampling_points(request):
    """The sampling-point inventory: where samples are physically drawn.

    ``latest_sample_date`` and ``result_count`` are annotated over the single
    point -> events -> results join chain rather than walked per row, so this
    page issues one query no matter how many points a system carries.
    """
    q = request.GET.get("q", "").strip()
    point_type = request.GET.get("point_type", "").strip()

    queryset = (
        SamplingPoint.objects
        .select_related("facility", "facility__system", "facility__well")
        .annotate(
            latest_sample_date=Max("events__sample_date"),
            result_count=Count("events__results"),
        )
        .order_by("ps_code")
    )

    # One filter() with a Q, never `qs.filter(a) | qs.filter(b)`: OR-ing two
    # already-annotated querysets re-joins events and results and inflates both
    # annotations.
    if q:
        queryset = queryset.filter(
            Q(ps_code__icontains=q) | Q(name__icontains=q)
        )
    if point_type:
        queryset = queryset.filter(point_type=point_type)

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return list_response(
        request,
        page_template="drinking/sampling_points.html",
        results_template="drinking/partials/_sampling_point_results.html",
        context={
            "page_obj": page_obj,
            "total_count": paginator.count,
            "q": q,
            "point_type": point_type,
            "point_type_choices": POINT_TYPE_CHOICES,
            "has_any": SamplingPoint.objects.exists(),
        },
    )


@login_required
def results(request):
    """The sample-result log — the workhorse surface.

    Filters are plain GET params (analyte, sampling point, date range) so a
    filtered view is a shareable URL. Every result is rendered through its
    ``result_kind``: a presence/absence row can never appear as a number, which
    is the whole reason that discriminator exists.
    """
    analyte_id = request.GET.get("analyte", "").strip()
    point_id = request.GET.get("sampling_point", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    queryset = (
        SampleResult.objects
        .select_related(
            "analyte",
            "event",
            "event__sampling_point",
            "event__sampling_point__facility",
            "event__sampling_point__facility__system",
        )
        .order_by("-event__sample_date", "analyte__name")
    )

    if analyte_id.isdigit():
        queryset = queryset.filter(analyte_id=analyte_id)
    if point_id.isdigit():
        queryset = queryset.filter(event__sampling_point_id=point_id)
    # Parsed, not passed through. An unparseable date reaching the ORM raises
    # ValidationError -> 500; a hand-edited or truncated URL should degrade to
    # the unfiltered list instead of an error page.
    parsed_from = parse_date(date_from) if date_from else None
    parsed_to = parse_date(date_to) if date_to else None
    if parsed_from:
        queryset = queryset.filter(event__sample_date__gte=parsed_from)
    if parsed_to:
        queryset = queryset.filter(event__sample_date__lte=parsed_to)

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return list_response(
        request,
        page_template="drinking/results.html",
        results_template="drinking/partials/_result_results.html",
        context={
            "page_obj": page_obj,
            "total_count": paginator.count,
            "analyte_id": analyte_id,
            "point_id": point_id,
            "date_from": date_from,
            "date_to": date_to,
            "analytes": Analyte.objects.filter(results__isnull=False).distinct(),
            "sampling_points": SamplingPoint.objects.order_by("ps_code"),
            "has_any": SampleResult.objects.exists(),
        },
    )
