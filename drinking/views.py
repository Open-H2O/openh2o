# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Drinking water views.

The three read surfaces for the PWS domain: the system overview (identity plus
its facilities), the sampling-point inventory, and the sample-result log.

**Prepare, never determine.** No view here compares a result against a limit or
colors a row by it. Showing a result and separately showing what the limit is
are both facts; rendering a verdict is a regulatory determination this platform
does not make. See ``drinking/models.py``.

The three read surfaces are deliberately read-only — no inline ``edit_field``
surface. The write paths are the lab-file import, onboarding, the production
year's add and import (146-04 Task 2) and the facility add and edit forms
(146-04 Task 3) and the sampling schedule's (146-04 Task 4), each a full page
of its own, plus Django admin for one-off
corrections.
"""
import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST
from core.access import public_in_open_demo
from core.map_labels import map_label

from core.workspace import list_response
from drinking import envirofacts, envirofacts_mapping, glossary, importer
from drinking import production_import as production_import_service
from drinking.forms import (
    FacilityLocalNameForm,
    SamplingScheduleForm,
    SystemFacilityForm,
    SystemProductionForm,
)
from drinking.ps_codes import compose_ps_code
from drinking.models import (
    ACTIVITY_STATUS_CHOICES,
    FACILITY_TYPE_CHOICES,
    OWNER_TYPE_CHOICES,
    POINT_TYPE_CHOICES,
    PRIMARY_SOURCE_CHOICES,
    PRODUCTION_TYPE_CHOICES,
    PRODUCTION_UNIT_CHOICES,
    PWS_TYPE_CHOICES,
    WATER_TYPE_CHOICES,
    Analyte,
    SampleResult,
    SamplingPoint,
    SamplingSchedule,
    SystemFacility,
    SystemProduction,
    WaterSystem,
)


logger = logging.getLogger(__name__)


_POPULATION_SPLIT_FIELDS = (
    "population_residential",
    "population_non_transient",
    "population_transient",
)

_CONNECTION_SPLIT_FIELDS = (
    "connections_agricultural",
    "connections_combined",
    "connections_commercial",
    "connections_industrial",
    "connections_residential",
)


@login_required
def overview(request):
    """The water system's front door: who it is, what EPA publishes, where to go.

    Not an inventory. The 61-row facility table that used to live at the bottom
    of this page moved to :func:`facilities`, where it can be searched; what is
    left is the identity card, EPA's two published aggregates, and three counts
    that route to the three lists.

    Usually one system row, like SiteConfig — but a table, so a wholesaler or a
    consecutive system can be carried alongside.
    """
    systems = list(
        WaterSystem.objects
        .annotate(facility_count=Count("facilities", distinct=True))
        .order_by("pwsid")
    )

    # Two aggregate queries keyed by system id, zipped on in Python. NOT a
    # per-system .count() inside the loop (which grows with the row count), and
    # NOT a second Count() annotation on the queryset above: multiple joins on
    # one queryset multiply each other's counts, which is the exact bug the
    # sampling-points view's own comment warns about. Three queries total, at
    # one system or at thirty.
    point_counts = {
        row["facility__system"]: row["n"]
        for row in SamplingPoint.objects
        .values("facility__system")
        .annotate(n=Count("id"))
    }
    result_counts = {
        row["event__sampling_point__facility__system"]: row["n"]
        for row in SampleResult.objects
        .values("event__sampling_point__facility__system")
        .annotate(n=Count("id"))
    }

    # 146-04 Task 4 (D8): the one "next due" line. One query for every
    # system's dated rows, earliest first, and the first per system kept in
    # Python -- the same no-per-system-query rule as the two aggregates above.
    next_due = {}
    for row in (
        SamplingSchedule.objects.filter(next_due__isnull=False)
        .select_related("analyte")
        .order_by("next_due", "pk")
    ):
        next_due.setdefault(row.system_id, row)

    for system in systems:
        system.next_due_row = next_due.get(system.pk)
        system.sampling_point_count = point_counts.get(system.pk, 0)
        system.result_count = result_counts.get(system.pk, 0)
        # One boolean each, computed here rather than as eight chained {% if %}s
        # in the template. The splits render only when the deployment actually
        # holds one; otherwise the page says where they come from, because a
        # sentence naming the missing source is information and a column of
        # em-dashes is not.
        system.has_population_splits = any(
            getattr(system, name) is not None for name in _POPULATION_SPLIT_FIELDS
        )
        system.has_connection_splits = any(
            getattr(system, name) is not None for name in _CONNECTION_SPLIT_FIELDS
        )
        # 123-02: the state each step of the sequence is in, computed here and
        # NEVER written into the template. The demonstration happens to hold 61
        # facilities, 27 points and 22,367 results; an onboarded system holds
        # none of those, and a numeral typed into the eyebrow would be a
        # sentence that is right on exactly one deployment.
        #
        # Derived from the three counts already gathered above — no fourth
        # aggregate query. Step 1 is done by definition inside the loop: this
        # system exists, so it was onboarded (or admin-created, which is the
        # same evidence).
        system.step_onboard_done = True
        system.step_points_done = system.sampling_point_count > 0
        system.step_results_done = system.result_count > 0

    return render(request, "drinking/overview.html", {"systems": systems})


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


def _sampling_points_head_line(
    *, all_count, mapped_facility_count, total_count, result_located_count, q, filter_words
):
    """The Sampling Points card head's `line` override (143-07).

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
        # Plain words (Brent, staging 18:24 PDT: "at a located facility, on
        # the map" read as machine prose). The Facilities head's own shape.
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
    if not result_located_count:
        tail = "the map shows none of them"
    elif total_count == 1:
        tail = "the map shows it"
    else:
        tail = f"the map shows {result_located_count:,} of them"
    return f"{total_count:,} of {all_count:,} {match_verb} {clause}; {tail}"


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

    queryset = base_queryset.annotate(
        sampling_point_count=Count("sampling_points")
    ).order_by("facility_id")

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # The card head's population line (R-063): one facility_type count query
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

    # The map card's head (143-07). The map draws FACILITIES and the list
    # counts facilities too — a 1:1 correspondence sampling_points below does
    # not have — so the shared head partial's own branches (all_count /
    # located_count / total_count / result_located_count) say the right thing
    # with no `line` override. `result_pks` is the WHOLE filtered queryset's
    # pks (before pagination), read by OH2O.followResults after every swap.
    facility_type_label = dict(FACILITY_TYPE_CHOICES).get(facility_type, "")
    activity_status_label = dict(ACTIVITY_STATUS_CHOICES).get(activity_status, "")
    filter_bits = []
    if facility_type_label:
        filter_bits.append(f"of type “{facility_type_label}”")
    if activity_status_label:
        filter_bits.append(f"with status “{activity_status_label}”")

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
            # Read _present_choices' docstring before touching either of these.
            "facility_type_choices": _present_choices(
                "facility_type", FACILITY_TYPE_CHOICES
            ),
            "activity_status_choices": _present_choices(
                "activity_status", ACTIVITY_STATUS_CHOICES
            ),
            "has_any": SystemFacility.objects.exists(),
            # 123-02: the coverage counts for the sentence under the map, the
            # same pair `sampling_points` computes below and for the same
            # reason — the Merced demonstration's figures are not any other
            # system's, and an Envirofacts-onboarded system starts at zero
            # because EPA publishes no coordinates at all.
            #
            # Deliberately UNFILTERED by `q` / `facility_type` /
            # `activity_status`. This sentence is about what the platform
            # HOLDS, not about what the current search matched.
            "total_facility_count": SystemFacility.objects.count(),
            "mapped_facility_count": SystemFacility.objects.filter(
                location__isnull=False
            ).count(),
            # The head partial's own names for the same two counts, plus the
            # FILTERED located count (143-07, Ruling A: the map now follows
            # the list, so this is the number that actually lands on it).
            "all_count": SystemFacility.objects.count(),
            "located_count": SystemFacility.objects.filter(
                location__isnull=False
            ).count(),
            "result_pks": list(queryset.values_list("pk", flat=True)),
            "result_located_count": queryset.filter(
                location__isnull=False
            ).count(),
            "filter_words": " and ".join(filter_bits),
            "hx_request": bool(request.headers.get("HX-Request")),
        },
    )


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

    # 123-02: the PWSID the empty state's "Build sampling points" button opens
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
    has_any_point = SamplingPoint.objects.exists()
    points_pwsid = ""
    if not has_any_point:
        pwsids = list(WaterSystem.objects.values_list("pwsid", flat=True)[:2])
        if len(pwsids) == 1:
            points_pwsid = pwsids[0]

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

    # The map card's head (143-07): the map draws FACILITIES, so the pks the
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
            all_count=point_total_count,
            mapped_facility_count=mapped_facility_count,
            total_count=paginator.count,
            result_located_count=result_located_count,
            q=q,
            filter_words=f"of type “{point_type_label}”" if point_type_label else "",
        )
        if mapped_facility_count
        else None
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
            "point_total_count": point_total_count,
            "mapped_point_count": mapped_point_count,
            "total_facility_count": total_facility_count,
            "mapped_facility_count": mapped_facility_count,
            "all_count": point_total_count,
            "located_count": mapped_facility_count,
            "result_pks": result_pks,
            "result_located_count": result_located_count,
            "line": head_line,
            "hx_request": bool(request.headers.get("HX-Request")),
        },
    )


