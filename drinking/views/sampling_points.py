# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sampling-point list and the detail page for one sampling point."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q, QuerySet
from django.shortcuts import get_object_or_404, render
from core.workspace import list_response
from drinking.models import (
    POINT_TYPE_CHOICES,
    SampleResult,
    SamplingPoint,
    SystemFacility,
    WaterSystem,
)
from drinking.views.common import group_results_by_event, _facility_geojson


def _sampling_points_head_line(
    *, all_count, mapped_facility_count, total_count, result_located_count, q, filter_words
):
    """The Sampling Points card head's `line` override.

    ``partials/_map_card_head.html``'s own branches describe ONE set of rows
    on the map exactly as the list counts them. This page's list counts
    sampling POINTS and its map draws the FACILITIES they sit at (one facility
    can host several points), so "the located subset" is a count of
    facilities, not of points — a shape the shared partial's branches cannot
    say on their own, hence this override. Mirrors their wording (and their
    three states — full load, a filter with matches, a filter with none) as
    closely as that difference allows.
    """
    if not q and not filter_words:
        noun = "sampling point" if all_count == 1 else "sampling points"
        # Plain words ("at a located facility, on the map" read as machine
        # prose). The Facilities head's own shape.
        return f"{all_count:,} {noun}, {mapped_facility_count:,} of them on the map"

    clause_bits = []
    if q:
        clause_bits.append(f"“{q}”")
    if filter_words:
        clause_bits.append(filter_words)
    clause = " ".join(clause_bits)

    if not total_count:
        return f"No sampling point matching {clause}; the map shows none"

    match_verb = "matches" if total_count == 1 else "match"
    if not result_located_count and total_count == 1:
        tail = "its facility has no location recorded, so the map shows none"
    elif not result_located_count:
        tail = "their facilities have no location recorded, so the map shows none"
    elif total_count == 1:
        tail = "the map shows it"
    else:
        tail = f"the map shows {result_located_count:,} of them"
    return f"{total_count:,} of {all_count:,} {match_verb} {clause}; {tail}"


def _filtered_sampling_points(q: str, point_type: str) -> QuerySet[SamplingPoint]:
    """The annotated sampling points matching the search and the type filter."""
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
    return queryset


def _points_pwsid_for_empty_state(has_any_point: bool) -> str:
    """The one system's PWSID the empty state's builder button opens on, or ""."""
    # The PWSID the empty state's "Build sampling points" button opens
    # on. Onboarding writes facilities and deliberately never writes a point, so
    # the right door from an empty inventory is the builder — and the builder
    # takes a PWSID in its path.
    #
    # Computed ONLY when the list is empty, which is the only render that can
    # show the empty state. A populated page issues exactly the queries it did
    # before this line existed.
    #
    # Exactly one system, or nothing: with two systems there is no honest
    # default, and picking the first would send an operator to the wrong one
    # with no way to tell. `[:2]` asks the database that question in one slice
    # rather than fetching a table to count it.
    points_pwsid = ""
    if not has_any_point:
        pwsids = list(WaterSystem.objects.values_list("pwsid", flat=True)[:2])
        if len(pwsids) == 1:
            points_pwsid = pwsids[0]
    return points_pwsid


def _sampling_point_coverage_counts() -> dict[str, int]:
    """The platform-wide point and facility counts behind the sentence under the map."""
    # The coverage counts for the sentence under the map. Computed here, every
    # render, and NEVER written into the template as literals: the Merced
    # demonstration happens to be 21 of 27 points and 21 of 61 facilities, and an
    # onboarded system has neither of those numbers. EPA's Envirofacts publishes
    # no coordinates at all, so a freshly-onboarded operator's honest answer is
    # zero — which is the common case for a new deployment, not an edge case.
    #
    # Deliberately unfiltered by `q` / `point_type`. This sentence is about what
    # the platform HOLDS, not about what the current search matched; recomputing
    # it per keystroke would make "how much of my inventory is mapped" flicker.
    point_total_count = SamplingPoint.objects.count()
    mapped_point_count = SamplingPoint.objects.filter(
        facility__location__isnull=False
    ).count()
    total_facility_count = SystemFacility.objects.count()
    mapped_facility_count = SystemFacility.objects.filter(
        location__isnull=False
    ).count()
    return {
        "point_total_count": point_total_count,
        "mapped_point_count": mapped_point_count,
        "total_facility_count": total_facility_count,
        "mapped_facility_count": mapped_facility_count,
    }


