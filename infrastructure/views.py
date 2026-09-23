# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Infrastructure views.

The operational setup surfaces for placing water infrastructure on the map:
the type-aware "add" flow that creates a well, surface point of diversion, or
recharge site from a drawn location, plus the CSV upload/import path. These are
the admin-facing screens an operator uses to stand up an agency's features
before any accounting runs.
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point, Polygon
from django.db.models import Q
from django.http import Http404, HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.modules import is_enabled
from core.validation import FieldValidationError, coerce_decimal, coerce_int
from infrastructure import importer
from parcels.models import Parcel
from wells.models import (
    ACCURACY_BAND_CHOICES,
    DWR_DIRECT_OR_ESTIMATE_CHOICES,
    DWR_EXTRACTION_METHOD_CHOICES,
    MEASUREMENT_METHOD_CHOICES,
    PUMP_TYPE_CHOICES,
    Well,
    WellIrrigatedParcel,
)


# preselect type -> (list-view url name, breadcrumb/back label)
ADD_TYPE_BACK = {
    "well": ("wells:list", "Extraction Wells"),
    "diversion": ("surface:pod_list", "Surface Diversions"),
    "storage": ("recharge:list", "Recharge Areas"),
    "recharge_site": ("recharge:list", "Recharge Areas"),
}
ADD_TYPE_LABEL = {
    "well": "Well",
    "diversion": "Diversion",
    # "Storage" alone made the breadcrumb read "Add Storage" beside a sentence
    # saying "a storage pond or tank" — the same self-contradiction ISS-134 was
    # filed about, one line smaller.
    "storage": "Storage Pond",
    "recharge_site": "Recharge Site",
}

#: The full name of each type, as the operator reads it on the page. ADD_TYPE_LABEL
#: above is the terse breadcrumb/button form ("Add Well", "Create Well"); these are
#: what a sentence calls the thing.
ADD_TYPE_LONG_LABEL = {
    "well": "groundwater well",
    "diversion": "surface water diversion",
    "storage": "storage pond or tank",
    "recharge_site": "recharge site",
}

#: The module that owns each add/import type. Phase 87: every ADD_TYPE_BACK value
#: is fed to `reverse()`, and `surface:pod_list` / `recharge:list` do not resolve
#: when their module is omitted — so an unfiltered `?type=diversion` was a
#: NoReverseMatch 500 on a page that is otherwise fine. This is not an import and
#: not a `{% url %}` in a template, so neither the import sweep nor the template
#: guard test can see it. `storage` maps to `recharge` because both storage and
#: recharge_site create a RechargeSite (see infrastructure_add below).
ADD_TYPE_MODULE = {
    "well": "wells",
    "diversion": "surface",
    "storage": "recharge",
    "recharge_site": "recharge",
}


#: Fallback order for an unrecognised or unavailable ``?type``. ``well`` first,
#: because it was the hardcoded fallback before Phase 88 and is still the right
#: default wherever it exists.
ADD_TYPE_ORDER = ("well", "diversion", "storage", "recharge_site")

logger = logging.getLogger(__name__)

#: Shown, verbatim, on a 404 from the bulk importer (ISS-179): `?type=parcel`
#: (also `use_area`, `usearea`) used to fall through to `_supported_type`'s
#: "unrecognised value" fallback and silently serve the Well importer instead.
#: Shape 6's own correction found it. `supported_add_types()` is the list of
#: truth for what this screen actually takes; use areas are a different door.
UNSUPPORTED_IMPORT_TYPE_MESSAGE = (
    "use areas are imported with `import_parcels` (docs/DATA-IMPORT.md); the "
    "screen importer takes wells, points of diversion, storage and recharge sites"
)


def supported_add_types() -> tuple:
    """The add/import types this deployment can actually serve, in fallback order."""
    return tuple(t for t in ADD_TYPE_ORDER if is_enabled(ADD_TYPE_MODULE[t]))


