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
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from core.access import public_in_open_demo

from accounting.models import ReportingPeriod
from accounting.services import current_period_id as compute_current_period_id
from core.workspace import detail_response, list_response
from recharge.forms import RechargeEventForm
from recharge.models import RechargeMeasurement, RechargeEvent, RechargeSite


# ---------------------------------------------------------------------------
# 143-10: the water-year grouping for a site's recharge events, shared by the
# detail page and recharge_event_create's POST response -- one helper, so the
# lead panel and the table under it can never disagree (ISS-154, 137-02;
# 143-05: the panel's figures are the SAME queryset the table prints).
#
# RechargeEvent carries no reporting_period FK (unlike surface.DiversionRecord),
# so a group is found by date range against the periods the caller fetched
# ONCE, never re-queried per event. An event whose start_date falls in no
# period's range closes into a single trailing "Outside any water year on
# record" group, appended last regardless of where its date falls among the
# others -- never split into more than one such group, unlike a plain
# contiguous-run grouping of pre-sorted rows (surface's
# _group_diversion_records, which relies on an FK already ordering the nulls
# together).
# ---------------------------------------------------------------------------
def _group_recharge_events(events, periods):
    """Partition ``events`` (any order) into per-period groups by date range.

    ``periods`` is fetched once by the caller (``ReportingPeriod.objects.all()``,
    the model's default ordering is ``-start_date``) and reused for every
    event, so this never issues a query. Each group carries its own
    ``volume`` / ``count`` sums and a ``by_type`` breakdown, computed once in
    Python from the rows already fetched.
    """
    period_list = list(periods)
    groups_by_pk = {}
    order = []
    for period in period_list:
        groups_by_pk[period.pk] = {
            "period_key": period.pk,
            "period": period,
            "period_name": period.name,
            "rows": [],
            "volume": Decimal("0"),
            "count": 0,
            "by_type": {},
        }
        order.append(period.pk)
    outside = {
        "period_key": None,
        "period": None,
        "period_name": "Outside any water year on record",
        "rows": [],
        "volume": Decimal("0"),
        "count": 0,
        "by_type": {},
    }
    for event in events:
        period = next(
            (p for p in period_list if p.start_date <= event.start_date <= p.end_date),
            None,
        )
        group = groups_by_pk[period.pk] if period else outside
        group["rows"].append(event)
        group["volume"] += event.volume_acre_feet
        group["count"] += 1
        type_name = event.water_type.name if event.water_type else "Not recorded"
        group["by_type"][type_name] = (
            group["by_type"].get(type_name, Decimal("0")) + event.volume_acre_feet
        )
    groups = [groups_by_pk[pk] for pk in order if groups_by_pk[pk]["rows"]]
    if outside["rows"]:
        groups.append(outside)
    return groups


@login_required
def recharge_sites_list(request):
    """Recharge Areas OVERVIEW: a map of every recharge site + a list.

    Recharge sites are a Bucket-3 screen (few items, each heavy): a district has a
    handful, and each one's detail is rich (its basin or point mapped, its
    recharge-event history, the diversions that fill it, recent measurements). So
    this screen is a finder, not a master-detail half-pane: the map up top shows
    every recharge site at once — polygons as basins, single points as markers —
    the full-width list below is for finding one fast, and clicking a row (or a
    feature on the map) opens that site's own full-width detail page. See
    ``docs/2.0-UX-PATTERN-SPEC.md`` for why this is Bucket 3, not master-detail.

    Returns the ``_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full page otherwise.
    """
    q = request.GET.get("q", "").strip()
    site_type = request.GET.get("site_type", "").strip()

    queryset = RechargeSite.objects.order_by("name")

    if q:
        queryset = queryset.filter(Q(name__icontains=q))
    if site_type:
        queryset = queryset.filter(site_type=site_type)

    # Recharge sites are bounded and few, so show them all on one page; finding one
    # is a glance at the map plus a type-to-filter. Pagination stays as a graceful
    # fallback for an unusually large district.
    paginator = Paginator(queryset, 100)
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
    events = list(
        RechargeEvent.objects.filter(recharge_site=site)
        .select_related("water_type")
        .order_by("-start_date")
    )

    # 143-10 (R-126, R-055): the table's own water-year groups, and the
    # CURRENT period's figures read off that SAME grouping -- no second
    # query, so the lead panel can never disagree with the table under it.
    # accounting.services.current_period_id is the helper 143-06 and 143-10
    # Task 2 read so this page lands on the same idea of "current" as the
    # diversion page, the right page, the zone page and the ledger (recharge
    # `requires` accounting, core/modules.py, so this import needs no module
    # gate).
    periods = ReportingPeriod.objects.all()
    event_groups = _group_recharge_events(events, periods)
    current_period_pk = compute_current_period_id()
    current_period = (
        ReportingPeriod.objects.filter(pk=current_period_pk).first()
        if current_period_pk is not None
        else None
    )
    current_totals = next(
        (
            g for g in event_groups
            if g["period_key"] == (current_period.pk if current_period else None)
        ),
        None,
    )

    # The diversion(s) that fill this basin (Phase 62): each link names the POD
    # and, through it, the real waterway it sits on. A data field on this page,
    # not a flow line on the map.
    pod_links = (
        site.pod_links.select_related(
            "point_of_diversion", "point_of_diversion__source_flowline"
        ).order_by("point_of_diversion__name")
    )

    # 143-10 (R-126): recent readings grouped by what they measure, most
    # recent SIX of each, the unit read off the first row (never assumed --
    # the same column carries mg/L, ft, cfs and in/hr depending on the
    # reading), and the count on record for that type. MEASUREMENT_TYPE_CHOICES
    # order, not alphabetical or by volume; a type with no readings on this
    # site adds no group (rule: a divider says a condition is true).
    measurement_groups = []
    total_measurement_count = 0
    for type_key, type_label in RechargeMeasurement.MEASUREMENT_TYPE_CHOICES:
        type_rows = list(
            RechargeMeasurement.objects.filter(
                recharge_site=site, measurement_type=type_key
            ).order_by("-measurement_date")
        )
        if not type_rows:
            continue
        total_measurement_count += len(type_rows)
        measurement_groups.append({
            "type_key": type_key,
            "display_name": type_label.capitalize(),
            "unit": type_rows[0].unit,
            "rows": type_rows[:6],
            "total_count": len(type_rows),
        })

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
        "event_groups": event_groups,
        "current_period": current_period,
        "current_totals": current_totals,
        "pod_links": pod_links,
        "measurement_groups": measurement_groups,
        "total_measurement_count": total_measurement_count,
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
        events = list(
            RechargeEvent.objects.filter(recharge_site=site)
            .select_related("water_type")
            .order_by("-start_date")
        )
        event_groups = _group_recharge_events(events, ReportingPeriod.objects.all())
        context = {
            "site": site,
            "events": events,
            "event_groups": event_groups,
            "event_form": form,
        }
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

    events = list(
        RechargeEvent.objects.filter(recharge_site=site)
        .select_related("water_type")
        .order_by("-start_date")
    )
    event_groups = _group_recharge_events(events, ReportingPeriod.objects.all())
    context = {
        "site": site,
        "events": events,
        "event_groups": event_groups,
        "event_form": RechargeEventForm(),
        "ledger_msg": ledger_msg,
    }
    return render(request, "recharge/partials/_event_history.html", context)


@public_in_open_demo
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