def group_results_by_event(rows):
    """Fold an ordered run of sample results into one block per sample event.

    R-070 / R-071: an event IS one date at one point, so the results log says
    that once per event (a ``tr.row-group`` divider) instead of repeating the
    date and the PS Code on every row. ``rows`` must already be ordered so a
    given event's results are contiguous -- ``results`` below orders
    ``-event__sample_date, event__sampling_point__ps_code, event_id,
    analyte__name`` for exactly that reason -- this function only folds runs
    of the same ``event_id``; it does not sort.

    ``total`` is the event's FULL result count, read from ONE ``Count`` query
    over every event id present in ``rows``, never a query per group and
    never a per-row loop. ``shown`` is how many of that event's rows are in
    THIS ``rows`` list, so a group whose rows are split across two pages of
    the caller's own pagination prints its divider again on the second page,
    with ``shown`` less than ``total`` saying so.

    Pure on purpose -- rows in, groups out, no request and no queryset touched
    beyond the one Count -- so the sampling-point detail page (143-08 Task 3)
    can call it again on its own ``recent`` slice of one point's history.
    """
    rows = list(rows)
    if not rows:
        return []

    event_ids = []
    seen_events = set()
    for row in rows:
        if row.event_id not in seen_events:
            seen_events.add(row.event_id)
            event_ids.append(row.event_id)

    totals = dict(
        SampleResult.objects.filter(event_id__in=event_ids)
        .order_by()
        .values("event_id")
        .annotate(n=Count("id"))
        .values_list("event_id", "n")
    )

    groups = []
    for row in rows:
        if not groups or groups[-1]["event"].pk != row.event_id:
            groups.append({
                "event": row.event,
                "rows": [],
                "shown": 0,
                "total": totals.get(row.event_id, 0),
            })
        groups[-1]["rows"].append(row)
        groups[-1]["shown"] += 1
    return groups


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
        # An event IS one date at one point (R-070/R-071): ordering by point
        # and event id after the date keeps a whole event's rows contiguous,
        # so two points sampled the same day render as two groups rather than
        # interleaving by analyte the way the old `analyte__name`-only
        # tiebreak did.
        .order_by(
            "-event__sample_date",
            "event__sampling_point__ps_code",
            "event_id",
            "analyte__name",
        )
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
            "result_groups": group_results_by_event(page_obj.object_list),
            "analyte_id": analyte_id,
            "point_id": point_id,
            "date_from": date_from,
            "date_to": date_to,
            "analytes": Analyte.objects.filter(results__isnull=False).distinct(),
            "sampling_points": SamplingPoint.objects.order_by("ps_code"),
            "has_any": SampleResult.objects.exists(),
        },
    )


