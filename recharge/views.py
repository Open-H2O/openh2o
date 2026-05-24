from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import HttpResponse
from django.shortcuts import render

from recharge.models import RechargeSite


@login_required
def recharge_sites_list(request):
    """Placeholder list view for recharge sites."""
    return render(request, "recharge/list.html")


@login_required
def recharge_sites_geojson(request):
    """Return all recharge sites as a GeoJSON FeatureCollection."""
    data = serialize(
        "geojson",
        RechargeSite.objects.all(),
        geometry_field="location",
        fields=["name", "site_type", "capacity_acre_feet", "status"],
    )
    return HttpResponse(data, content_type="application/json")
