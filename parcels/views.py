from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import HttpResponse
from django.shortcuts import render

from parcels.models import Parcel


@login_required
def parcels_list(request):
    """Placeholder list view for parcels."""
    return render(request, "parcels/list.html")


@login_required
def parcels_geojson(request):
    """Return all parcels as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        Parcel.objects.filter(geometry__isnull=False),
        geometry_field="geometry",
        fields=["parcel_number", "owner_name", "area_acres", "status"],
    )
    return HttpResponse(data, content_type="application/json")