# ---------------------------------------------------------------------------
# Detail pages: facility -> sampling point -> sample result
# ---------------------------------------------------------------------------
#
# The three lists above are inventories; these are the records themselves. Each
# is **Bucket 3** (``docs/2.0-UX-PATTERN-SPEC.md``): a full-width page of its
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
    """Add a facility by hand (146-04 Task 3, D9).

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


def _facility_geojson(facility, extra_properties=None):
    """One facility as a one-feature ``FeatureCollection``, or ``None``.

    ``None``, deliberately, and never an empty ``FeatureCollection``.
    ``OH2O.detailPaneMap`` hides its whole card when the ``json_script`` element
    is absent, and shows an empty grey rectangle when the element is present but
    carries no features — which is 40 of the 61 facilities in the demonstration,
    and EVERY facility of a system onboarded through Envirofacts, since EPA
    publishes no coordinates at all.

    A Python object, not a ``json.dumps`` string: the template escapes it through
    ``json_script`` so a facility name can never break out of the ``<script>``.

    **Identity and position only.** Same rule as ``facilities_geojson`` and for
    the same reason — a popup is a view, so no result, limit or compliance status
    is carried here.
    """
    if facility.location is None:
        return None
    properties = {
        "facility_id": facility.facility_id,
        "name": facility.name,
        # The published LABEL, not the two-letter code (ISS-008).
        "facility_type": facility.get_facility_type_display(),
        "system_name": facility.system.name,
    }
    properties.update(extra_properties or {})
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [facility.location.x, facility.location.y],
                },
                "properties": properties,
            }
        ],
    }


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
                # 143-07 Step 0: the map label, code prefix stripped. `name` is
                # optional here (a facility can carry only its federal id), so
                # this is null rather than an empty string when absent — a
                # coalesce expression skips null and falls through to the next
                # field, but treats "" as a real (empty) value and stops there.
                "label": map_label(facility.name) if facility.name else None,
                # The published LABEL, not the two-letter code. ISS-008 was filed
                # for exactly this on the monitoring charts.
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
            # 143-08 Task 3 (R-069): the SAME helper the results log calls
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


#: The State Water Board's Consumer Confidence Report viewer.
#:
#: Verified live 2026-07-27: returns HTTP 200 ``application/pdf``. It is a
#: CALIFORNIA service, which is why ``_ccr_url`` gates on the PWSID's prefix —
#: a New Mexico or federal PWSID would compose a link that 404s while looking
#: authoritative, and an authoritative-looking dead link is worse than none.
CCR_VIEWER_URL = "https://ear.waterboards.ca.gov/Home/ViewCCR?PwsID={pwsid}&Year={year}"


def _ccr_is_published(year, today):
    """Has the CCR covering ``year`` been delivered yet?

    40 CFR 141.155(a): a community water system delivers its Consumer Confidence
    Report **by July 1 annually**, and that report covers the **previous**
    calendar year. So the report for year Y does not exist until July 1 of Y+1 —
    a sample taken this year has no annual report at all, and one taken last year
    has none until this July.

    Measured against the live viewer for CA2410009 on 2026-07-28, which this rule
    reproduces exactly: 2020-2024 and 2025 all answer 200, and 2026 answers 404.
    """
    return (today.year, today.month) >= (year + 1, 7)


def _ccr_url(system, sample_date, today=None):
    """The system's annual CCR for the year this sample was taken, or None.

    **This is not the sample's own lab sheet**, and the page must not imply it
    is. Per-sample analytical PDFs are published by nobody: Envirofacts is
    tabular REST with no document endpoint, and California labs submit through
    CLIP as data. The system's annual report for that year is the nearest
    published document that exists, so it is offered as exactly that.

    Two gates, and both exist to avoid the same failure — an authoritative-looking
    link that 404s:

    * **The state.** The viewer is a California State Water Board service, so a
      New Mexico or federal PWSID would compose a link to a report that service
      never held.
    * **The year.** See ``_ccr_is_published``. The demonstration data runs to
      2026-05-21, so without this gate the newest samples on the busiest surface
      in the module all link to a 404.
    """
    pwsid = (system.pwsid or "").strip().upper()
    if not pwsid.startswith("CA") or sample_date is None:
        return None
    if not _ccr_is_published(sample_date.year, today or timezone.localdate()):
        return None
    return CCR_VIEWER_URL.format(pwsid=pwsid, year=sample_date.year)


@login_required
def result_detail(request, pk):
    """One lab result, whole.

    The results log shows six columns of a record that carries far more — method,
    laboratory, ELAP certification, reporting level, analysis date, collector,
    chain of custody. This is the page those columns were hidden behind.

    **No RegulatoryLimit is loaded or rendered here.** A one-record page is
    exactly where a limit beside a value would look most natural, and showing one
    is a verdict in everything but the wording. See the module docstring.
    """
    result = get_object_or_404(
        SampleResult.objects.select_related(
            "analyte",
            "analyte__observed_property",
            "event",
            "event__sampling_point",
            "event__sampling_point__facility",
            "event__sampling_point__facility__system",
        ),
        pk=pk,
    )
    system = result.event.sampling_point.facility.system

    # 143-08 Task 3 (R-055): the lead panel's third peer. The most recent
    # earlier finding of the SAME analyte at the SAME point -- never a
    # different point or a different analyte, which would compare findings
    # that answer different questions. `sample_date__lte` plus `exclude(pk=)`
    # rather than a strict `<` catches two results filed under the same date
    # (a re-run, a duplicate row) and still resolves to one deterministic row,
    # ordered by pk so the tie always favors the later-written one.
    previous_finding = (
        SampleResult.objects
        .filter(
            analyte=result.analyte,
            event__sampling_point=result.event.sampling_point,
            event__sample_date__lte=result.event.sample_date,
        )
        .exclude(pk=result.pk)
        .select_related("event")
        .order_by("-event__sample_date", "-pk")
        .first()
    )
    finding_count = SampleResult.objects.filter(
        analyte=result.analyte,
        event__sampling_point=result.event.sampling_point,
    ).count()

    return render(
        request,
        "drinking/result_detail.html",
        {
            "result": result,
            "event": result.event,
            "point": result.event.sampling_point,
            "facility": result.event.sampling_point.facility,
            "system": system,
            "previous_finding": previous_finding,
            "finding_count": finding_count,
            "ccr_url": _ccr_url(system, result.event.sample_date),
            "ccr_year": result.event.sample_date.year if result.event.sample_date else "",
        },
    )


# ---------------------------------------------------------------------------
# Lab-file import: page -> preview -> commit
# ---------------------------------------------------------------------------
#
# Thin glue over ``drinking.importer``'s four functions, mirroring the
# infrastructure import flow's shape and error idiom. The one deliberate
# difference: infrastructure offers a manual column-mapping step, and this does
# not. The DDW SDWIS.CSV layout is a published spec, so auto-mapping is right
# essentially always; a mapping UI would be five clicks of ceremony to confirm
# what the header row already said. When a REQUIRED column cannot be found, the
# preview says exactly which one rather than offering a grid of dropdowns.


@login_required
@require_GET
def import_page(request):
    """The lab-file upload page (the dropzone)."""
    return render(request, "drinking/import.html", {"max_rows": importer.MAX_ROWS})


def _unknown_ps_code_routes(validated):
    """Which PS Codes the file names that this deployment does not carry.

    The single most likely real-world failure: a partially-walked system. On its
    own that dead-ends in a row error with nowhere to go, so each unknown code is
    resolved back to the system it belongs to and, when that system is onboarded,
    to the sampling-point builder that can create it.

    Detected structurally — a row that carried a PS Code but got no
    ``sampling_point_id`` — rather than by matching the error string, so a
    reworded message cannot silently switch this off.

    The PWSID is the first segment of the composite by construction. A code too
    malformed to split is still reported, just without a link: it is a typo in
    the file, not a missing sampling point.
    """
    unknown = sorted(
        {
            item["data"]["ps_code"]
            for item in validated
            if item["data"].get("ps_code")
            and item["data"].get("sampling_point_id") is None
        }
    )
    if not unknown:
        return []

    onboarded = set(WaterSystem.objects.values_list("pwsid", flat=True))
    routes = []
    for ps_code in unknown:
        pwsid = ps_code.split("_")[0] if "_" in ps_code else ""
        routes.append(
            {
                "ps_code": ps_code,
                "pwsid": pwsid,
                "is_onboarded": pwsid in onboarded,
            }
        )
    return routes


def _preview_rows(rows, mapping, validated):
    """Zip validated rows back to their source values for the preview table."""
    def src(row, field):
        col = mapping.get(field)
        return (row.get(col) or "").strip() if col else ""

    shaped = []
    for item in validated:
        row = rows[item["index"]]
        shaped.append(
            {
                "index": item["index"] + 1,  # 1-based: matches the file's rows
                "ps_code": src(row, "ps_code"),
                "sample_date": src(row, "sample_date"),
                "analyte": src(row, "analyte_name"),
                "result": src(row, "result"),
                "unit": src(row, "unit"),
                "errors": item["errors"],
                "warnings": item["warnings"],
            }
        )
    return shaped


@login_required
@require_POST
def import_preview(request):
    """Parse, auto-map and validate the upload; show what a commit would do."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": "No file provided. Choose a CSV of lab results."},
        )

    try:
        parsed = importer.parse_upload(uploaded, uploaded.name)
    except ImportError as exc:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": str(exc)},
        )

    columns = parsed["columns"]
    rows = parsed["rows"]
    mapping = importer.auto_map_columns(columns)

    missing = importer.missing_required(mapping)
    if missing:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {
                "error": (
                    "This file is missing column"
                    f"{'s' if len(missing) > 1 else ''} the import needs: "
                    f"{', '.join(missing)}. The expected layout is the state's "
                    "own SDWIS.CSV lab-results format."
                )
            },
        )

    validated = importer.validate_rows(rows, mapping)
    preview = _preview_rows(rows, mapping, validated)

    error_rows = [r for r in preview if r["errors"]]
    warning_rows = [r for r in preview if r["warnings"] and not r["errors"]]
    duplicate_count = sum(
        1 for item in validated if item["data"].get("is_duplicate")
    )
    new_analytes = sorted(
        {
            item["data"]["analyte_name"]
            for item in validated
            if not item["errors"] and item["data"].get("analyte_id") is None
            and item["data"].get("analyte_name")
        }
    )
    committable = sum(
        1
        for item in validated
        if not item["errors"] and not item["data"].get("is_duplicate")
    )

    return render(
        request,
        "drinking/partials/_import_preview.html",
        {
            "recognised": [
                (importer.FIELD_LABELS[field], col)
                for field, col in mapping.items()
            ],
            "preview_rows": preview[:200],
            "shown_count": min(len(preview), 200),
            "error_rows": error_rows,
            "warning_rows": warning_rows,
            "row_count": len(rows),
            "error_count": len(error_rows),
            "duplicate_count": duplicate_count,
            "new_analytes": new_analytes,
            "committable": committable,
            "unknown_ps_codes": _unknown_ps_code_routes(validated),
            "rows_json": json.dumps(rows),
        },
    )