def _supported_type(raw):
    """Normalize a ?type / infra_type value to one this deployment can serve.

    A type whose owning module is dropped falls back to the first type that IS
    available, rather than reaching `reverse()` on a route that never
    registered. The matching cards in add.html are guarded on the same
    condition, so the type is not offered either.

    **The fallback used to be the literal ``"well"``, which Phase 88 turned into
    a bug rather than a safety net**: with `wells` demoted, an unrecognised type
    fell back to a type whose route no longer exists, so the guard handed the
    NoReverseMatch straight back. Returns ``None`` when no type is available at
    all — the caller turns that into a 404, because a page for adding
    infrastructure to a deployment that tracks none of it has no subject.
    """
    available = supported_add_types()
    raw = (raw or "").strip()
    if raw in available:
        return raw
    return available[0] if available else None


def _add_context(infra_type, **extra):
    """Build the type-aware context for add.html (GET and POST-error re-renders)."""
    infra_type = _supported_type(infra_type)
    if infra_type is None:
        raise Http404(
            "This deployment runs none of the modules that own an infrastructure "
            "type (wells, surface diversions, recharge sites), so there is "
            "nothing this page could add."
        )
    back_name, back_label = ADD_TYPE_BACK[infra_type]
    context = {
        "preselect_type": infra_type,
        "preselect_label": ADD_TYPE_LABEL[infra_type],
        "preselect_long_label": ADD_TYPE_LONG_LABEL[infra_type],
        # The OTHER types this deployment can serve, so the page can offer a way
        # out without asking the question it already has the answer to. Built
        # from supported_add_types() rather than the full list, for the same
        # reason the type cards were guarded in Phase 87: offering a type whose
        # module is dropped is a NoReverseMatch 500, not a dead link.
        "other_add_types": [
            {"value": t, "label": ADD_TYPE_LONG_LABEL[t]}
            for t in supported_add_types()
            if t != infra_type
        ],
        "back_url": reverse(back_name),
        "back_label": back_label,
        "measurement_method_choices": MEASUREMENT_METHOD_CHOICES,
        "pump_type_choices": PUMP_TYPE_CHOICES,
        # 146-05 S2: DWR's own extraction-method row, offered blank by default.
        "dwr_extraction_method_choices": DWR_EXTRACTION_METHOD_CHOICES,
        "dwr_direct_or_estimate_choices": DWR_DIRECT_OR_ESTIMATE_CHOICES,
        "accuracy_band_choices": ACCURACY_BAND_CHOICES,
        # 146-02 D2: the diversion card's "Water right" select. Local import,
        # guarded, the same reason `infra_type == "diversion"` branches below
        # import `surface.models` locally -- `surface` is truly optional
        # (Phase 87) and this context is built for every add-page render, not
        # only a diversion one.
        "water_rights": _water_rights_for_select(),
        # 146-03 Task 3: the diversion card's "Contract unit" select.
        "contract_unit_choices": _contract_unit_choices(),
    }
    context.update(extra)
    return context


def _water_rights_for_select():
    """Every WaterRight, right_id order, or an empty list without `surface`."""
    if not is_enabled("surface"):
        return []
    from surface.models import WaterRight

    return WaterRight.objects.order_by("right_id")


def _contract_unit_choices():
    """PointOfDiversion's own contract-unit choices, or none without `surface`."""
    if not is_enabled("surface"):
        return []
    from surface.models import PointOfDiversion

    return PointOfDiversion.CONTRACT_UNIT_CHOICES


