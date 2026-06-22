# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Surface views.

The surface-water browsing and entry surfaces. pod_list and pod_detail are the
primary entry point for surface diversions — pod_detail renders the one-hop water
journey from a point of diversion through the parcels it serves. water_rights_list
and water_right_detail expose the underlying entitlements, diversion_record_create
records a diversion event, and pods_geojson feeds the diversion map.
"""
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounting.models import ReportingPeriod
from core.workspace import detail_response, list_response
from surface.forms import DiversionRecordForm
from surface.models import (
    CurtailmentOrder,
    DiversionRecord,
    PointOfDiversion,
    PointOfDiversionParcel,
    WaterRight,
)


# ---------------------------------------------------------------------------
# POD-centric views (primary entry point for Surface Diversions)
# ---------------------------------------------------------------------------


@login_required
def pod_list(request):
    """Master-detail workspace for points of diversion.

    Left pane: the HTMX-searchable POD list. Right pane: the selected diversion
    point's detail, swapped in place when a row is clicked. A ``?selected=<pk>``
    query param pre-renders that POD server-side so a reload or deep link lands
    on the same workspace view (the row click pushes that URL).

    Returns the ``_pod_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full workspace page
    otherwise.
    """
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = (
        PointOfDiversion.objects
        .select_related("water_right")
        .annotate(diversion_count=Count("diversionrecord"))
        .order_by("name")
    )

    if q:
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(stream_name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Pre-load the selected POD (deep link / reload) into the detail pane.
    selected_pod = None
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        selected_pod = (
            PointOfDiversion.objects.select_related("water_right")
            .filter(pk=selected_raw)
            .first()
        )

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": PointOfDiversion.STATUS_CHOICES,
        "selected_pod": selected_pod,
    }
    if selected_pod is not None:
        context.update(_pod_detail_context(selected_pod))

    return list_response(
        request,
        page_template="surface/pod_list.html",
        results_template="surface/partials/_pod_list_results.html",
        context=context,
    )


def _pod_detail_context(pod):
    """Build the per-POD detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
    # Diversion records for this POD
    diversion_records = (
        DiversionRecord.objects
        .filter(point_of_diversion=pod)
        .select_related("reporting_period")
        .order_by("-month")
    )

    # Linked use areas (parcel connections)
    pod_parcels = (
        PointOfDiversionParcel.objects
        .filter(point_of_diversion=pod)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    # Recharge areas this diversion fills (Phase 62). For a dual-purpose Merced
    # River diversion this lists the Flood-MAR areas it floods, right next to the
    # cropland it irrigates above.
    basin_links = (
        pod.basin_links
        .select_related("recharge_site")
        .order_by("recharge_site__name")
    )

    # One-hop water journey (Phase 67-03). rediverted_from is the upstream source
    # this POD re-diverts; rediversions is the reverse — downstream PODs that draw
    # on this POD's return flow. One hop only — no route-resolver graph this phase.
    rediverted_from = pod.rediverted_from
    rediversions = pod.rediversions.order_by("name")

    # Water right info (may be None)
    water_right = pod.water_right

    # Inline form for adding diversion records
    form = DiversionRecordForm()

    # GeoJSON for the persistent detail map. A FeatureCollection (not a bare
    # Feature) because OH2O.detailPaneMap frames the map off geojson.features.
    # Python object (not a json.dumps string): the template escapes it via
    # json_script so pod.name / stream_name can't break out of <script>.
    geojson = None
    if pod.location:
        geojson = json.loads(
            serialize(
                "geojson",
                [pod],
                geometry_field="location",
                fields=["name", "stream_name"],
            )
        )

    return {
        "pod": pod,
        "diversion_records": diversion_records,
        "pod_parcels": pod_parcels,
        "basin_links": basin_links,
        "rediverted_from": rediverted_from,
        "rediversions": rediversions,
        "water_right": water_right,
        "form": form,
        "geojson": geojson,
    }


@login_required
def pod_detail(request, pk):
    """A single point of diversion's detail.

    On an HTMX request it returns just the ``_detail_pane`` fragment (the
    workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    pod = get_object_or_404(
        PointOfDiversion.objects.select_related("water_right"), pk=pk
    )
    context = _pod_detail_context(pod)
    return detail_response(
        request,
        pane_template="surface/partials/_detail_pane.html",
        page_template="surface/pod_detail.html",
        context=context,
    )


@login_required
@require_POST
def diversion_record_create(request, pk):
    """HTMX POST endpoint: create a DiversionRecord for a POD."""
    pod = get_object_or_404(PointOfDiversion, pk=pk)
    form = DiversionRecordForm(request.POST)

    if form.is_valid():
        record = form.save(commit=False)
        record.point_of_diversion = pod

        # Auto-assign reporting_period from the record's month
        month = record.month
        period = ReportingPeriod.objects.filter(
            start_date__lte=month,
            end_date__gte=month,
        ).first()
        record.reporting_period = period
        record.save()
        # Saved cleanly — hand back a blank form for the next entry.
        form = DiversionRecordForm()

    # On an invalid submit, `form` is still the BOUND form: re-rendering it
    # preserves the user's typed values and surfaces the field errors, so a
    # failed save reads as a visible error rather than a silent reset.
    diversion_records = (
        DiversionRecord.objects
        .filter(point_of_diversion=pod)
        .select_related("reporting_period")
        .order_by("-month")
    )

    return render(request, "surface/partials/_diversion_records.html", {
        "pod": pod,
        "diversion_records": diversion_records,
        "form": form,
    })


# ---------------------------------------------------------------------------
# Water Rights views (kept for compliance-focused navigation)
# ---------------------------------------------------------------------------


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
        # Python object (or None); template escapes it via json_script.
        "pods_geojson": pods_geojson,
    }
    return render(request, "surface/water_right_detail.html", context)


@login_required
def pods_geojson(request):
    """Return all points of diversion as a GeoJSON FeatureCollection."""
    raw = serialize(
        "geojson",
        PointOfDiversion.objects.all(),
        geometry_field="location",
        fields=["name", "stream_name", "max_rate_cfs", "status"],
    )
    data = json.loads(raw)
    for f in data["features"]:
        # Inject pk so the full-map popup can link to the POD detail page.
        f["properties"]["pk"] = f.get("id")
    return HttpResponse(json.dumps(data), content_type="application/json")
