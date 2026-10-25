# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facility list, its detail page, the add and edit forms, and the map data they share."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from core.access import public_in_open_demo
from core.map_labels import map_label
from core.workspace import list_response
from drinking.forms import FacilityLocalNameForm, SystemFacilityForm
from drinking.models import (
    ACTIVITY_STATUS_CHOICES,
    FACILITY_TYPE_CHOICES,
    SamplingPoint,
    SystemFacility,
    WaterSystem,
)
from drinking.views.common import _facility_geojson, _describe


def _present_choices(field_name, choices):
    """The filter options actually present in the database, never the full table.

    **This is a build requirement, not a style preference.** ``FACILITY_TYPE_CHOICES``
    carries ("WL", "Well"), ("CW", "Clear Well") and ("WH", "Wellhead"). A
    ``<select>`` renders its option TEXT on every load — empty database included
    — and ``tests/droppability/checks.py::visible_text()`` strips tags and keeps
    text, so those three options are read as page prose. ``_FORBIDDEN_VOCABULARY``
    fails any page a ``wells``-less deployment keeps if it names ``well`` or
    ``wells``, so rendering the full choices table here fails
    ``test_kept_pages_never_name_a_dropped_module[wells]``. The existing
    sampling-point filter survives only because POINT_TYPE_CHOICES happens to be
    Source / Entry Point / Distribution / Tap.

    Building from the database also happens to be better UX than a 22-option
    list where three are used. If you are here to "simplify" this back to
    ``FACILITY_TYPE_CHOICES``, that is the failure you are about to reintroduce.
    """
    labels = dict(choices)
    present = (
        SystemFacility.objects
        .order_by()
        .values_list(field_name, flat=True)
        .distinct()
    )
    return sorted(
        ((code, labels[code]) for code in present if code in labels),
        key=lambda pair: pair[1],
    )


def _filtered_facilities(
    q: str, facility_type: str, activity_status: str
) -> QuerySet[SystemFacility]:
    """The facilities matching the search and the two exact filters, unannotated."""
    # The filters live on `base_queryset`, unannotated, so the type-count
    # aggregate below can group it by `facility_type` alone. Annotating it
    # first and THEN grouping by fewer fields would fold `sampling_point_count`
    # into the same GROUP BY and re-join `sampling_points` under the new
    # `Count("id")` -- the exact join-multiplication bug the comment below
    # already warns about, just one step removed.
    base_queryset = SystemFacility.objects.select_related("well", "system")

    # One filter() with a Q, never `qs.filter(a) | qs.filter(b)`: OR-ing an
    # already-annotated queryset re-joins sampling_points and inflates the count.
    if q:
        base_queryset = base_queryset.filter(
            Q(facility_id__icontains=q)
            | Q(name__icontains=q)
            | Q(local_name__icontains=q)
        )
    if facility_type:
        base_queryset = base_queryset.filter(facility_type=facility_type)
    if activity_status:
        base_queryset = base_queryset.filter(activity_status=activity_status)
    return base_queryset


def _facility_population_counts(
    base_queryset: QuerySet[SystemFacility],
) -> tuple[int, int, int]:
    """The card head's population line as (sources, treatment plants, distribution systems)."""
    # The card head's population line: one facility_type count query
    # over the FILTERED, unannotated queryset -- never a per-row loop -- with
    # "source" as the residual bucket (every present type that is not a
    # treatment plant or the distribution system). Measured on the local
    # stack every present type besides TP/DS is a source (`is_source=True`);
    # this reads the same story off `facility_type` so it stays one query.
    type_counts = dict(
        base_queryset.order_by()
        .values("facility_type")
        .annotate(n=Count("id"))
        .values_list("facility_type", "n")
    )
    n_tp = type_counts.pop("TP", 0)
    n_ds = type_counts.pop("DS", 0)
    n_source = sum(type_counts.values())
    return n_source, n_tp, n_ds


def _facility_filter_words(facility_type: str, activity_status: str) -> str:
    """The active filters in words, for the map card head."""
    facility_type_label = dict(FACILITY_TYPE_CHOICES).get(facility_type, "")
    activity_status_label = dict(ACTIVITY_STATUS_CHOICES).get(activity_status, "")
    filter_bits = []
    if facility_type_label:
        filter_bits.append(f"of type “{facility_type_label}”")
    if activity_status_label:
        filter_bits.append(f"with status “{activity_status_label}”")
    return " and ".join(filter_bits)


