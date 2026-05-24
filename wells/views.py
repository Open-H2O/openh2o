from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import HttpResponse
from django.shortcuts import render

from wells.models import Well


@login_required
def wells_list(request):
    """Placeholder list view for wells."""
    return render(request, "wells/list.html")


@login_required
def wells_geojson(request):
    """Return all wells as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        Well.objects.all(),
        geometry_field="location",
        fields=["name", "well_registration_id", "status", "depth_ft", "capacity_gpm"],
    )
    return HttpResponse(data, content_type="application/json")
