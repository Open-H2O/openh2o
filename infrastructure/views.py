# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point, Polygon
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from infrastructure import importer
from parcels.models import Parcel
from recharge.models import RechargeSite
from surface.models import PointOfDiversion, PointOfDiversionParcel
from wells.models import (
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
    "storage": "Storage",
    "recharge_site": "Recharge Site",
}


def _add_context(infra_type, **extra):
    """Build the type-aware context for add.html (GET and POST-error re-renders)."""
    if infra_type not in ADD_TYPE_BACK:
        infra_type = "well"
    back_name, back_label = ADD_TYPE_BACK[infra_type]
    context = {
        "preselect_type": infra_type,
        "preselect_label": ADD_TYPE_LABEL[infra_type],
        "back_url": reverse(back_name),
        "back_label": back_label,
        "measurement_method_choices": MEASUREMENT_METHOD_CHOICES,
        "pump_type_choices": PUMP_TYPE_CHOICES,
    }
    context.update(extra)
    return context


@login_required
def infrastructure_add(request):
    if request.method == "GET":
        return render(
            request,
            "infrastructure/add.html",
            _add_context(request.GET.get("type", "well").strip()),
        )

    infra_type = request.POST.get("infra_type", "well")
    name = request.POST.get("name", "").strip()
    status = request.POST.get("status", "active")
    notes = request.POST.get("notes", "").strip()
    geometry_json = request.POST.get("geometry_json", "")
    parcel_id = request.POST.get("parcel_id", "")

    parcel = None
    if parcel_id:
        try:
            parcel = Parcel.objects.get(pk=parcel_id)
        except Parcel.DoesNotExist:
            parcel = None

    if infra_type == "well":
        location = _parse_point(geometry_json)
        if not location:
            return render(request, "infrastructure/add.html", _add_context("well", error="A point location is required for wells."))
        well = Well.objects.create(
            name=name,
            location=location,
            depth_ft=request.POST.get("depth_ft") or None,
            capacity_gpm=request.POST.get("capacity_gpm") or None,
            status=status,
            owner_name=request.POST.get("owner_name", ""),
            year_pumping_began=request.POST.get("year_pumping_began") or None,
            measurement_method=request.POST.get("measurement_method", ""),
            wcr_number=request.POST.get("wcr_number", ""),
            state_well_number=request.POST.get("state_well_number", ""),
            casing_diameter_in=request.POST.get("casing_diameter_in") or None,
            casing_material=request.POST.get("casing_material", ""),
            screen_top_ft=request.POST.get("screen_top_ft") or None,
            screen_bottom_ft=request.POST.get("screen_bottom_ft") or None,
            tested_yield_gpm=request.POST.get("tested_yield_gpm") or None,
            pump_type=request.POST.get("pump_type", ""),
            notes=notes,
        )
        if parcel:
            WellIrrigatedParcel.objects.create(well=well, parcel=parcel)
        return redirect("wells:detail", pk=well.pk)

    elif infra_type == "diversion":
        location = _parse_point(geometry_json)
        if not location:
            return render(request, "infrastructure/add.html", _add_context("diversion", error="A point location is required for diversions."))
        pod = PointOfDiversion.objects.create(
            name=name,
            location=location,
            water_right=None,
            stream_name=request.POST.get("stream_name", ""),
            max_rate_cfs=request.POST.get("max_rate_cfs") or None,
            status=status,
            notes=notes,
        )
        if parcel:
            PointOfDiversionParcel.objects.create(point_of_diversion=pod, parcel=parcel)
        return redirect("surface:pod_list")

    elif infra_type in ("recharge_site", "storage"):
        location = _parse_point(geometry_json)
        geometry = _parse_polygon(geometry_json)

        if not location and not geometry:
            return render(request, "infrastructure/add.html", _add_context(infra_type, error="A location or polygon is required."))

        if geometry and not location:
            location = geometry.centroid

        site_type = request.POST.get("site_type", "spreading_basin")
        if infra_type == "storage":
            site_type = request.POST.get("storage_type", "storage_pond")

        site = RechargeSite.objects.create(
            name=name,
            location=location,
            geometry=geometry,
            site_type=site_type,
            capacity_acre_feet=request.POST.get("capacity_acre_feet") or None,
            status=status,
            operator=request.POST.get("operator", ""),
            notes=notes,
        )
        return redirect("recharge:detail", pk=site.pk)

    return render(request, "infrastructure/add.html", _add_context(infra_type, error="Invalid infrastructure type."))


# ---------------------------------------------------------------------------
# Bulk import: page -> preview/map -> commit
# ---------------------------------------------------------------------------


def _import_type(raw):
    """Normalize a ?type / infra_type value to a supported import type."""
    raw = (raw or "well").strip()
    return raw if raw in ADD_TYPE_BACK else "well"


@login_required
@require_GET
def infrastructure_import(request):
    """Bulk import landing page (the file dropzone)."""
    infra_type = _import_type(request.GET.get("type"))
    back_name, back_label = ADD_TYPE_BACK[infra_type]
    return render(
        request,
        "infrastructure/import.html",
        {
            "infra_type": infra_type,
            "infra_label": ADD_TYPE_LABEL[infra_type],
            "back_url": reverse(back_name),
            "back_label": back_label,
        },
    )


@login_required
@require_POST
def infrastructure_import_preview(request):
    """Parse the uploaded file, auto-map its columns, return the mapping UI."""
    infra_type = _import_type(request.POST.get("infra_type"))
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

    return render(
        request,
        "infrastructure/partials/_import_mapping.html",
        {
            "infra_type": infra_type,
            "infra_label": ADD_TYPE_LABEL[infra_type],
            "columns": columns,
            "field_rows": field_rows,
            "sample_table": sample_table,
            "sample_count": len(sample_table),
            "row_count": len(rows),
            "rows_json": json.dumps(rows),
        },
    )


@login_required
@require_POST
def infrastructure_import_commit(request):
    """Validate the confirmed mapping against the parsed rows and bulk-create."""
    infra_type = _import_type(request.POST.get("infra_type"))

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

    results = importer.validate_rows(rows, mapping, infra_type, existing_reg_ids)
    created = importer.commit_rows(results, infra_type)
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

    for pod in PointOfDiversion.objects.filter(water_right__isnull=True):
        features.append({
            "type": "Feature",
            "geometry": json.loads(pod.location.geojson),
            "properties": {"type": "diversion", "name": pod.name, "id": pod.pk},
        })

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