def _facility_coverage_context(queryset: QuerySet[SystemFacility]) -> dict:
    """The choice lists and the map coverage counts the page and its head partial read."""
    return {
        # Read _present_choices' docstring before touching either of these.
        "facility_type_choices": _present_choices(
            "facility_type", FACILITY_TYPE_CHOICES
        ),
        "activity_status_choices": _present_choices(
            "activity_status", ACTIVITY_STATUS_CHOICES
        ),
        "has_any": SystemFacility.objects.exists(),
        # The coverage counts for the sentence under the map, the
        # same pair `sampling_points` computes below and for the same
        # reason — the Merced demonstration's figures are not any other
        # system's, and an Envirofacts-onboarded system starts at zero
        # because EPA publishes no coordinates at all.
        #
        # Deliberately UNFILTERED by `q` / `facility_type` /
        # `activity_status`. This sentence is about what the platform
        # HOLDS, not about what the current search matched.
        "total_facility_count": SystemFacility.objects.count(),
        # The page names both publishers once a facility was added by hand.
        "any_added_by_hand": SystemFacility.objects.filter(added_by_hand=True).exists(),
        "mapped_facility_count": SystemFacility.objects.filter(
            location__isnull=False
        ).count(),
        # The head partial's own names for the same two counts, plus the
        # FILTERED located count (the map follows
        # the list, so this is the number that actually lands on it).
        "all_count": SystemFacility.objects.count(),
        "located_count": SystemFacility.objects.filter(
            location__isnull=False
        ).count(),
        "result_pks": list(queryset.values_list("pk", flat=True)),
        "result_located_count": queryset.filter(
            location__isnull=False
        ).count(),
    }


@login_required
def facilities(request):
    """The facility inventory: every physical part of the water system.

    Was a 61-row table stapled to the bottom of the overview, where it could not
    be searched, filtered or paged. Same shape as ``sampling_points`` above —
    one annotated queryset, a Q-joined search, two exact filters, 50 to a page.
    """
    q = request.GET.get("q", "").strip()
    facility_type = request.GET.get("facility_type", "").strip()
    activity_status = request.GET.get("activity_status", "").strip()

    base_queryset = _filtered_facilities(q, facility_type, activity_status)

    queryset = base_queryset.annotate(
        sampling_point_count=Count("sampling_points")
    ).order_by("facility_id")

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    n_source, n_tp, n_ds = _facility_population_counts(base_queryset)

    # The map card's head. The map draws FACILITIES and the list
    # counts facilities too — a 1:1 correspondence sampling_points below does
    # not have — so the shared head partial's own branches (all_count /
    # located_count / total_count / result_located_count) say the right thing
    # with no `line` override. `result_pks` is the WHOLE filtered queryset's
    # pks (before pagination), read by OH2O.followResults after every swap.
    filter_words = _facility_filter_words(facility_type, activity_status)

    return list_response(
        request,
        page_template="drinking/facilities.html",
        results_template="drinking/partials/_facility_results.html",
        context={
            "page_obj": page_obj,
            "total_count": paginator.count,
            "n_source": n_source,
            "n_tp": n_tp,
            "n_ds": n_ds,
            "q": q,
            "facility_type": facility_type,
            "activity_status": activity_status,
            **_facility_coverage_context(queryset),
            "filter_words": filter_words,
            "hx_request": bool(request.headers.get("HX-Request")),
        },
    )


# ---------------------------------------------------------------------------
# Detail pages: facility -> sampling point -> sample result
# ---------------------------------------------------------------------------
#
# The three lists above are inventories; these are the records themselves. Each
# is **Bucket 3** (``DESIGN.md "Kinds of page"``): a full-width page of its
# own, reached from a table row rather than from a side pane. So they use plain
# ``render`` + ``get_object_or_404`` and deliberately NOT
# ``core.workspace.detail_response`` — that helper's whole job is the HTMX
# pane-swap branch, and none of these three lists carries a pane to swap into.
#
# **Prepare, never determine** applies here hardest. A one-record page is where
# a limit beside a value would look most natural and be most wrong: nothing on
# these pages compares a result against a ``RegulatoryLimit``.


def _points_with_activity(queryset):
    """Sampling points carrying their latest sample date and result count.

    The same annotation pair ``sampling_points`` uses, for the same reason: one
    query for the whole table rather than two per row. Both annotations walk the
    single point -> events -> results chain, so they cannot inflate each other.
    """
    return queryset.annotate(
        latest_sample_date=Max("events__sample_date"),
        result_count=Count("events__results"),
    ).order_by("ps_code")


