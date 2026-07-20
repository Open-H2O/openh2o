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

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from core.workspace import list_response
from drinking import envirofacts, envirofacts_mapping, importer
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


@login_required
@require_POST
def onboard_lookup(request):
    """Fetch and map a PWSID's federal record, and render the review. Writes nothing."""
    raise NotImplementedError


@login_required
@require_POST
def onboard_commit(request):
    """Re-fetch the session's PWSID from cache and write the system + facilities."""
    raise NotImplementedError
