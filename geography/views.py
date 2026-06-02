# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounting.models import AllocationPlan
from geography.forms import ZoneForm
from geography.models import Boundary, ParcelZone, Zone
from parcels.models import Parcel
from surface.models import PointOfDiversionParcel
from wells.models import WellIrrigatedParcel


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------


@login_required
def map_view(request):
    """Interactive map with all spatial layers. Uses map-engine.js."""
    center_lng = -119.5
    center_lat = 37.5
    zoom = 6

    boundary = Boundary.objects.first()
    if boundary and boundary.geometry:
        centroid = boundary.geometry.centroid
        center_lng = centroid.x
        center_lat = centroid.y
        extent = boundary.geometry.extent
        bounds = json.dumps([
            [extent[0], extent[1]],
            [extent[2], extent[3]],
        ])
    else:
        bounds = "null"

    return render(request, "geography/map.html", {
        "center_lng": center_lng,
        "center_lat": center_lat,
        "zoom": zoom,
        "bounds": bounds,
    })


# ---------------------------------------------------------------------------
# Zone management
# ---------------------------------------------------------------------------


@login_required
def zone_list(request):
    """Paginated list of zones with HTMX search and type filter."""
    q = request.GET.get("q", "").strip()
    zone_type = request.GET.get("zone_type", "").strip()

    queryset = (
        Zone.objects
        .annotate(parcel_count=Count("parcel_zones"))
        .order_by("name")
    )

    if q:
        queryset = queryset.filter(Q(name__icontains=q))
    if zone_type:
        queryset = queryset.filter(zone_type=zone_type)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "zone_type": zone_type,
        "zone_type_choices": Zone.ZONE_TYPE_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(request, "geography/partials/_zone_list_results.html", context)

    return render(request, "geography/zone_list.html", context)


