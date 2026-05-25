import json

from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import HttpResponse
from django.shortcuts import render

from geography.models import Boundary, Zone
from surface.models import PointOfDiversionParcel
from wells.models import WellIrrigatedParcel


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


@login_required
def tie_lines_geojson(request):
    """Return GeoJSON FeatureCollection of LineString tie lines connecting wells/PODs to parcel centroids."""
    features = []

    # Groundwater tie lines: well → parcel centroid
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

    # Surface water tie lines: POD → parcel centroid
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