@login_required
def infrastructure_add(request):
    if request.method == "GET":
        return render(
            request,
            "infrastructure/add.html",
            _add_context(request.GET.get("type", "").strip()),
        )

    # Normalised, not taken raw: a POST naming a demoted module's type would
    # otherwise write rows into a switched-off module and then redirect to a
    # route that does not exist.
    infra_type = _supported_type(request.POST.get("infra_type", ""))
    if infra_type is None:
        raise Http404("No infrastructure type is available in this configuration.")
    name = request.POST.get("name", "").strip()
    status = request.POST.get("status", "active")
    notes = request.POST.get("notes", "").strip()
    geometry_json = request.POST.get("geometry_json", "")
    parcel_id = request.POST.get("parcel_id", "")

    # ISS-171: a well operator with a WCR in hand types the point instead of
    # clicking the map. A click or a drag always fills geometry_json client
    # side, so this is strictly a fallback for the typed-coordinate path — and
    # it runs BEFORE the geometry path below, building the same Point a click
    # would have, so _parse_point/_parse_polygon downstream need no changes.
    # Silently ignored (not an error) when it does not parse: a stray value in
    # one box with the map still empty is the map's story to tell, not this
    # fallback's.
    if not geometry_json:
        lat_raw = request.POST.get("latitude", "").strip()
        lng_raw = request.POST.get("longitude", "").strip()
        if lat_raw and lng_raw:
            try:
                lat_val = float(lat_raw)
                lng_val = float(lng_raw)
            except ValueError:
                lat_val = lng_val = None
            if (
                lat_val is not None
                and -90 <= lat_val <= 90
                and -180 <= lng_val <= 180
            ):
                geometry_json = json.dumps(
                    {"type": "Point", "coordinates": [lng_val, lat_val]}
                )

    parcel = None
    if parcel_id:
        try:
            parcel = Parcel.objects.get(pk=parcel_id)
        except Parcel.DoesNotExist:
            parcel = None

    def _error(error_type, message):
        # Re-render the Add form with a friendly error AND the submitted values +
        # drawn geometry preserved, so a failed submit never loses the user's work.
        return render(
            request,
            "infrastructure/add.html",
            _add_context(error_type, error=message, submitted=request.POST),
        )

    if infra_type == "well":
        location = _parse_point(geometry_json)
        if not location:
            return _error("well", "A point location is required for wells.")
        try:
            depth_ft = coerce_decimal(request.POST.get("depth_ft"), "Depth (ft)", min_value=0)
            capacity_gpm = coerce_decimal(request.POST.get("capacity_gpm"), "Capacity (gpm)", min_value=0)
            year_pumping_began = coerce_int(
                request.POST.get("year_pumping_began"), "Year Pumping Began",
                min_value=1850, max_value=timezone.now().year,
            )
            casing_diameter_in = coerce_decimal(request.POST.get("casing_diameter_in"), "Casing Diameter (in)", min_value=0)
            screen_top_ft = coerce_decimal(request.POST.get("screen_top_ft"), "Screen Top (ft)", min_value=0)
            screen_bottom_ft = coerce_decimal(request.POST.get("screen_bottom_ft"), "Screen Bottom (ft)", min_value=0)
            tested_yield_gpm = coerce_decimal(request.POST.get("tested_yield_gpm"), "Tested Yield (gpm)", min_value=0)
        except FieldValidationError as exc:
            return _error("well", str(exc))
        well = Well.objects.create(
            name=name,
            location=location,
            depth_ft=depth_ft,
            capacity_gpm=capacity_gpm,
            status=status,
            owner_name=request.POST.get("owner_name", ""),
            year_pumping_began=year_pumping_began,
            measurement_method=request.POST.get("measurement_method", ""),
            dwr_extraction_method=request.POST.get("dwr_extraction_method", ""),
            dwr_direct_or_estimate=request.POST.get("dwr_direct_or_estimate", ""),
            accuracy_band=request.POST.get("accuracy_band", ""),
            wcr_number=request.POST.get("wcr_number", ""),
            state_well_number=request.POST.get("state_well_number", ""),
            casing_diameter_in=casing_diameter_in,
            casing_material=request.POST.get("casing_material", ""),
            screen_top_ft=screen_top_ft,
            screen_bottom_ft=screen_bottom_ft,
            tested_yield_gpm=tested_yield_gpm,
            pump_type=request.POST.get("pump_type", ""),
            notes=notes,
        )
        if parcel:
            WellIrrigatedParcel.objects.create(well=well, parcel=parcel)
        return redirect("wells:detail", pk=well.pk)

    elif infra_type == "diversion":
        # Local import: `surface` is an optional module (Phase 87), so this must
        # not run at module scope. This branch is only reachable when the add
        # form offered a diversion type, which it does not do without the module.
        from surface.models import PointOfDiversion, PointOfDiversionParcel, WaterRight

        location = _parse_point(geometry_json)
        if not location:
            return _error("diversion", "A point location is required for diversions.")
        try:
            max_rate_cfs = coerce_decimal(request.POST.get("max_rate_cfs"), "Max Rate (cfs)", min_value=0)
            # 146-03 Task 3: left blank, the model's own default (11.22, the
            # statute's gallons a minute) applies -- so a blank submission
            # must NOT pass `None` to create(), which would overwrite that
            # default with a NOT NULL column's illegal value.
            miners_inch_gpm = coerce_decimal(
                request.POST.get("miners_inch_gpm"), "Miner's Inch (gpm)", min_value=0
            )
        except FieldValidationError as exc:
            return _error("diversion", str(exc))
        # 146-02 D2: optional at creation, the same select the POD page's own
        # "Water right" panel offers -- a blank, stale or tampered value falls
        # back to unlinked rather than a 500, since this is a plain <select>
        # value, not a get_object_or_404'd URL segment.
        water_right_id = request.POST.get("water_right_id", "").strip()
        water_right = (
            WaterRight.objects.filter(pk=water_right_id).first()
            if water_right_id
            else None
        )
        pod_kwargs = dict(
            name=name,
            location=location,
            water_right=water_right,
            stream_name=request.POST.get("stream_name", ""),
            max_rate_cfs=max_rate_cfs,
            status=status,
            notes=notes,
            # 146-03 Task 3: the 145-01 memo's crosswalk layer -- the ditch
            # tender's own alias and contract unit for this headgate.
            local_name=request.POST.get("local_name", "").strip(),
            contract_unit=request.POST.get("contract_unit", "").strip(),
        )
        if miners_inch_gpm is not None:
            pod_kwargs["miners_inch_gpm"] = miners_inch_gpm
        pod = PointOfDiversion.objects.create(**pod_kwargs)
        if parcel:
            PointOfDiversionParcel.objects.create(point_of_diversion=pod, parcel=parcel)
        return redirect("surface:pod_list")

    elif infra_type in ("recharge_site", "storage"):
        # Local import: `recharge` is an optional module, so this must not run at
        # module scope (ISS-072). This branch is only reachable when the add form
        # offered a recharge type, which it does not do without the module.
        from recharge.models import RechargeSite

        location = _parse_point(geometry_json)
        geometry = _parse_polygon(geometry_json)

        if not location and not geometry:
            return _error(infra_type, "A location or polygon is required.")

        if geometry and not location:
            location = geometry.centroid

        try:
            capacity_acre_feet = coerce_decimal(
                request.POST.get("capacity_acre_feet"), "Capacity (acre-feet)", min_value=0
            )
        except FieldValidationError as exc:
            return _error(infra_type, str(exc))

        site_type = request.POST.get("site_type", "spreading_basin")
        if infra_type == "storage":
            site_type = request.POST.get("storage_type", "storage_pond")

        site = RechargeSite.objects.create(
            name=name,
            location=location,
            geometry=geometry,
            site_type=site_type,
            capacity_acre_feet=capacity_acre_feet,
            status=status,
            operator=request.POST.get("operator", ""),
            notes=notes,
        )
        return redirect("recharge:detail", pk=site.pk)

    return _error(infra_type, "Invalid infrastructure type.")