@login_required
def facility_detail(request, pk):
    """One facility: what it physically is, its system, its well, its points.

    ``_describe`` is reused rather than re-derived — it attaches the
    plain-English sentence for the facility type and the guard against the
    heading "Distribution System — DISTRIBUTION SYSTEM". It is defined with the
    sampling-point builder further down because that is where it was written;
    both callers want exactly the same two attributes.
    """
    facility = get_object_or_404(
        SystemFacility.objects.select_related("system", "well"), pk=pk
    )
    return render(
        request,
        "drinking/facility_detail.html",
        {
            "facility": _describe(facility),
            "points": _points_with_activity(facility.sampling_points),
            "geojson": _facility_geojson(facility),
        },
    )


@login_required
def facility_add(request):
    """Add a facility by hand.

    A source does not exist for the state's reporting until the district
    engineer assigns it an id, and it does not reach EPA's record, which
    onboarding reads, until later still. This is the door for that gap: the
    operator types the id they were given, the state's name if they have it,
    and their own name for it.

    No system onboarded yet: the page says so and links to Onboard, the same
    shape as ``production_add``, rather than redirecting away from the page
    that was asked for.
    """
    system = WaterSystem.objects.order_by("pwsid").first()
    if system is None:
        return render(request, "drinking/facility_form.html", {"system": None})

    if request.method == "POST":
        form = SystemFacilityForm(request.POST, system=system)
        if form.is_valid():
            facility = form.save()
            return redirect("drinking:facility_detail", pk=facility.pk)
    else:
        form = SystemFacilityForm(system=system)

    return render(
        request,
        "drinking/facility_form.html",
        {"form": form, "system": system, "facility": None},
    )


@login_required
def facility_edit(request, pk):
    """Edit one facility; how much depends on who wrote it.

    A hand-added facility is the operator's throughout, so every field is
    offered. One the federal record wrote offers only the local name and the
    well link: the rest is EPA's as published, and a re-onboarding would
    write it back.
    """
    facility = get_object_or_404(
        SystemFacility.objects.select_related("system"), pk=pk
    )
    if facility.added_by_hand:
        form_class, kwargs = SystemFacilityForm, {"system": facility.system}
    else:
        form_class, kwargs = FacilityLocalNameForm, {}

    if request.method == "POST":
        form = form_class(request.POST, instance=facility, **kwargs)
        if form.is_valid():
            form.save()
            return redirect("drinking:facility_detail", pk=facility.pk)
    else:
        form = form_class(instance=facility, **kwargs)

    return render(
        request,
        "drinking/facility_form.html",
        {"form": form, "system": facility.system, "facility": facility},
    )


@public_in_open_demo
def facilities_geojson(request):
    """Every located facility as a plain GeoJSON FeatureCollection.

    Modeled on ``recharge/views.py::recharge_sites_geojson`` — the same shape the
    platform's other three Bucket-3 overview maps read, with no new caching
    machinery.

    **Only facilities with a location appear.** An unlocated facility is omitted
    entirely rather than emitted at ``(0, 0)``; saying out loud how much of the
    inventory that leaves off the map is the PAGE's job, not this endpoint's.

    **The properties carry identity and position, nothing else.** No result, no
    limit, no count of detections, no compliance status. A popup is a view, and
    "prepare, never determine" (see the module docstring) binds it exactly as
    hard as it binds the detail pages: this says what a thing IS and where it is,
    never a judgment about its water.

    ``ps_codes`` is what makes this ONE map instead of two. The sampling points
    drawn here are not a second set of dots at the same coordinates — they are
    what each facility's popup names.
    """
    facilities = (
        SystemFacility.objects
        .filter(location__isnull=False)
        .select_related("system")
        .annotate(point_count=Count("sampling_points"))
        .prefetch_related(
            Prefetch(
                "sampling_points",
                queryset=SamplingPoint.objects.order_by("ps_code"),
                to_attr="ordered_points",
            )
        )
        .order_by("facility_id")
    )

    features = []
    for facility in facilities:
        features.append({
            "type": "Feature",
            "geometry": json.loads(facility.location.geojson),
            "properties": {
                "pk": facility.pk,
                "facility_id": facility.facility_id,
                "name": facility.name,
                # The map label, code prefix stripped. `name` is
                # optional here (a facility can carry only its federal id), so
                # this is null rather than an empty string when absent — a
                # coalesce expression skips null and falls through to the next
                # field, but treats "" as a real (empty) value and stops there.
                "label": map_label(facility.name) if facility.name else None,
                # The published LABEL, not the two-letter code.
                "facility_type": facility.get_facility_type_display(),
                "system_name": facility.system.name,
                "pwsid": facility.system.pwsid,
                "point_count": facility.point_count,
                "ps_codes": [p.ps_code for p in facility.ordered_points],
            },
        })

    return HttpResponse(
        json.dumps({"type": "FeatureCollection", "features": features}),
        content_type="application/json",
    )
