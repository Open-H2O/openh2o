# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Recharge site and event surfaces.

Renders the recharge-site list and detail pages (showing a site's RechargeEvents,
the PODs that fill it, and recent RechargeMeasurements) and the sites GeoJSON
endpoint. Creating a RechargeEvent here hands off to the accounting service,
which credits groundwater either to the GSA basin pool for the site's zone or to
a has-well parcel on the conjunctive path.
"""
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.workspace import detail_response, list_response
from recharge.forms import RechargeEventForm
from recharge.models import RechargeMeasurement, RechargeEvent, RechargeSite


@login_required
def recharge_sites_list(request):
    """Master-detail workspace for recharge areas.

    Left pane: the HTMX-searchable site list. Right pane: the selected site's
    detail — its geometry mapped (polygon basin or point), plus event history and
    recent measurements — swapped in place when a row is clicked. A
    ``?selected=<pk>`` query param pre-renders that site server-side so a reload
    or deep link lands on the same workspace view (the row click pushes that URL).

    Returns the ``_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full workspace page
    otherwise.
    """
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

    # Pre-load the selected site (deep link / reload) into the detail pane.
    selected_site = None
    selected_raw = request.GET.get("selected", "").strip()
    if selected_raw:
        selected_site = RechargeSite.objects.filter(pk=selected_raw).first()

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "site_type": site_type,
        "site_type_choices": RechargeSite.SITE_TYPE_CHOICES,
        "status_choices": RechargeSite.STATUS_CHOICES,
        "selected_site": selected_site,
    }
    if selected_site is not None:
        context.update(_recharge_site_detail_context(selected_site))

    return list_response(
        request,
        page_template="recharge/list.html",
        results_template="recharge/partials/_list_results.html",
        context=context,
    )


def _recharge_site_detail_context(site):
    """Build the per-site detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
    events = RechargeEvent.objects.filter(recharge_site=site).select_related(
        "water_type"
    ).order_by("-start_date")

    # The diversion(s) that fill this basin (Phase 62): each link names the POD
    # and, through it, the real waterway it sits on. A data field on this page,
    # not a flow line on the map.
    pod_links = (
        site.pod_links.select_related(
            "point_of_diversion", "point_of_diversion__source_flowline"
        ).order_by("point_of_diversion__name")
    )

    recent_measurements = RechargeMeasurement.objects.filter(
        recharge_site=site
    ).order_by("-measurement_date")[:10]

    # GeoJSON for the persistent detail map. Prefer the polygon basin geometry;
    # fall back to a point location. OH2O.detailPaneMap auto-detects polygon
    # (fill + outline) vs point (glow + marker) from the geometry type, so the
    # same call serves both. Python object (or None): the template escapes it via
    # json_script so the site name / type can't break out of <script>.
    geojson = None
    geo_field = "geometry" if site.geometry else "location"
    if geo_field == "location" and not site.location:
        geo_field = None
    if geo_field:
        geojson = json.loads(
            serialize(
                "geojson",
                [site],
                geometry_field=geo_field,
                fields=["name", "site_type", "status"],
            )
        )

    return {
        "site": site,
        "events": events,
        "pod_links": pod_links,
        "recent_measurements": recent_measurements,
        "event_form": RechargeEventForm(),
        "geojson": geojson,
    }


@login_required
def recharge_site_detail(request, pk):
    """A single recharge site's detail.

    On an HTMX request it returns just the ``_detail_pane`` fragment (the
    workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    site = get_object_or_404(RechargeSite, pk=pk)
    context = _recharge_site_detail_context(site)
    return detail_response(
        request,
        pane_template="recharge/partials/_detail_pane.html",
        page_template="recharge/site_detail.html",
        context=context,
    )


@login_required
def recharge_event_create(request, pk):
    """Create a RechargeEvent for a site and auto-distribute it to the ledger.

    Renders the event-history partial (table + inline form) for HTMX swap.
    """
    site = get_object_or_404(RechargeSite, pk=pk)

    # Forms live inline on the detail page; a bare GET has nothing to do here.
    if request.method != "POST":
        return redirect("recharge:detail", pk=pk)

    form = RechargeEventForm(request.POST)
    if not form.is_valid():
        events = (
            RechargeEvent.objects.filter(recharge_site=site)
            .select_related("water_type")
            .order_by("-start_date")
        )
        context = {"site": site, "events": events, "event_form": form}
        return render(request, "recharge/partials/_event_history.html", context)

    event = form.save(commit=False)
    event.recharge_site = site
    event.save()

    # The service is the single source of truth for the zone rule; let it decide.
    from accounting.services import create_recharge_ledger_entries

    try:
        created = create_recharge_ledger_entries(event)
        count = len(created)
        if count:
            # Personal-credit path: the event was tied to a has-well parcel.
            ledger_msg = (
                f"Created {count} personal recharge ledger "
                f"entr{'y' if count == 1 else 'ies'}."
            )
        else:
            # Default path (52.6-02): the recharge infiltrates the shared aquifer,
            # so it was deposited to the GSA basin recharge pool for the zone —
            # not smeared across individual parcels.
            ledger_msg = (
                "Event saved. Recharge deposited to the GSA basin pool for the "
                "site's zone."
            )
    except ValueError:
        ledger_msg = (
            "Event saved. No zone assigned to this site, so no ledger entries "
            "were generated — assign a zone to auto-distribute recharge."
        )

    events = (
        RechargeEvent.objects.filter(recharge_site=site)
        .select_related("water_type")
        .order_by("-start_date")
    )
    context = {
        "site": site,
        "events": events,
        "event_form": RechargeEventForm(),
        "ledger_msg": ledger_msg,
    }
    return render(request, "recharge/partials/_event_history.html", context)


@login_required
def recharge_sites_geojson(request):
    """Return all recharge sites as GeoJSON, preferring polygon geometry."""
    features = []
    for site in RechargeSite.objects.all():
        geom = site.geometry or site.location
        if not geom:
            continue
        features.append({
            "type": "Feature",
            "geometry": json.loads(geom.geojson),
            "properties": {
                "pk": site.pk,
                "name": site.name,
                "site_type": site.site_type,
                "capacity_acre_feet": str(site.capacity_acre_feet) if site.capacity_acre_feet else None,
                "status": site.status,
            },
        })
    collection = {"type": "FeatureCollection", "features": features}
    return HttpResponse(json.dumps(collection), content_type="application/json")
