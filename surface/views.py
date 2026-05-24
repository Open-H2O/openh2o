import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from surface.models import (
    CurtailmentOrder,
    DiversionRecord,
    PointOfDiversion,
    WaterRight,
)


@login_required
def water_rights_list(request):
    """List view for water rights with HTMX search and status filter."""
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = WaterRight.objects.select_related("right_type").order_by("right_id")

    if q:
        queryset = queryset.filter(
            Q(right_id__icontains=q) | Q(holder_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": WaterRight.STATUS_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(request, "surface/partials/_list_results.html", context)

    return render(request, "surface/water_rights_list.html", context)


@login_required
def water_right_detail(request, pk):
    """Detail view for a single water right."""
    water_right = get_object_or_404(
        WaterRight.objects.select_related("right_type"), pk=pk
    )

    pods = PointOfDiversion.objects.filter(water_right=water_right).order_by("name")

    # Recent diversion records through PODs, last 12
    recent_diversions = (
        DiversionRecord.objects.filter(point_of_diversion__water_right=water_right)
        .select_related("point_of_diversion")
        .order_by("-month")[:12]
    )

    # Active curtailments that affect this right (priority_date_cutoff >= this right's priority_date)
    active_curtailments = []
    if water_right.priority_date:
        active_curtailments = CurtailmentOrder.objects.filter(
            status="active",
            priority_date_cutoff__gte=water_right.priority_date,
        ).order_by("-effective_date")

    # GeoJSON for PODs
    pods_with_location = [p for p in pods if p.location]
    pods_geojson = None
    if pods_with_location:
        pods_geojson = json.loads(
            serialize(
                "geojson",
                pods_with_location,
                geometry_field="location",
                fields=["name", "stream_name", "max_rate_cfs", "status"],
            )
        )

    context = {
        "water_right": water_right,
        "pods": pods,
        "recent_diversions": recent_diversions,
        "active_curtailments": active_curtailments,
        "pods_geojson": json.dumps(pods_geojson) if pods_geojson else None,
    }
    return render(request, "surface/water_right_detail.html", context)


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
