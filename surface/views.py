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
    """Surface Diversions OVERVIEW: a map of every diversion point + a list.

    Points of diversion are a Bucket-3 screen (few items, each heavy): a district
    has a handful, and each one's detail is rich (its location mapped on the
    stream/canal network, diversion records, linked use areas, compliance). So
    this screen is a finder, not a master-detail half-pane: the map up top shows
    every diversion point at once, the full-width list below is for finding one
    fast, and clicking a row (or a point on the map) opens that diversion's own
    full-width detail page. See ``docs/2.0-UX-PATTERN-SPEC.md`` for why this is
    Bucket 3, not master-detail.

    Returns the ``_pod_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full page otherwise.
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

    # Diversion points are bounded and few, so show them all on one page; finding
    # one is a glance plus a type-to-filter. Pagination stays as a graceful
    # fallback for an unusually large district.
    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": PointOfDiversion.STATUS_CHOICES,
    }

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
    """Master-detail workspace for water rights.

    Left pane: the HTMX-searchable rights list. Right pane: the selected right's
    detail — its points of diversion mapped, plus diversion records and active
    curtailments — swapped in place when a row is clicked. A ``?selected=<pk>``
    query param pre-renders that right server-side so a reload or deep link lands
    on the same workspace view (the row click pushes that URL).

    Returns the ``_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full workspace page
    otherwise.
    """
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

    # Pre-load the selected right (deep link / reload) into the detail pane.
    selected_right = None
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        selected_right = (
            WaterRight.objects.select_related("right_type")
            .filter(pk=selected_raw)
            .first()
        )

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "status_choices": WaterRight.STATUS_CHOICES,
        "selected_right": selected_right,
    }
    if selected_right is not None:
        context.update(_water_right_detail_context(selected_right))

    return list_response(
        request,
        page_template="surface/water_rights_list.html",
        results_template="surface/partials/_list_results.html",
        context=context,
    )


def _water_right_detail_context(water_right):
    """Build the per-right detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
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

    # GeoJSON for the PODs this right serves — a FeatureCollection (the right maps
    # multiple diversion points, so OH2O.detailPaneMap frames the map across all of
    # them via geojson.features). Python object (not a dumped string): the template
    # escapes it via json_script so POD names can't break out of <script>.
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

    return {
        "water_right": water_right,
        "pods": pods,
        "recent_diversions": recent_diversions,
        "active_curtailments": active_curtailments,
        "pods_geojson": pods_geojson,
    }


@login_required
def water_right_detail(request, pk):
    """A single water right's detail.

    On an HTMX request it returns just the ``_water_right_detail_pane`` fragment
    (the workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    water_right = get_object_or_404(
        WaterRight.objects.select_related("right_type"), pk=pk
    )
    context = _water_right_detail_context(water_right)
    return detail_response(
        request,
        pane_template="surface/partials/_water_right_detail_pane.html",
        page_template="surface/water_right_detail.html",
        context=context,
    )


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