# ---------------------------------------------------------------------------
# Bulk import: page -> preview/map -> commit
# ---------------------------------------------------------------------------


def _import_type(raw):
    """Normalize a ?type / infra_type value to a supported import type.

    **Only partly `_supported_type(raw)`** (ISS-179). A BLANK type, nobody
    named one, e.g. the bare `/infrastructure/import/` the URLconf crawl and a
    stray internal link both reach, still falls back to the first available
    type exactly as `_supported_type` does; that half of the fallback was never
    the bug and a page landing there with no type at all reasonably shows
    something rather than a 404. What must NOT fall back is a type that IS a
    real value and simply is not one this deployment serves: `?type=parcel`
    (also `use_area`, `usearea`) named an actual, wrong door and
    `_supported_type`'s "anything I don't recognise" fallback silently served
    the Well importer instead. Shape 6's own correction is what caught it.
    Returns the type unchanged when it is one this deployment actually serves,
    `None` for an unrecognised NON-BLANK value. The three callers below turn
    `None` into a 404 with `UNSUPPORTED_IMPORT_TYPE_MESSAGE`, never a fallback
    to a different importer than the one asked for. `supported_add_types()`
    stays the list of truth.
    """
    raw = (raw or "").strip()
    if not raw:
        return _supported_type(raw)
    return raw if raw in supported_add_types() else None