@login_required
@require_POST
def import_commit(request):
    """Re-validate the posted rows and write them."""
    try:
        rows = json.loads(request.POST.get("rows_json", "") or "[]")
    except json.JSONDecodeError:
        rows = []

    if not rows:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": "No rows to import — please re-upload your file and try again."},
        )

    # Re-enforce the row cap on COMMIT, not just on preview. `rows_json` is a
    # hidden field the browser posts back, so a logged-in user can hand-edit it
    # to submit far more rows than the upload parser allowed. The upload cap is
    # meaningless if commit does not check it too.
    if len(rows) > importer.MAX_ROWS:
        return render(
            request,
            "drinking/partials/_import_result.html",
            {
                "error": (
                    f"Import is {len(rows)} rows, over the {importer.MAX_ROWS}-row "
                    "cap. Re-upload a smaller file."
                )
            },
        )

    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return render(
            request,
            "drinking/partials/_import_result.html",
            {"error": "The import data was malformed — please re-upload your file."},
        )

    # Re-derive the mapping and re-validate from scratch. The preview's verdict
    # is never trusted: between preview and commit another operator may have
    # added the very sampling point a row was rejected for, or the duplicate a
    # row is about to become.
    columns = list(rows[0].keys())
    mapping = importer.auto_map_columns(columns)
    validated = importer.validate_rows(rows, mapping)
    counts = importer.commit_rows(validated)
    # After the commit, so a file that lands nothing still records the agency
    # it names for the system its rows resolved to (146-04 Task 3).
    agency = importer.record_regulating_agency(rows, mapping, validated)

    skipped = [
        {"index": item["index"] + 1, "errors": item["errors"]}
        for item in validated
        if item["errors"]
    ]

    return render(
        request,
        "drinking/partials/_import_result.html",
        {
            "counts": counts,
            "skipped": skipped,
            "total": len(validated),
            "agency": agency,
        },
    )


# ---------------------------------------------------------------------------
# System onboarding: page -> lookup -> commit
# ---------------------------------------------------------------------------
#
# The operator-facing door onto Phase 79's Envirofacts adapter. Same three-step
# shape as the lab import above, for the same reason: nothing is written until
# the operator has seen exactly what a commit would do, including what it would
# SKIP.
#
# **The session holds only the PWSID.** Sessions are `signed_cookies` (ISS-069)
# — there is no server-side store, the session IS the cookie, and a browser caps
# a cookie at roughly 4 KB. Bakman alone returns 36 facilities against a ~45-field
# WaterSystem; stashing the mapped payloads would blow that ceiling, and the
# failure mode is a silently dropped or truncated cookie rather than a clean
# exception — you would be debugging "the wizard forgets everything on step 2".
#
# Re-fetching on commit costs nothing: `fetch_water_system` / `fetch_facilities`
# / `fetch_geographic_area` are cache-backed by `EnvirofactsCache` (30-day TTL),
# so the commit step reads the same cached rows the review step read, with no
# second network call. It also guarantees review and commit see the same bytes,
# which a session copy could not if the cache refreshed in between.

