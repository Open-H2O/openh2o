# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from recharge.forms import RechargeEventForm
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

    context = {
        "site": site,
        "events": events,
        "recent_measurements": recent_measurements,
        "event_form": RechargeEventForm(),
        # Python object (or None); template escapes it via json_script.
        "geojson": geojson,
    }
    return render(request, "recharge/site_detail.html", context)


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
            ledger_msg = (
                f"Created {count} ledger "
                f"entr{'y' if count == 1 else 'ies'} across zone parcels."
            )
        else:
            ledger_msg = (
                "Event saved. The site's zone has no parcels, so no ledger "
                "entries were generated."
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