@login_required
@require_GET
def infrastructure_import(request):
    """Bulk import landing page (the file dropzone)."""
    infra_type = _import_type(request.GET.get("type"))
    if infra_type is None:
        return HttpResponseNotFound(
            UNSUPPORTED_IMPORT_TYPE_MESSAGE, content_type="text/plain"
        )
    back_name, back_label = ADD_TYPE_BACK[infra_type]
    return render(
        request,
        "infrastructure/import.html",
        {
            "infra_type": infra_type,
            "infra_label": ADD_TYPE_LABEL[infra_type],
            "back_url": reverse(back_name),
            "back_label": back_label,
            # The OTHER types this deployment can serve, built exactly as
            # `_add_context` builds `other_add_types` (R-130) — so the import
            # page and the add page read as one pair, not two designs.
            "other_import_types": [
                {"value": t, "label": ADD_TYPE_LONG_LABEL[t]}
                for t in supported_add_types()
                if t != infra_type
            ],
        },
    )


@login_required
@require_POST
def infrastructure_import_preview(request):
    """Parse the uploaded file, auto-map its columns, return the mapping UI."""
    infra_type = _import_type(request.POST.get("infra_type"))
    if infra_type is None:
        return HttpResponseNotFound(
            UNSUPPORTED_IMPORT_TYPE_MESSAGE, content_type="text/plain"
        )
    uploaded = request.FILES.get("file")
    if not uploaded:
        return render(
            request,
            "infrastructure/partials/_import_result.html",
            {"error": "No file provided. Choose a CSV, GeoJSON, shapefile (.zip), or KML."},
        )

    try:
        parsed = importer.parse_upload(uploaded, uploaded.name)
    except ImportError as exc:
        return render(
            request,
            "infrastructure/partials/_import_result.html",
            {"error": str(exc)},
        )

    columns = parsed["columns"]
    rows = parsed["rows"]
    mapping = importer.auto_map_columns(columns, infra_type)

    # Pre-shape for the template (Django can't index a dict by a loop variable):
    # one row per model field with its auto-detected guess, and a plain grid of
    # the first few data rows aligned to `columns`.
    field_rows = [
        {"field": field, "label": label, "guess": mapping.get(field, "")}
        for field, label in importer.import_fields(infra_type)
    ]
    sample_table = [[row.get(col, "") for col in columns] for row in rows[:5]]
    # 146-02 D2: the sample table's OWN header, separate from `columns` (which
    # the field-mapping <select>s above also iterate as the file's real source
    # columns -- appending a synthetic entry there would offer it as a
    # selectable, non-existent column).
    sample_columns = _diversion_water_right_preview_column(
        infra_type, rows, mapping, columns, sample_table
    )

    return render(
        request,
        "infrastructure/partials/_import_mapping.html",
        {
            "infra_type": infra_type,
            "infra_label": ADD_TYPE_LABEL[infra_type],
            "columns": columns,
            "sample_columns": sample_columns,
            "field_rows": field_rows,
            "sample_table": sample_table,
            "sample_count": len(sample_table),
            "row_count": len(rows),
            "rows_json": json.dumps(rows),
        },
    )


def _diversion_water_right_preview_column(infra_type, rows, mapping, columns, sample_table):
    """Append "Water right (resolved)" to the sample preview, diversion only.

    146-02 D2: the preview shows the resolved right per row, so an operator
    sees a typo'd APPL_ID before committing rather than after. Mutates
    `sample_table`'s rows in place (one cell each) and returns the header row
    to show above them -- `columns` itself must stay untouched, since the
    field-mapping step's <select>s also iterate it as the file's real source
    columns.
    """
    if infra_type != "diversion" or not mapping.get("water_right"):
        return columns

    existing_rights = {}
    if is_enabled("surface"):
        from surface.models import WaterRight

        existing_rights = dict(WaterRight.objects.values_list("right_id", "pk"))

    right_col = mapping["water_right"]
    for i, row in enumerate(rows[: len(sample_table)]):
        raw = (row.get(right_col) or "").strip()
        if not raw:
            resolved = "(none)"
        elif raw in existing_rights:
            resolved = raw
        else:
            resolved = f"not found: {raw}"
        sample_table[i].append(resolved)

    return list(columns) + ["Water right (resolved)"]