def _sampling_point_map_head(
    queryset: QuerySet[SamplingPoint],
    coverage: dict[str, int],
    total_count: int,
    q: str,
    point_type: str,
) -> tuple[list[int], int, str | None]:
    """The map card head: (facility pks drawn, located facility count, `line` override)."""
    # The map card's head: the map draws FACILITIES, so the pks the
    # results partial emits are the distinct facility ids of the FILTERED
    # sampling points, never the points' own pks. `result_located_count`
    # counts the distinct located facilities among that same filtered set —
    # the number the `line` override actually names.
    point_type_label = dict(POINT_TYPE_CHOICES).get(point_type, "")
    result_pks = list(
        queryset.values_list("facility_id", flat=True).distinct()
    )
    result_located_count = (
        queryset.filter(facility__location__isnull=False)
        .values_list("facility_id", flat=True)
        .distinct()
        .count()
    )
    # None when nothing is located at all: `_map_card_head.html`'s own
    # `{% elif not located_count %}` branch ("No sampling point has a
    # location yet.") already says that correctly, and skips building the map
    # host — no need for this override to duplicate it.
    head_line = (
        _sampling_points_head_line(
            all_count=coverage["point_total_count"],
            mapped_facility_count=coverage["mapped_facility_count"],
            total_count=total_count,
            result_located_count=result_located_count,
            q=q,
            filter_words=f"of type “{point_type_label}”" if point_type_label else "",
        )
        if coverage["mapped_facility_count"]
        else None
    )
    return result_pks, result_located_count, head_line


@login_required
def sampling_points(request):
    """The sampling-point inventory: where samples are physically drawn.

    ``latest_sample_date`` and ``result_count`` are annotated over the single
    point -> events -> results join chain rather than walked per row, so this
    page issues one query no matter how many points a system carries.
    """
    q = request.GET.get("q", "").strip()
    point_type = request.GET.get("point_type", "").strip()

    queryset = _filtered_sampling_points(q, point_type)

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    has_any_point = SamplingPoint.objects.exists()
    points_pwsid = _points_pwsid_for_empty_state(has_any_point)

    coverage = _sampling_point_coverage_counts()
    point_total_count = coverage["point_total_count"]
    mapped_point_count = coverage["mapped_point_count"]
    mapped_facility_count = coverage["mapped_facility_count"]

    result_pks, result_located_count, head_line = _sampling_point_map_head(
        queryset, coverage, paginator.count, q, point_type
    )

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
            "has_any": has_any_point,
            "points_pwsid": points_pwsid,
            "has_system": WaterSystem.objects.exists(),
            "point_total_count": point_total_count,
            "mapped_point_count": mapped_point_count,
            "unmapped_point_count": point_total_count - mapped_point_count,
            "total_facility_count": coverage["total_facility_count"],
            "mapped_facility_count": mapped_facility_count,
            "all_count": point_total_count,
            "located_count": mapped_facility_count,
            "result_pks": result_pks,
            "result_located_count": result_located_count,
            "line": head_line,
            "hx_request": bool(request.headers.get("HX-Request")),
        },
    )


#: How many of a sampling point's results its detail page shows.
#:
#: A point in the Merced demonstration carries roughly 800 results (22,367
#: across 27 points), so rendering "its results" unbounded is an 800-row page.
#: Paginating them here would be a second, worse copy of the results log, which
#: already filters by ``?sampling_point=``. The page shows the most recent 25
#: and states the true total beside them — a truncated list that does not admit
#: it is truncated is the failure mode this constant exists to avoid.
RECENT_RESULT_LIMIT = 25


@login_required
def sampling_point_detail(request, pk):
    """One sampling point: where it is, what hangs off it, its recent results."""
    point = get_object_or_404(
        SamplingPoint.objects.select_related(
            "facility", "facility__system", "facility__well"
        ),
        pk=pk,
    )

    at_this_point = SampleResult.objects.filter(event__sampling_point=point)
    summary = at_this_point.aggregate(
        result_count=Count("pk"),
        analyte_count=Count("analyte", distinct=True),
        first_sample=Min("event__sample_date"),
        latest_sample=Max("event__sample_date"),
    )
    # `event_id` rides in the ordering (ahead of `analyte__name`) for the same
    # reason `results()` carries it: `group_results_by_event` only folds a
    # CONTIGUOUS run of one `event_id`, so two events sharing a date must not
    # interleave by analyte before they reach it.
    recent = (
        at_this_point
        .select_related("analyte", "event")
        .order_by("-event__sample_date", "event_id", "analyte__name")[:RECENT_RESULT_LIMIT]
    )

    return render(
        request,
        "drinking/sampling_point_detail.html",
        {
            "point": point,
            "recent_results": recent,
            # The SAME helper the results log calls
            # (`group_results_by_event`, defined above), on this point's own
            # `recent` slice, so one place decides how a run of results folds
            # into one block per sample event.
            "result_groups": group_results_by_event(recent),
            "shown_limit": RECENT_RESULT_LIMIT,
            "is_truncated": summary["result_count"] > RECENT_RESULT_LIMIT,
            # Read through the FACILITY, because a sampling point has no
            # coordinate of its own — it is a tap ON a facility and is drawn
            # where the facility is. `select_related("facility")` above already
            # carries the location, so this costs no extra query.
            #
            # `ps_code` rides along so the popup can say WHOSE coordinate this
            # is. A dot that silently claims to be the tap would be the same
            # class of quiet lie as a facility drawn at (0, 0).
            "geojson": _facility_geojson(
                point.facility, extra_properties={"ps_code": point.ps_code}
            ),
            **summary,
        },
    )
