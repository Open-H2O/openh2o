import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from recharge.models import RechargeMeasurement, RechargeEvent, RechargeSite


@login_required
def recharge_sites_list(request):
    """List view for recharge sites with HTMX search and type filter."""
    q = request.GET.get("q", "").strip()
    site_type = request.GET.get("site_type", "").strip()

    queryset = RechargeSite.objects.order_by("name")

    if q:
        queryset = queryset.filter(Q(name__icontains=q))
    if site_type:
        queryset = queryset.filter(site_type=site_type)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "site_type": site_type,
        "site_type_choices": RechargeSite.SITE_TYPE_CHOICES,
        "status_choices": RechargeSite.STATUS_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(request, "recharge/partials/_list_results.html", context)

    return render(request, "recharge/list.html", context)


@login_required
def recharge_site_detail(request, pk):
    """Detail view for a single recharge site."""
    site = get_object_or_404(RechargeSite, pk=pk)

    events = RechargeEvent.objects.filter(recharge_site=site).select_related(
        "water_type"
    ).order_by("-start_date")

    recent_measurements = RechargeMeasurement.objects.filter(
        recharge_site=site
    ).order_by("-measurement_date")[:10]

    # GeoJSON for site location point
    geojson = None
    if site.location:
        geojson = json.loads(
            serialize(
                "geojson",
                [site],
                geometry_field="location",
                fields=["name", "site_type", "status"],
            )
        )

    context = {
        "site": site,
        "events": events,
        "recent_measurements": recent_measurements,
        "geojson": json.dumps(geojson) if geojson else None,
    }
    return render(request, "recharge/site_detail.html", context)


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