#: The ONLY thing the wizard puts in the session. Read the block above before
#: adding a second key that carries a payload.
SESSION_KEY_ONBOARD_PWSID = "drinking_onboard_pwsid"


@login_required
@require_GET
def onboard_page(request):
    """The PWSID entry screen — one input and an honest note about scope."""
    return render(request, "drinking/onboard.html", {})


def _code_label(code, choices):
    """Show the published label, falling back to the raw code.

    A code that survived ``_coded`` is always in the vocabulary, so the fallback
    only fires for a value the mapping deliberately dropped — in which case
    showing the code beats showing an empty cell.
    """
    return dict(choices).get(code, code)


def _collect_federal_record(pwsid):
    """Fetch all three EPA tables for one PWSID and map them. **Writes nothing.**

    The single place the wizard talks to Envirofacts, so review and commit ask
    the same question the same way. Every call is cache-backed, so the commit
    step's repeat of this work is a DB read, not a second federal round-trip.

    Returns the raw rows alongside the mapped ones: ``commit_system`` takes raw
    payloads (it maps internally, so a mapping fix reaches it without a caller
    change), while the review screen needs the mapped values plus the two raw
    EPA aggregates that are deliberately never written.
    """
    warnings = []

    system_row = envirofacts.fetch_water_system(pwsid)
    facility_rows = envirofacts.fetch_facilities(pwsid)
    geography_row = envirofacts.fetch_geographic_area(pwsid)

    mapped_system = envirofacts_mapping.map_water_system(system_row, warnings=warnings)

    facilities = []
    skipped = []
    for row in facility_rows:
        try:
            mapped = envirofacts_mapping.map_facility(row, warnings=warnings)
        except envirofacts_mapping.UnmappableFacility as exc:
            # Kept as its own list rather than folded into `warnings`: a skip is
            # a facility that will not exist, which is a different fact from a
            # code that was not recognised.
            skipped.append(str(exc))
            continue
        facilities.append(
            {
                "facility_id": mapped["facility_id"],
                "epa_facility_id": mapped.get("epa_facility_id", ""),
                "name": mapped.get("name", ""),
                "facility_type": _code_label(
                    mapped.get("facility_type", ""), FACILITY_TYPE_CHOICES
                ),
                "water_type": _code_label(
                    mapped.get("water_type", ""), WATER_TYPE_CHOICES
                ),
                "is_source": mapped.get("is_source", False),
            }
        )

    return {
        "pwsid": pwsid,
        "system_row": system_row,
        "facility_rows": facility_rows,
        "mapped_system": mapped_system,
        "facilities": facilities,
        "skipped": skipped,
        "geography": envirofacts_mapping.map_geography(geography_row),
        "warnings": warnings,
    }


def _review_context(collected):
    """Shape one collected federal record for the review partial."""
    mapped = collected["mapped_system"]
    raw = collected["system_row"]
    pwsid = collected["pwsid"]

    existing = WaterSystem.objects.filter(pwsid=pwsid).first()

    return {
        "pwsid": pwsid,
        "name": mapped.get("name", ""),
        "activity_status": _code_label(
            mapped.get("activity_status", ""), ACTIVITY_STATUS_CHOICES
        ),
        "pws_type": _code_label(mapped.get("pws_type", ""), PWS_TYPE_CHOICES),
        "owner_type": _code_label(mapped.get("owner_type", ""), OWNER_TYPE_CHOICES),
        "primary_source": _code_label(
            mapped.get("primary_source_code", ""), PRIMARY_SOURCE_CHOICES
        ),
        "mailing": mapped,
        # Straight off EPA's row, NOT off the model: these two aggregates are
        # shown because an operator should see what EPA holds, and are not
        # written because the model carries a 3-way and a 5-way split that no
        # single total can honestly be divided into.
        "epa_population_served": raw.get("population_served_count"),
        "epa_service_connections": raw.get("service_connections_count"),
        "geography": collected["geography"],
        "facilities": collected["facilities"],
        "facility_count": len(collected["facilities"]),
        "epa_facility_count": len(collected["facility_rows"]),
        "skipped": collected["skipped"],
        "warnings": collected["warnings"],
        "already_onboarded": existing is not None,
        "existing_facility_count": (
            existing.facilities.count() if existing is not None else 0
        ),
    }


@login_required
@require_POST
def onboard_lookup(request):
    """Fetch and map a PWSID's federal record, and render the review. Writes nothing."""
    pwsid = (request.POST.get("pwsid") or "").strip().upper()
    if not pwsid:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "empty", "error": "Enter a PWSID to look up."},
        )

    # Specific first. PwsidNotFound and EnvirofactsUnavailable both subclass
    # EnvirofactsError, so putting the base class first would swallow both and
    # tell an operator holding a perfectly good PWSID that EPA has no such
    # system. Order here is load-bearing, not stylistic.
    try:
        collected = _collect_federal_record(pwsid)
    except envirofacts.PwsidNotFound as exc:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "not_found", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsUnavailable as exc:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "unavailable", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsError as exc:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "service_error", "error": str(exc), "pwsid": pwsid},
        )

    # Only the id, and only after a lookup actually succeeded. See the block at
    # the top of this section on why nothing else goes in here.
    request.session[SESSION_KEY_ONBOARD_PWSID] = pwsid

    return render(
        request, "drinking/partials/_onboard_review.html", _review_context(collected)
    )


@login_required
@require_POST
def onboard_commit(request):
    """Re-fetch the session's PWSID from cache and write the system + facilities."""
    pwsid = request.session.get(SESSION_KEY_ONBOARD_PWSID)
    if not pwsid:
        # A stale tab or an expired cookie is an ordinary event, not an error.
        # Sending an operator to a 500 for closing their laptop overnight would
        # be the wizard's fault, not theirs.
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"expired": True},
        )

    # Same order as the lookup, and for the same reason. The fetch is a cache
    # hit (EnvirofactsCache, 30-day TTL) so this costs a DB read, not a second
    # federal round-trip — but the cache can legitimately have been refreshed or
    # the service can have gone down between the two steps, so all three
    # failures still have to be handled here.
    try:
        collected = _collect_federal_record(pwsid)
    except envirofacts.PwsidNotFound as exc:
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"error_kind": "not_found", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsUnavailable as exc:
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"error_kind": "unavailable", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsError as exc:
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"error_kind": "service_error", "error": str(exc), "pwsid": pwsid},
        )

    # `commit_system` is already @transaction.atomic, so a bad facility payload
    # cannot leave a half-onboarded system behind. Deliberately NOT wrapped in a
    # second transaction and given no compensating cleanup — both would fight a
    # guarantee that already holds. It also takes the RAW payloads and maps them
    # itself, which is why `_collect_federal_record` keeps them.
    result = envirofacts_mapping.commit_system(
        collected["system_row"], collected["facility_rows"]
    )

    del request.session[SESSION_KEY_ONBOARD_PWSID]

    return render(
        request,
        "drinking/partials/_onboard_result.html",
        {
            "result": result,
            "pwsid": pwsid,
            "epa_facility_count": len(collected["facility_rows"]),
        },
    )