def _columns_from_rows(rows):
    """Union of every row's keys, first-seen order (mirrors importer._features_to_rows)."""
    seen = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _commit_failure_context(infra_type, rows, mapping, exc):
    """Rebuild the mapping-step context after a commit-time crash (ISS-179).

    The same shape `infrastructure_import_preview` renders the first time,
    from the `rows_json` and confirmed `mapping` the crashed POST already
    carried, so the operator can fix a mapping and press Create again
    instead of re-uploading the file. `error` is the one thing added;
    `_import_mapping.html` prints it above the table.
    """
    columns = _columns_from_rows(rows)
    field_rows = [
        {"field": field, "label": label, "guess": mapping.get(field, "")}
        for field, label in importer.import_fields(infra_type)
    ]
    sample_table = [[row.get(col, "") for col in columns] for row in rows[:5]]
    return {
        "infra_type": infra_type,
        "infra_label": ADD_TYPE_LABEL[infra_type],
        "columns": columns,
        "field_rows": field_rows,
        "sample_table": sample_table,
        "sample_count": len(sample_table),
        "row_count": len(rows),
        "rows_json": json.dumps(rows),
        "error": f"Nothing was created: {type(exc).__name__}: {exc}",
    }


@login_required
@require_POST
def infrastructure_import_commit(request):
    """Validate the confirmed mapping against the parsed rows and bulk-create."""
    infra_type = _import_type(request.POST.get("infra_type"))
    if infra_type is None:
        return HttpResponseNotFound(
            UNSUPPORTED_IMPORT_TYPE_MESSAGE, content_type="text/plain"
        )

    try:
        rows = json.loads(request.POST.get("rows_json", "") or "[]")
    except json.JSONDecodeError:
        rows = []

    if not rows:
        return render(
            request,
            "infrastructure/partials/_import_result.html",
            {"error": "No rows to import — please re-upload your file and try again."},
        )

    # Re-enforce the row cap on COMMIT, not just on preview. rows_json is a hidden
    # field the browser posts back, so a logged-in user can hand-edit it to submit
    # far more rows than the upload parser allowed — a cheap way to push tens of
    # thousands of rows through on a 2-4GB VPS. The upload cap is meaningless if
    # commit doesn't check it too. (Raw payload size is separately bounded by
    # Django's DATA_UPLOAD_MAX_MEMORY_SIZE before this view runs.)
    if len(rows) > importer.MAX_ROWS:
        return render(
            request,
            "infrastructure/partials/_import_result.html",
            {"error": (
                f"Import is {len(rows)} rows, over the {importer.MAX_ROWS}-row cap. "
                "Re-upload a smaller file."
            )},
        )

    # Rebuild the field -> column mapping from the confirmed <select> values.
    mapping = {
        key[len("map:"):]: val
        for key, val in request.POST.items()
        if key.startswith("map:") and val
    }

    existing_reg_ids = set()
    if infra_type == "well":
        existing_reg_ids = set(
            Well.objects.exclude(well_registration_id__isnull=True)
            .exclude(well_registration_id="")
            .values_list("well_registration_id", flat=True)
        )

    # ISS-179: commit_rows' per-row savepoint already isolates a single bad row
    # (see its own docstring), so anything that still reaches here (a module
    # this deployment does not have but that Task 2.1's guard missed, a
    # programming error, anything) is genuinely unexpected. Before this catch
    # it was a 500: HTMX swaps nothing on a 500, so the operator saw the exact
    # same mapping table come back with no explanation (shape 1, three tries;
    # shape 4, two). Now they get that same table back with one line saying
    # nothing was created and why, at 200 so HTMX actually swaps it in.
    try:
        results = importer.validate_rows(rows, mapping, infra_type, existing_reg_ids)
        created = importer.commit_rows(results, infra_type)
    except Exception as exc:
        logger.exception(
            "infrastructure import commit failed (infra_type=%s)", infra_type
        )
        return render(
            request,
            "infrastructure/partials/_import_mapping.html",
            _commit_failure_context(infra_type, rows, mapping, exc),
            status=200,
        )
    skipped = [r for r in results if r["errors"]]

    back_name, back_label = ADD_TYPE_BACK[infra_type]
    return render(
        request,
        "infrastructure/partials/_import_result.html",
        {
            "created": created,
            "skipped": skipped,
            "total": len(results),
            "infra_type": infra_type,
            "infra_label": ADD_TYPE_LABEL[infra_type],
            "back_url": reverse(back_name),
            "back_label": back_label,
        },
    )


