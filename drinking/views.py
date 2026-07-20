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
surface. The write path is the lab-file import at the bottom of this module,
plus Django admin for one-off corrections.
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from core.workspace import list_response
from drinking import envirofacts, envirofacts_mapping, glossary, importer
from drinking.ps_codes import compose_ps_code
from drinking.models import (
    ACTIVITY_STATUS_CHOICES,
    FACILITY_TYPE_CHOICES,
    OWNER_TYPE_CHOICES,
    POINT_TYPE_CHOICES,
    PRIMARY_SOURCE_CHOICES,
    PWS_TYPE_CHOICES,
    WATER_TYPE_CHOICES,
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
    """Attach the plain-English sentence for what this facility physically is.

    Set on the instance rather than resolved in the template so the same
    description is available whether the panel is rendered by the page or
    swapped in by an add.
    """
    facility.plain_type = glossary.facility_type_plain(facility.facility_type)
    # EPA's name is often just the type again ("DISTRIBUTION SYSTEM" on a
    # facility already typed Distribution System). Showing both produced the
    # heading "Distribution System — DISTRIBUTION SYSTEM", which is the exact
    # code-soup this rewrite exists to remove.
    label = (facility.get_facility_type_display() or "").strip().lower()
    facility.name_adds_nothing = (facility.name or "").strip().lower() == label
    return facility


@login_required
@require_GET
def onboard_points(request, pwsid):
    """The per-facility sampling-point builder.

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
            f"{pwsid} is carried here but has no facilities, so there is "
            "nothing to hang a sampling point on. Re-run the lookup to refresh "
            "its facilities from EPA.",
        )
        return redirect("drinking:onboard")

    # Split rather than list all 35. A real system carries far more facilities
    # than ever take samples — Bakman has 35, of which 14 are sampled — and
    # rendering 21 identical empty forms buries the ones that matter. The empty
    # ones stay reachable behind a toggle; they are not hidden, just not first.
    with_points = [f for f in facilities if f.sampling_points.all()]
    without_points = [f for f in facilities if not f.sampling_points.all()]

    return render(
        request,
        "drinking/onboard_points.html",
        {
            "system": system,
            "facilities": facilities,
            "facilities_with_points": with_points,
            "facilities_without_points": without_points,
            "point_type_choices": POINT_TYPE_CHOICES,
            "point_count": SamplingPoint.objects.filter(
                facility__system=system
            ).count(),
            # Only the abbreviations that actually appear on this page.
            "shorthand": glossary.shorthand_in_use(
                [f.name for f in facilities]
                + [f.facility_id for f in facilities]
                + [p.name for f in facilities for p in f.sampling_points.all()]
            ),
        },
    )


@login_required
@require_POST
def onboard_points_add(request, pwsid):
    """Add one sampling point to one facility. Renders that facility's panel back.

    A duplicate is reported and skipped, not raised: an operator re-walking a
    partially-completed system is the ordinary case, not an error. ``get_or_create``
    rather than an ``exists()`` check so two operators racing the same code get a
    plain "already there" instead of an IntegrityError 500.
    """
    pwsid = (pwsid or "").strip().upper()
    system = WaterSystem.objects.filter(pwsid=pwsid).first()
    if system is None:
        return render(
            request,
            "drinking/partials/_onboard_points.html",
            {"error": f"{pwsid} is not a system carried here."},
        )

    facility = system.facilities.filter(
        pk=(request.POST.get("facility") or "").strip() or None
    ).first()
    if facility is None:
        return render(
            request,
            "drinking/partials/_onboard_points.html",
            {"error": "That facility is not part of this system."},
        )

    panel = {
        "system": system,
        "facility": _describe(facility),
        "point_type_choices": POINT_TYPE_CHOICES,
    }

    point_number = (request.POST.get("point_number") or "").strip()
    name = (request.POST.get("name") or "").strip()
    point_type = (request.POST.get("point_type") or "").strip()

    # Composition is the validator. Rather than re-implementing the rules here
    # (and drifting from them), the ValueError text is shown as-is — it already
    # names which part was wrong and why.
    try:
        ps_code = compose_ps_code(system.pwsid, facility.facility_id, point_number)
    except ValueError as exc:
        return render(
            request,
            "drinking/partials/_onboard_points.html",
            {**panel, "error": str(exc)},
        )

    if point_type and point_type not in dict(POINT_TYPE_CHOICES):
        return render(
            request,
            "drinking/partials/_onboard_points.html",
            {**panel, "error": "That is not a point type this platform carries."},
        )

    point, created = SamplingPoint.objects.get_or_create(
        ps_code=ps_code,
        defaults={"facility": facility, "name": name, "point_type": point_type},
    )

    return render(
        request,
        "drinking/partials/_onboard_points.html",
        {
            **panel,
            "added": point if created else None,
            "duplicate": None if created else point,
        },
    )