# ---------------------------------------------------------------------------
# Sampling-point builder: the second half of onboarding
# ---------------------------------------------------------------------------
#
# Onboarding creates a system and its facilities. That looks finished and is
# not: `drinking.importer` matches every lab row on PS Code, and a PS Code lives
# on a SamplingPoint. Until points exist, a real lab file cannot import at all —
# every row is an unknown-PS-Code error. This is the surface that closes it.
#
# **Points are created here and only here** — by explicit operator action, never
# as an import side effect. The importer's refusal to invent structure is the
# guarantee that makes an unknown PS Code meaningful, so an "auto-create on
# import" convenience would quietly destroy the thing it appears to help.
#
# **Distribution-system program points need no special case.** LCR and DBPR
# points hang off the distribution system rather than a source facility, but the
# distribution system arrives from EPA as an ordinary SystemFacility
# (`facility_id` = `DST`). So `CA1010001_DST_LCR` is a normal point on a normal
# facility. The only thing this owes it is copy that does not assume "facility"
# means "well", and a point-number field that accepts letters.


def _facility_panels(system):
    """Every committed facility for one system, with the points already on it."""
    return (
        system.facilities
        .prefetch_related("sampling_points")
        .order_by("facility_id")
    )


def _describe(facility):
    """Flag whether EPA's name for this facility repeats its type label.

    Set on the instance rather than resolved in the template so the same answer
    is available whether the page renders it or an add's response swaps it in.

    This used to also attach a sentence saying what the facility physically is
    ("A drilled well. Water comes up out of the ground here."). Deleted
    2026-08-06 (ISS-129): the reader is a water district operator and the panel
    heading already carries EPA's own label. DESIGN.md copy rule 11.
    """
    # EPA's name is often just the type again ("DISTRIBUTION SYSTEM" on a
    # facility already typed Distribution System). Showing both produced the
    # heading "Distribution System — DISTRIBUTION SYSTEM", which is the exact
    # code-soup this rewrite exists to remove. Applied to the facility select's
    # option text too (143-08 Task 4), the one other place this heading shape
    # is built.
    label = (facility.get_facility_type_display() or "").strip().lower()
    facility.name_adds_nothing = (facility.name or "").strip().lower() == label
    return facility


def _facility_select_order(facilities):
    """Sources first, then the rest, each group in facility-id order.

    143-08 Task 4 (design A): the builder's facility select is the one place
    order matters, since a source facility is disproportionately what an
    operator is adding a point to (it is where water enters the system, the
    thing a program most often samples). ``sorted`` is stable, so within each
    group ``_facility_panels``'s own facility-id order survives.
    """
    return sorted(facilities, key=lambda f: not f.is_source)


def _points_listed_context(system, facilities):
    """The grouped-table state for the builder's listed-points card.

    Shared by the full-page GET and by ``onboard_points_add``'s POST response
    so the two can never drift apart the way a hand-spliced row would: the
    add view calls this on a freshly refetched facility list, never patches
    the group it just added to.

    A facility with no points is left out of ``point_groups`` entirely (the
    head's "n of m" already says such facilities exist); it never disappears
    from the system, only from this table.
    """
    point_groups = []
    n_with = 0
    point_count = 0
    for facility in facilities:
        points = list(facility.sampling_points.all())
        if not points:
            continue
        n_with += 1
        point_count += len(points)
        point_groups.append({"facility": facility, "points": points})
    return {
        "system": system,
        "pwsid": system.pwsid,
        "facilities": facilities,
        "point_groups": point_groups,
        "point_count": point_count,
        "n_with": n_with,
    }


@login_required
@require_GET
def onboard_points(request, pwsid):
    """The system-wide sampling-point builder: one form, one grouped table.

    Guarded rather than rendered empty: a system that was never onboarded has no
    facilities to hang points on, and an empty page would read as "this system
    has no facilities" instead of "you have not onboarded this system yet".
    """
    pwsid = (pwsid or "").strip().upper()
    system = WaterSystem.objects.filter(pwsid=pwsid).first()

    if system is None:
        messages.warning(
            request,
            f"{pwsid} has not been onboarded yet, so it has no facilities to "
            "add sampling points to. Look the system up first.",
        )
        return redirect("drinking:onboard")

    facilities = [_describe(f) for f in _facility_panels(system)]
    if not facilities:
        messages.warning(
            request,
            f"{pwsid} has no facilities, so no sampling point can be added. "
            "Re-run the lookup to refresh its facilities from EPA.",
        )
        return redirect("drinking:onboard")

    # ONE ordered list, reused everywhere on the page: the select's options,
    # the grouped table's row order, and the "n of m" count line's length.
    # Sorted once here rather than per-consumer so the select and the table
    # below it never present two different orders for the same facilities.
    facilities = _facility_select_order(facilities)

    return render(
        request,
        "drinking/onboard_points.html",
        {
            "system": system,
            "point_type_choices": POINT_TYPE_CHOICES,
            # Only the abbreviations that actually appear on this page.
            "shorthand": glossary.shorthand_in_use(
                [f.name for f in facilities]
                + [f.facility_id for f in facilities]
                + [p.name for f in facilities for p in f.sampling_points.all()]
            ),
            **_points_listed_context(system, facilities),
        },
    )