@login_required
@require_GET
def infrastructure_geojson(request):
    features = []

    for well in Well.objects.all():
        features.append({
            "type": "Feature",
            "geometry": json.loads(well.location.geojson),
            "properties": {"type": "well", "name": well.name, "id": well.pk},
        })

    if is_enabled("surface"):
        # Local import: `surface` is an optional module (Phase 87) — see
        # `infrastructure_add`. Unlike the add-form branch, this loop is
        # unconditional, so it needs the module check as well as the local import.
        from surface.models import PointOfDiversion

        for pod in PointOfDiversion.objects.filter(water_right__isnull=True):
            features.append({
                "type": "Feature",
                "geometry": json.loads(pod.location.geojson),
                "properties": {"type": "diversion", "name": pod.name, "id": pod.pk},
            })

    if is_enabled("recharge"):
        # Local import: `recharge` is an optional module, so this must not run at
        # module scope (ISS-072). Unlike the add-form branch above, this loop is
        # unconditional, so it needs the module check as well as the local import.
        from recharge.models import RechargeSite

        for site in RechargeSite.objects.all():
            geom = site.geometry if site.geometry else site.location
            features.append({
                "type": "Feature",
                "geometry": json.loads(geom.geojson),
                "properties": {"type": "recharge", "name": site.name, "id": site.pk},
            })

    return JsonResponse({"type": "FeatureCollection", "features": features})


@login_required
@require_GET
def parcel_search(request):
    q = request.GET.get("q", "").strip()
    parcels = []
    if q:
        parcels = Parcel.objects.filter(
            Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
        )[:20]
    return render(request, "infrastructure/partials/_parcel_results.html", {"parcels": parcels})


@login_required
@require_POST
def parcel_create_inline(request):
    parcel_number = request.POST.get("parcel_number", "").strip()
    owner_name = request.POST.get("owner_name", "").strip()
    geometry_json = request.POST.get("geometry_json", "")

    if not parcel_number or not geometry_json:
        return JsonResponse({"error": "Parcel number and geometry required."}, status=400)

    try:
        geom = GEOSGeometry(geometry_json, srid=4326)
        if isinstance(geom, Polygon):
            geom = MultiPolygon(geom, srid=4326)
    except Exception:
        return JsonResponse({"error": "Invalid geometry."}, status=400)

    parcel = Parcel.objects.create(
        parcel_number=parcel_number,
        owner_name=owner_name,
        geometry=geom,
    )
    return render(request, "infrastructure/partials/_parcel_selected.html", {"parcel": parcel})


def _parse_point(geometry_json):
    if not geometry_json:
        return None
    try:
        data = json.loads(geometry_json)
        if data.get("type") == "Point":
            return Point(data["coordinates"][0], data["coordinates"][1], srid=4326)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    return None


def _parse_polygon(geometry_json):
    if not geometry_json:
        return None
    try:
        data = json.loads(geometry_json)
        if data.get("type") == "Polygon":
            poly = Polygon(data["coordinates"][0], srid=4326)
            return MultiPolygon(poly, srid=4326)
        elif data.get("type") == "MultiPolygon":
            return MultiPolygon(GEOSGeometry(json.dumps(data), srid=4326))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    return None
