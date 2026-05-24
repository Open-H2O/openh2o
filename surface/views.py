from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import HttpResponse
from django.shortcuts import render

from surface.models import PointOfDiversion


@login_required
def water_rights_list(request):
    """Placeholder list view for water rights."""
    return render(request, "surface/water_rights_list.html")


@login_required
def pods_geojson(request):
    """Return all points of diversion as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        PointOfDiversion.objects.all(),
        geometry_field="location",
        fields=["name", "stream_name", "max_rate_cfs", "status"],
    )
    return HttpResponse(data, content_type="application/json")