@login_required
@require_POST
def onboard_points_add(request, pwsid):
    """Add one sampling point to one facility. Renders the WHOLE listed-points
    table back, regrouped, plus the status alert out of band.

    A duplicate is reported and skipped, not raised: an operator re-walking a
    partially-completed system is the ordinary case, not an error. ``get_or_create``
    rather than an ``exists()`` check so two operators racing the same code get a
    plain "already there" instead of an IntegrityError 500.

    143-08 Task 4 (design A): every branch below renders
    ``_onboard_points_listed.html``, never the bare alert the old per-facility
    panel returned on an error: the operator's whole table has to stay on
    screen (``hx-target="#points-listed"``, ``hx-swap="outerHTML"``) whatever
    the outcome, with the alert riding along as an out-of-band swap into
    ``#point-add-status``.
    """
    pwsid = (pwsid or "").strip().upper()
    system = WaterSystem.objects.filter(pwsid=pwsid).first()
    if system is None:
        return render(
            request,
            "drinking/partials/_onboard_points_listed.html",
            {
                "system": None,
                "pwsid": pwsid,
                "facilities": [],
                "point_groups": [],
                "point_count": 0,
                "n_with": 0,
                "error": f"{pwsid} is not a system carried here.",
            },
        )

    def _listed(**status):
        facilities = _facility_select_order(
            [_describe(f) for f in _facility_panels(system)]
        )
        return render(
            request,
            "drinking/partials/_onboard_points_listed.html",
            {**_points_listed_context(system, facilities), **status},
        )

    facility = system.facilities.filter(
        pk=(request.POST.get("facility") or "").strip() or None
    ).first()
    if facility is None:
        return _listed(error="That facility is not part of this system.")

    point_number = (request.POST.get("point_number") or "").strip()
    name = (request.POST.get("name") or "").strip()
    point_type = (request.POST.get("point_type") or "").strip()

    # Composition is the validator. Rather than re-implementing the rules here
    # (and drifting from them), the ValueError text is shown as-is — it already
    # names which part was wrong and why.
    try:
        ps_code = compose_ps_code(system.pwsid, facility.facility_id, point_number)
    except ValueError as exc:
        return _listed(error=str(exc))

    if point_type and point_type not in dict(POINT_TYPE_CHOICES):
        return _listed(error="That is not a point type this platform carries.")

    point, created = SamplingPoint.objects.get_or_create(
        ps_code=ps_code,
        defaults={"facility": facility, "name": name, "point_type": point_type},
    )

    return _listed(
        added=point if created else None,
        duplicate=None if created else point,
    )


# ---------------------------------------------------------------------------
# Production by month and source (146-04 Task 2, D7, ISS-184)
# ---------------------------------------------------------------------------
#
# The record shape 2's operator never had: what the system produced, by
# month and by source. Same three-step shape as the lab import above (page,
# preview, commit) for the bulk door; a plain ModelForm for the by-hand door.
# The importer's own rules -- two layouts, unit conversions, dedup -- live in
# ``drinking/production_import.py``.

PRODUCTION_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
    12: "December",
}


@login_required
def production(request):
    """The year table: production and delivery by month and source.

    Months down, type codes across, in the unit each type was reported in
    plus acre-feet -- the shape a small system's operator wants: the same
    figures the state's own eAR already has from them, read back in one
    table instead of scattered across a year of import rows.

    No system onboarded yet: the empty state names the two files this door
    takes (the eAR export, the operator's own log) rather than an empty
    table with nothing to explain it.
    """
    system = WaterSystem.objects.first()
    if system is None:
        return render(request, "drinking/production.html", {"system": None})

    years = list(
        SystemProduction.objects.filter(system=system)
        .order_by("-year")
        .values_list("year", flat=True)
        .distinct()
    )

    year_param = request.GET.get("year", "").strip()
    if year_param.isdigit():
        year = int(year_param)
    else:
        year = years[0] if years else None

    type_codes = [code for code, _label in PRODUCTION_TYPE_CHOICES]
    records = (
        SystemProduction.objects.filter(system=system, year=year)
        if year is not None
        else SystemProduction.objects.none()
    )
    by_key = {(r.month, r.type_code): r for r in records}

    # A record with month=None (the whole year reported as one figure) is
    # its own row at the foot of the table, never folded into a numbered
    # month it was never attached to.
    has_annual_row = any(month is None for month, _type_code in by_key)

    rows = []
    for month_num in range(1, 13):
        rows.append(
            {
                "month": month_num,
                "label": PRODUCTION_MONTH_NAMES[month_num],
                "cells": [by_key.get((month_num, code)) for code in type_codes],
            }
        )
    if has_annual_row:
        rows.append(
            {
                "month": None,
                "label": "Whole year (one figure)",
                "cells": [by_key.get((None, code)) for code in type_codes],
            }
        )

    totals = []
    for code in type_codes:
        column = [record for (_month, t), record in by_key.items() if t == code]
        gallons = sum((r.volume_gallons for r in column), Decimal("0"))
        totals.append(
            {
                "type_code": code,
                # Gallons are the state's own reported unit and arrive as
                # whole numbers (`Water Produced or Delivered` carries no
                # fractional gallon in either layout), so this is rounded in
                # the view rather than through `floatformat`; there is
                # nothing a formatter would do here that `int()` does not.
                # Acre-feet is different: it is a conversion this platform
                # performs (325,851 gallons per acre-foot), so it goes
                # through `floatformat:2` in the template and carries its own
                # figure-ledger row -- `FIG-drinking-002` (this total) and
                # `FIG-drinking-003` (the grand total below), both in
                # `docs/figure-ledger-2026-09.md`.
                "gallons": gallons,
                "gallons_whole": int(gallons.to_integral_value()),
                "acre_feet": sum((r.volume_acre_feet for r in column), Decimal("0")),
            }
        )
    grand_total_gallons = sum((t["gallons"] for t in totals), Decimal("0"))
    grand_total_af = sum((t["acre_feet"] for t in totals), Decimal("0"))

    return render(
        request,
        "drinking/production.html",
        {
            "system": system,
            "years": years,
            "year": year,
            "type_codes": type_codes,
            "type_columns": PRODUCTION_TYPE_CHOICES,
            "rows": rows,
            "totals": totals,
            "grand_total_gallons": grand_total_gallons,
            "grand_total_gallons_whole": int(grand_total_gallons.to_integral_value()),
            "grand_total_af": grand_total_af,
            "has_any": SystemProduction.objects.filter(system=system).exists(),
        },
    )


@login_required
def production_add(request):
    """Add one month's production or delivery by hand.

    No system onboarded yet: the page itself says so and links to Onboard,
    the same way the year table's own empty state does, rather than bouncing
    the visitor away from the page they asked for -- a redirect is a page
    nobody can read, and `/drinking/onboard/` is not what "Add month"
    promised (`tests/test_platform_readability.py`).
    """
    system = WaterSystem.objects.first()
    if system is None:
        return render(request, "drinking/production_form.html", {"system": None})

    if request.method == "POST":
        form = SystemProductionForm(request.POST, system=system)
        if form.is_valid():
            record = form.save()
            return redirect(f"{reverse('drinking:production')}?year={record.year}")
    else:
        form = SystemProductionForm(system=system)

    return render(
        request, "drinking/production_form.html", {"form": form, "system": system}
    )


