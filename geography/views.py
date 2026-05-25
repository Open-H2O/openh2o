import json

from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import HttpResponse
from django.shortcuts import render

from geography.models import Boundary, Zone


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


def boundaries_geojson(request):
    """Return all boundaries as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        Boundary.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["name", "description", "area_sq_miles"],
    )
    return HttpResponse(data, content_type="application/json")


def zones_geojson(request):
    """Return all zones as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        Zone.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["name", "zone_type"],
    )
    return HttpResponse(data, content_type="application/json")