@login_required
def zone_detail(request, pk):
    """Detail page for a single zone."""
    zone = get_object_or_404(Zone, pk=pk)

    # Assigned parcels via ParcelZone
    parcel_zones = (
        ParcelZone.objects
        .filter(zone=zone)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    # Allocations for this zone (any period)
    allocations = (
        AllocationPlan.objects
        .filter(zone=zone)
        .select_related("reporting_period", "water_type")
        .order_by("-reporting_period__start_date")
    )

    # GeoJSON for the zone map
    zone_geojson = None
    if zone.geometry:
        # Python object (not a json.dumps string): the template escapes it via
        # json_script so zone.name can't break out of <script>.
        zone_geojson = {
            "type": "Feature",
            "geometry": json.loads(zone.geometry.geojson),
            "properties": {
                "name": zone.name,
                "zone_type": zone.zone_type,
            },
        }

    context = {
        "zone": zone,
        "parcel_zones": parcel_zones,
        "allocations": allocations,
        "zone_geojson": zone_geojson,
    }
    return render(request, "geography/zone_detail.html", context)


@login_required
def zone_create(request):
    """Create a new zone with map polygon drawing."""
    if request.method == "POST":
        form = ZoneForm(request.POST)
        if form.is_valid():
            zone = form.save(commit=False)

            # Parse geometry from hidden input
            geometry_json = request.POST.get("geometry_json", "")
            geometry = _parse_polygon(geometry_json)
            if not geometry:
                return render(request, "geography/zone_create.html", {
                    "form": form,
                    "error": "A polygon boundary is required. Draw a polygon on the map.",
                })

            zone.geometry = geometry

            # Auto-assign boundary to first Boundary object
            boundary = Boundary.objects.first()
            if not boundary:
                return render(request, "geography/zone_create.html", {
                    "form": form,
                    "error": "No district boundary configured. Create a boundary first in the admin.",
                })
            zone.boundary = boundary
            zone.save()
            return redirect("geography:zone_detail", pk=zone.pk)
    else:
        form = ZoneForm()

    return render(request, "geography/zone_create.html", {"form": form})


@login_required
@require_POST
def zone_parcel_assign(request, pk):
    """Assign a parcel to a zone. Creates ParcelZone."""
    zone = get_object_or_404(Zone, pk=pk)
    parcel_id = request.POST.get("parcel_id")
    parcel = get_object_or_404(Parcel, pk=parcel_id)

    ParcelZone.objects.get_or_create(zone=zone, parcel=parcel)

    parcel_zones = (
        ParcelZone.objects
        .filter(zone=zone)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    return render(request, "geography/partials/_zone_parcels.html", {
        "zone": zone,
        "parcel_zones": parcel_zones,
    })


@login_required
@require_POST
def zone_parcel_remove(request, pk, pz_pk):
    """Remove a parcel from a zone. Deletes the ParcelZone."""
    zone = get_object_or_404(Zone, pk=pk)
    pz = get_object_or_404(ParcelZone, pk=pz_pk, zone=zone)
    pz.delete()

    parcel_zones = (
        ParcelZone.objects
        .filter(zone=zone)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    return render(request, "geography/partials/_zone_parcels.html", {
        "zone": zone,
        "parcel_zones": parcel_zones,
    })


@login_required
def zone_parcel_search(request, pk):
    """HTMX GET endpoint: search parcels not already in this zone."""
    zone = get_object_or_404(Zone, pk=pk)
    q = request.GET.get("q", "").strip()

    results = []
    if q:
        already_assigned = ParcelZone.objects.filter(
            zone=zone
        ).values_list("parcel_id", flat=True)

        results = (
            Parcel.objects.filter(
                Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
            )
            .exclude(pk__in=already_assigned)
            .order_by("parcel_number")[:10]
        )

    return render(request, "geography/partials/_zone_parcel_search_results.html", {
        "zone": zone,
        "results": results,
        "q": q,
    })


@login_required
def zone_geojson_single(request, pk):
    """Return GeoJSON for a single zone."""
    zone = get_object_or_404(Zone, pk=pk)
    if not zone.geometry:
        return HttpResponse(
            json.dumps({"type": "FeatureCollection", "features": []}),
            content_type="application/json",
        )
    data = serialize(
        "geojson",
        Zone.objects.filter(pk=pk),
        geometry_field="geometry",
        fields=["name", "zone_type"],
    )
    return HttpResponse(data, content_type="application/json")


# ---------------------------------------------------------------------------
# GeoJSON endpoints
# ---------------------------------------------------------------------------


@login_required
def tie_lines_geojson(request):
    """Return GeoJSON FeatureCollection of LineString tie lines connecting wells/PODs to parcel centroids."""
    features = []

    # Groundwater tie lines: well -> parcel centroid
    for wip in WellIrrigatedParcel.objects.select_related("well", "parcel").all():
        parcel = wip.parcel
        if not parcel.geometry:
            continue
        well = wip.well
        centroid = parcel.geometry.centroid
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [well.location.x, well.location.y],
                    [centroid.x, centroid.y],
                ],
            },
            "properties": {
                "source_type": "gw",
                "source_name": str(well),
                "parcel_number": parcel.parcel_number,
                "fraction": float(wip.fraction),
                "source_id": well.pk,
                "parcel_id": parcel.pk,
            },
        })

    # Surface water tie lines: POD -> parcel centroid
    for podp in PointOfDiversionParcel.objects.select_related("point_of_diversion", "parcel").all():
        parcel = podp.parcel
        if not parcel.geometry:
            continue
        pod = podp.point_of_diversion
        centroid = parcel.geometry.centroid
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [pod.location.x, pod.location.y],
                    [centroid.x, centroid.y],
                ],
            },
            "properties": {
                "source_type": "sw",
                "source_name": str(pod),
                "parcel_number": parcel.parcel_number,
                "fraction": float(podp.fraction),
                "source_id": pod.pk,
                "parcel_id": parcel.pk,
            },
        })

    data = json.dumps({"type": "FeatureCollection", "features": features})
    return HttpResponse(data, content_type="application/json")


@login_required
def boundaries_geojson(request):
    """Return all boundaries as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        Boundary.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["name", "description", "area_sq_miles"],
    )
    return HttpResponse(data, content_type="application/json")


@login_required
def zones_geojson(request):
    """Return all zones as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        Zone.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["name", "zone_type"],
    )
    return HttpResponse(data, content_type="application/json")


# ---------------------------------------------------------------------------
# Helpers (duplicated from infrastructure/views.py — polygon parsing)
# ---------------------------------------------------------------------------


def _parse_polygon(geometry_json):
    """Parse a GeoJSON Polygon or MultiPolygon string into a MultiPolygon GEOS object."""
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