@login_required
@require_GET
def production_import_page(request):
    """The production-import landing page: the eAR export, or the operator's own log."""
    return render(
        request,
        "drinking/production_import.html",
        {"max_rows": production_import_service.MAX_ROWS},
    )


def _production_import_settings_context(*, unit_for_blank="", operator_year="",
                                          operator_unit="G"):
    return {
        "unit_choices": PRODUCTION_UNIT_CHOICES,
        "unit_for_blank": unit_for_blank,
        "operator_year": operator_year,
        "operator_unit": operator_unit,
    }


@login_required
@require_POST
def production_import_preview(request):
    """Parse the upload (or re-run with changed mapping-step settings) and

    show what a commit would do -- every skipped row and every error -- with
    nothing written yet (dry_run=True throughout).
    """
    system = WaterSystem.objects.first()
    if system is None:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": "Onboard a water system first."},
        )

    uploaded = request.FILES.get("file")
    rows_json_raw = request.POST.get("rows_json", "")

    if uploaded:
        try:
            columns, rows = production_import_service.parse_csv(uploaded, uploaded.name)
        except ImportError as exc:
            return render(
                request,
                "drinking/partials/_production_import_result.html",
                {"error": str(exc)},
            )
    elif rows_json_raw:
        try:
            rows = json.loads(rows_json_raw)
        except json.JSONDecodeError:
            rows = []
        if not rows:
            return render(
                request,
                "drinking/partials/_production_import_result.html",
                {"error": "No rows to preview -- please re-upload your file and try again."},
            )
        columns = list(rows[0].keys())
    else:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": "No file provided. Choose a production CSV."},
        )

    if len(rows) > production_import_service.MAX_ROWS:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {
                "error": (
                    f"Import is {len(rows)} rows, over the "
                    f"{production_import_service.MAX_ROWS}-row cap. Re-upload a "
                    "smaller file."
                )
            },
        )

    try:
        layout = production_import_service.recognise_layout(columns)
    except ImportError as exc:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": str(exc)},
        )

    unit_for_blank = request.POST.get("unit_for_blank", "").strip()
    operator_year_raw = request.POST.get("operator_year", "").strip()
    operator_year = int(operator_year_raw) if operator_year_raw.isdigit() else None
    operator_unit = request.POST.get("operator_unit", "").strip() or "G"

    result = production_import_service.import_production_rows(
        columns, rows, system=system, layout=layout,
        unit_for_blank=unit_for_blank or None,
        operator_year=operator_year, operator_unit=operator_unit,
        dry_run=True,
    )

    context = _production_import_settings_context(
        unit_for_blank=unit_for_blank, operator_year=operator_year_raw,
        operator_unit=operator_unit,
    )
    context.update(result)
    context["rows_json"] = json.dumps(rows)
    context["row_count"] = len(rows)
    return render(
        request, "drinking/partials/_production_import_preview.html", context
    )


@login_required
@require_POST
def production_import_commit(request):
    """Re-run the confirmed mapping-step settings against the parsed rows and write them."""
    system = WaterSystem.objects.first()
    if system is None:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": "Onboard a water system first."},
        )

    try:
        rows = json.loads(request.POST.get("rows_json", "") or "[]")
    except json.JSONDecodeError:
        rows = []

    if not rows:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": "No rows to import -- please re-upload your file and try again."},
        )

    columns = list(rows[0].keys())
    try:
        layout = production_import_service.recognise_layout(columns)
    except ImportError as exc:
        return render(
            request,
            "drinking/partials/_production_import_result.html",
            {"error": str(exc)},
        )

    unit_for_blank = request.POST.get("unit_for_blank", "").strip()
    operator_year_raw = request.POST.get("operator_year", "").strip()
    operator_year = int(operator_year_raw) if operator_year_raw.isdigit() else None
    operator_unit = request.POST.get("operator_unit", "").strip() or "G"

    try:
        result = production_import_service.import_production_rows(
            columns, rows, system=system, layout=layout,
            unit_for_blank=unit_for_blank or None,
            operator_year=operator_year, operator_unit=operator_unit,
            dry_run=False,
        )
    except Exception as exc:
        logger.exception("production import commit failed")
        context = _production_import_settings_context(
            unit_for_blank=unit_for_blank, operator_year=operator_year_raw,
            operator_unit=operator_unit,
        )
        context["rows_json"] = json.dumps(rows)
        context["row_count"] = len(rows)
        context["error"] = f"Nothing was created: {type(exc).__name__}: {exc}"
        return render(
            request, "drinking/partials/_production_import_preview.html", context,
            status=200,
        )

    return render(
        request, "drinking/partials/_production_import_result.html", result
    )


# ---------------------------------------------------------------------------
# The sampling schedule (146-04 Task 4, D8)
# ---------------------------------------------------------------------------


@login_required
def schedule(request):
    """The operator's sampling checklist, by the date they set.

    Earliest date first (the model's ordering), so a date that has passed
    leads the list; rows with no date last. A passed date is worded as the
    operator's own ("past the date you set") and never as a verdict: the
    platform holds the schedule and does not judge it.
    """
    system = WaterSystem.objects.order_by("pwsid").first()
    rows = (
        SamplingSchedule.objects.filter(system=system)
        .select_related("analyte", "sampling_point")
        if system is not None
        else SamplingSchedule.objects.none()
    )
    return render(
        request,
        "drinking/schedule.html",
        {"system": system, "rows": rows, "today": timezone.localdate()},
    )


@login_required
def schedule_add(request):
    """Add one row to the schedule; no system yet says Onboard first."""
    system = WaterSystem.objects.order_by("pwsid").first()
    if system is None:
        return render(request, "drinking/schedule_form.html", {"system": None})

    if request.method == "POST":
        form = SamplingScheduleForm(request.POST, system=system)
        if form.is_valid():
            form.save()
            return redirect("drinking:schedule")
    else:
        form = SamplingScheduleForm(system=system)
    return render(
        request,
        "drinking/schedule_form.html",
        {"form": form, "system": system, "row": None},
    )


@login_required
def schedule_edit(request, pk):
    """Edit one schedule row: typically the two dates, after a sample is taken."""
    row = get_object_or_404(SamplingSchedule.objects.select_related("system"), pk=pk)
    if request.method == "POST":
        form = SamplingScheduleForm(request.POST, instance=row, system=row.system)
        if form.is_valid():
            form.save()
            return redirect("drinking:schedule")
    else:
        form = SamplingScheduleForm(instance=row, system=row.system)
    return render(
        request,
        "drinking/schedule_form.html",
        {"form": form, "system": row.system, "row": row},
    )
