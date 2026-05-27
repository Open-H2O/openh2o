import json
import os
import shutil
import tempfile
import zipfile
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point, Polygon
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from parcels.models import Parcel
from recharge.models import RechargeSite
from surface.models import PointOfDiversion, PointOfDiversionParcel
from wells.models import Well, WellIrrigatedParcel


@login_required
@require_GET
def infrastructure_list(request):
    wells = Well.objects.all()
    pods = PointOfDiversion.objects.filter(water_right__isnull=True)
    recharge_sites = RechargeSite.objects.all()

    well_count = wells.count()
    pod_count = pods.count()
    recharge_count = recharge_sites.count()
    total_count = well_count + pod_count + recharge_count

    type_filter = request.GET.get("type", "").strip()
    epoch = timezone.make_aware(timezone.datetime(2000, 1, 1))

    items_lists = []
    if type_filter in ("", "well"):
        items_lists.append([
            {
                "type": "well",
                "name": w.name,
                "created_at": w.created_at,
                "status": w.get_status_display(),
                "depth_ft": w.depth_ft,
                "capacity_gpm": w.capacity_gpm,
                "detail_url": reverse("wells:detail", args=[w.pk]),
            }
            for w in wells
        ])
    if type_filter in ("", "diversion"):
        items_lists.append([
            {
                "type": "diversion",
                "name": p.name,
                "created_at": epoch,
                "status": p.get_status_display(),
                "stream_name": p.stream_name,
                "max_rate_cfs": p.max_rate_cfs,
                "detail_url": reverse("surface:pod_detail", args=[p.pk]),
            }
            for p in pods
        ])
    if type_filter in ("", "recharge"):
        items_lists.append([
            {
                "type": "recharge",
                "name": r.name,
                "created_at": r.created_at,
                "status": r.get_status_display(),
                "site_type": r.get_site_type_display(),
                "capacity_acre_feet": r.capacity_acre_feet,
                "detail_url": reverse("recharge:detail", args=[r.pk]),
            }
            for r in recharge_sites
        ])

    items = sorted(chain(*items_lists), key=lambda x: x["created_at"], reverse=True)

    q = request.GET.get("q", "").strip()
    if q:
        items = [i for i in items if q.lower() in i["name"].lower()]

    context = {
        "items": items,
        "query": q,
        "type_filter": type_filter,
        "total_count": total_count,
        "well_count": well_count,
        "pod_count": pod_count,
        "recharge_count": recharge_count,
    }

    if request.headers.get("HX-Request"):
        return render(request, "infrastructure/partials/_list_results.html", context)
    return render(request, "infrastructure/list.html", context)


@login_required
def infrastructure_add(request):
    if request.method == "GET":
        return render(request, "infrastructure/add.html")

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
            return render(request, "infrastructure/add.html", {"error": "A point location is required for wells."})
        well = Well.objects.create(
            name=name,
            location=location,
            depth_ft=request.POST.get("depth_ft") or None,
            capacity_gpm=request.POST.get("capacity_gpm") or None,
            status=status,
            owner_name=request.POST.get("owner_name", ""),
            notes=notes,
        )
        if parcel:
            WellIrrigatedParcel.objects.create(well=well, parcel=parcel)
        return redirect("wells:detail", pk=well.pk)

    elif infra_type == "diversion":
        location = _parse_point(geometry_json)
        if not location:
            return render(request, "infrastructure/add.html", {"error": "A point location is required for diversions."})
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
        return redirect("infrastructure:list")

    elif infra_type in ("recharge_site", "storage"):
        location = _parse_point(geometry_json)
        geometry = _parse_polygon(geometry_json)

        if not location and not geometry:
            return render(request, "infrastructure/add.html", {"error": "A location or polygon is required."})

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

    return render(request, "infrastructure/add.html", {"error": "Invalid infrastructure type."})


@login_required
@require_POST
def infrastructure_upload(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file provided."}, status=400)

    filename = uploaded.name.lower()
    try:
        if filename.endswith((".geojson", ".json")):
            features = _parse_geojson_file(uploaded)
        elif filename.endswith(".zip"):
            features = _parse_shapefile_zip(uploaded)
        elif filename.endswith(".kml"):
            features = _parse_kml_file(uploaded)
        else:
            return JsonResponse({"error": "Unsupported format. Use .geojson, .zip (shapefile), or .kml."}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Parse error: {str(e)}"}, status=400)

    if len(features) > 500:
        return JsonResponse({"error": "File contains more than 500 features. Please use a smaller file."}, status=400)

    return JsonResponse({"features": features})


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


def _parse_geojson_file(uploaded):
    content = json.loads(uploaded.read().decode("utf-8"))
    features = []

    if content.get("type") == "FeatureCollection":
        raw_features = content.get("features", [])
    elif content.get("type") == "Feature":
        raw_features = [content]
    else:
        raw_features = [{"type": "Feature", "geometry": content, "properties": {}}]

    for feat in raw_features:
        features.append({
            "geometry": feat.get("geometry"),
            "properties": feat.get("properties", {}),
        })
    return features


def _parse_shapefile_zip(uploaded):
    tmp_dir = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(tmp_dir, "upload.zip")
        with open(zip_path, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        shp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".shp")]
        if not shp_files:
            for root, dirs, files in os.walk(tmp_dir):
                for f in files:
                    if f.endswith(".shp"):
                        shp_files.append(os.path.join(root, f))
                        break
                if shp_files:
                    break

        if not shp_files:
            raise ValueError("No .shp file found in archive.")

        shp_path = shp_files[0] if os.path.isabs(shp_files[0]) else os.path.join(tmp_dir, shp_files[0])
        return _extract_features_from_datasource(shp_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _parse_kml_file(uploaded):
    tmp_dir = tempfile.mkdtemp()
    try:
        kml_path = os.path.join(tmp_dir, "upload.kml")
        with open(kml_path, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)
        return _extract_features_from_datasource(kml_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_features_from_datasource(path):
    ds = DataSource(path)
    features = []
    for layer in ds:
        for feat in layer:
            geom = feat.geom
            if geom.srid and geom.srid != 4326:
                geom.transform(4326)
            properties = {}
            for field_name in feat.fields:
                val = feat.get(field_name)
                if val is not None:
                    properties[field_name] = str(val)
            features.append({
                "geometry": json.loads(geom.geojson),
                "properties": properties,
            })
    return features
