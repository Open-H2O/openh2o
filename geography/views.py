# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Geography views.

The map and zone surfaces: the interactive MapLibre map (map_view), zone
management (list/detail/create, parcel assignment), and the per-district
year-end recovery-horizon override. Also serves the spatial layers as GeoJSON
endpoints — boundaries, zones, flowlines, zone labels, and the tie lines that
draw wells and points of diversion to the parcel centroids they serve.
"""
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.cache import cache
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounting.models import AllocationPlan
from accounting.services import billable_ledger
from core.access import admin_required
from core.constants import RECOVERY_HORIZON_CHOICES
from core.models import SiteConfig
from core.workspace import detail_response, list_response
from geography.forms import ZoneForm
from geography.models import Boundary, Flowline, ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger
from wells.models import WellIrrigatedParcel


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------


@login_required
def map_view(request):
    """Interactive map with all spatial layers. Uses map-engine.js."""
    center_lng = -119.5
    center_lat = 37.5
    zoom = 6

    # Default the map to the Merced Subbasin (the v1.9 demonstration area).
    # Fall back to any boundary so a fresh / non-Merced install still frames.
    boundary = (
        Boundary.objects.filter(name="Merced Subbasin").first()
        or Boundary.objects.first()
    )
    if boundary and boundary.geometry:
        centroid = boundary.geometry.centroid
        center_lng = centroid.x
        center_lat = centroid.y
        extent = boundary.geometry.extent
        bounds = json.dumps([
            [extent[0], extent[1]],
            [extent[2], extent[3]],
        ])
    else:
        bounds = "null"

    # GSA-zone legend + fill colors, DERIVED from the live management-area zones
    # so the legend can never name a basin that isn't in the database. (A
    # hardcoded Kaweah legend survived the v1.9 Kaweah→Merced demo migration and
    # showed retired-basin names on the live map — post-mortem 2026-06-08.)
    zone_palette = ["#2d6a4f", "#40916c", "#52b788", "#74c69d", "#95d5b2"]
    gsa_zones = [
        {"name": name, "color": zone_palette[i % len(zone_palette)]}
        for i, name in enumerate(
            Zone.objects.filter(zone_type="management_area", geometry__isnull=False)
            .order_by("name")
            .values_list("name", flat=True)
        )
    ]

    return render(request, "geography/map.html", {
        "center_lng": center_lng,
        "center_lat": center_lat,
        "zoom": zoom,
        "bounds": bounds,
        "gsa_zones": gsa_zones,
    })


# ---------------------------------------------------------------------------
# Zone management
# ---------------------------------------------------------------------------


@login_required
def zone_list(request):
    """Zones OVERVIEW: a boundary map of every zone + a searchable list.

    Zones are a Bucket-3 screen (few items, each heavy): an instance has a
    handful of bounded management areas, and each zone's detail is rich (its
    boundary mapped, assigned use areas, the allocation-vs-use table, and the
    per-district year-end-water control). So this screen is a finder, not a
    master-detail half-pane: the map up top shows all zone boundaries at once,
    the full-width list below is for finding one fast, and clicking a row (or a
    zone on the map) opens that zone's own full-width detail page. See
    ``docs/2.0-UX-PATTERN-SPEC.md`` for why this is Bucket 3, not master-detail.

    Returns the ``_zone_list_results`` partial for an HTMX list refresh (search /
    filter / pagination, which target ``#results``), and the full page otherwise.
    """
    q = request.GET.get("q", "").strip()
    zone_type = request.GET.get("zone_type", "").strip()

    queryset = (
        Zone.objects
        .annotate(parcel_count=Count("parcel_zones"))
        .order_by("name")
    )

    if q:
        queryset = queryset.filter(Q(name__icontains=q))
    if zone_type:
        queryset = queryset.filter(zone_type=zone_type)

    # Zones are bounded and few, so show them all on one page — finding one is a
    # glance plus a type-to-filter, not a paging exercise. Pagination stays as a
    # graceful fallback for an unusually large district.
    paginator = Paginator(queryset, 100)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "zone_type": zone_type,
        "zone_type_choices": Zone.ZONE_TYPE_CHOICES,
    }

    return list_response(
        request,
        page_template="geography/zone_list.html",
        results_template="geography/partials/_zone_list_results.html",
        context=context,
    )


def _zone_detail_context(zone):
    """Build the per-zone detail context.

    Shared by the standalone detail page, the in-pane HTMX render, and the
    workspace's pre-loaded ``?selected=`` pane so all three are identical.
    """
    # Assigned parcels via ParcelZone
    parcel_zones = (
        ParcelZone.objects
        .filter(zone=zone)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    # Allocations for this zone (any period)
    allocations = (
        AllocationPlan.objects
        .filter(zone=zone)
        .select_related("reporting_period", "water_type")
        .order_by("-reporting_period__start_date")
    )

    # Allocation vs. use (Phase 52-02): an allocation number alone doesn't tell the story —
    # an evaluator needs "of X allocated, Y was used". For each allocation, compute the
    # matching draw against the zone's parcels in that period: groundwater allocations
    # show metered/estimated PUMPING (the magnitude of the negative extraction
    # rows); surface allocations show DELIVERED canal water (the surface-delivery rows
    # only — allocations are excluded so we don't count the grant as a use).
    zone_parcel_ids = list(parcel_zones.values_list("parcel_id", flat=True))
    budgets = []
    for alloc in allocations:
        period_rows = billable_ledger(
            ParcelLedger.objects.filter(
                parcel_id__in=zone_parcel_ids,
                reporting_period=alloc.reporting_period,
            )
        )
        if (alloc.water_type.code or "").upper() == "GW":
            used = abs(
                period_rows.filter(amount_acre_feet__lt=0).aggregate(
                    s=Sum("amount_acre_feet")
                )["s"]
                or Decimal("0")
            )
            used_label = "pumped"
        else:
            # surface_diversion is stored NEGATIVE (production convention); the
            # delivered magnitude is its absolute value, so remaining =
            # budget − delivered reads correctly.
            used = abs(
                period_rows.filter(source_type="surface_diversion").aggregate(
                    s=Sum("amount_acre_feet")
                )["s"]
                or Decimal("0")
            )
            used_label = "delivered"
        budget = alloc.allocation_acre_feet or Decimal("0")
        budgets.append({
            "period": alloc.reporting_period,
            "water_type": alloc.water_type,
            "budget": budget,
            "used": used,
            "used_label": used_label,
            "remaining": budget - used,
        })

    # Curtailment narrative — flag the zone if any of its parcels is served by a
    # curtailed water right, and surface the matching active order (by priority-
    # date cutoff). Tells the El Nido story on the district page, not just via the
    # collapsed open-year budget number.
    # Local import: `surface` is an optional module (Phase 87), so this must not
    # run at module scope — importing surface.models with the app uninstalled
    # raises RuntimeError before any useful error prints.
    from surface.models import CurtailmentOrder, WaterRight

    curtailment_orders = []
    is_curtailed = WaterRight.objects.filter(
        status="curtailed", water_right_parcels__parcel_id__in=zone_parcel_ids
    ).exists()
    if is_curtailed:
        cutoffs = list(
            WaterRight.objects.filter(
                status="curtailed",
                water_right_parcels__parcel_id__in=zone_parcel_ids,
                priority_date__isnull=False,
            ).values_list("priority_date", flat=True)
        )
        curtailment_orders = list(
            CurtailmentOrder.objects.filter(
                status="active", priority_date_cutoff__in=cutoffs
            )
        )

    # GeoJSON for the persistent detail map. A FeatureCollection (via serialize)
    # so OH2O.detailPaneMap reads it exactly as it does for every other screen;
    # it auto-detects the zone's polygon boundary (fill + outline). A Python
    # object (or None): the template escapes it via json_script so the zone name
    # can't break out of <script>.
    geojson = None
    if zone.geometry:
        geojson = json.loads(
            serialize(
                "geojson",
                [zone],
                geometry_field="geometry",
                fields=["name", "zone_type"],
            )
        )

    context = {
        "zone": zone,
        "parcel_zones": parcel_zones,
        "allocations": allocations,
        "budgets": budgets,
        "is_curtailed": is_curtailed,
        "curtailment_orders": curtailment_orders,
        "geojson": geojson,
    }
    context.update(_recovery_horizon_context(zone))
    return context


@login_required
def zone_detail(request, pk):
    """A single zone's detail.

    On an HTMX request it returns just the ``_zone_detail_pane`` fragment (the
    workspace swaps this into ``#detail-body``); otherwise it returns the
    standalone page, which deep links and no-HTMX clients still reach.
    """
    zone = get_object_or_404(Zone, pk=pk)
    context = _zone_detail_context(zone)
    return detail_response(
        request,
        pane_template="geography/partials/_zone_detail_pane.html",
        page_template="geography/zone_detail.html",
        context=context,
    )


# ---------------------------------------------------------------------------
# Per-district year-end-unused-water override (Phase 55-03)
# ---------------------------------------------------------------------------
#
# A surface district IS its own Zone, so the per-district override of the
# agency-wide year-end policy lives on Zone.recovery_horizon. "Dense, not
# hidden": the resolved policy is always shown as one quiet line; the control to
# change it for this one district sits right beside it. Clearing the override
# sets the field back to NULL — never the literal default — so a later change to
# the agency default still flows through to this district.

# Plain-language phrasings (no internal jargon). The short phrase appears inside
# the "Using agency default (...)" line; the action label is on the buttons.
_HORIZON_PHRASE = {
    "carry_forward": "carry forward",
    "same_water_year": "expire at year-end",
}


def _recovery_horizon_context(zone):
    """Context for the per-district year-end-unused-water control.

    Resolves the effective policy (override else agency default), and reports
    whether THIS district is on the default or carries its own override, so the
    template can render the "Using agency default (...)" line vs. an explicit
    override and highlight the active choice.
    """
    from accounting.services import resolve_recovery_horizon

    agency_default = SiteConfig.objects.first()
    agency_value = (
        agency_default.default_recovery_horizon if agency_default else "carry_forward"
    )
    override = zone.recovery_horizon or None
    effective = resolve_recovery_horizon(zone)
    return {
        "zone": zone,
        "rh_override": override,  # None => using the agency default
        "rh_effective": effective,
        "rh_effective_phrase": _HORIZON_PHRASE.get(effective, effective),
        "rh_agency_phrase": _HORIZON_PHRASE.get(agency_value, agency_value),
    }


@login_required
@admin_required
@require_POST
def zone_recovery_horizon(request, pk):
    """Set or clear this district's year-end-unused-water override, HTMX-inline.

    The posted ``recovery_horizon`` is either one of the two choice strings (set
    an override) or empty / ``"default"`` (clear it). CLEARING stores NULL, not
    the agency default literal — that null is what lets a later agency-default
    change flow through to this district. Re-renders the one-line control in place
    (mirrors methodology_step_toggle's partial-swap pattern).
    """
    zone = get_object_or_404(Zone, pk=pk)
    choice = (request.POST.get("recovery_horizon") or "").strip()
    valid = {c[0] for c in RECOVERY_HORIZON_CHOICES}
    if choice in valid:
        zone.recovery_horizon = choice
    else:
        # "default" / blank / anything else => inherit the agency default (NULL).
        zone.recovery_horizon = None
    zone.save(update_fields=["recovery_horizon"])
    return render(
        request,
        "geography/partials/_zone_recovery_horizon.html",
        _recovery_horizon_context(zone),
    )


@login_required
def zone_create(request):
    """Create a new zone with map polygon drawing."""
    if request.method == "POST":
        form = ZoneForm(request.POST)
        if form.is_valid():
            zone = form.save(commit=False)

            # Parse geometry from hidden input
            geometry_json = request.POST.get("geometry_json", "")
            geometry = _parse_polygon(geometry_json)
            if not geometry:
                return render(request, "geography/zone_create.html", {
                    "form": form,
                    "error": "A polygon boundary is required. Draw a polygon on the map.",
                })

            zone.geometry = geometry

            # Auto-assign boundary to first Boundary object
            boundary = Boundary.objects.first()
            if not boundary:
                return render(request, "geography/zone_create.html", {
                    "form": form,
                    "error": "No district boundary configured. Create a boundary first in the admin.",
                })
            zone.boundary = boundary
            zone.save()
            return redirect("geography:zone_detail", pk=zone.pk)
    else:
        form = ZoneForm()

    return render(request, "geography/zone_create.html", {"form": form})


@login_required
@require_POST
def zone_parcel_assign(request, pk):
    """Assign a parcel to a zone. Creates ParcelZone."""
    zone = get_object_or_404(Zone, pk=pk)
    parcel_id = request.POST.get("parcel_id")
    parcel = get_object_or_404(Parcel, pk=parcel_id)

    ParcelZone.objects.get_or_create(zone=zone, parcel=parcel)

    parcel_zones = (
        ParcelZone.objects
        .filter(zone=zone)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    return render(request, "geography/partials/_zone_parcels.html", {
        "zone": zone,
        "parcel_zones": parcel_zones,
    })


@login_required
@require_POST
def zone_parcel_remove(request, pk, pz_pk):
    """Remove a parcel from a zone. Deletes the ParcelZone."""
    zone = get_object_or_404(Zone, pk=pk)
    pz = get_object_or_404(ParcelZone, pk=pz_pk, zone=zone)
    pz.delete()

    parcel_zones = (
        ParcelZone.objects
        .filter(zone=zone)
        .select_related("parcel")
        .order_by("parcel__parcel_number")
    )

    return render(request, "geography/partials/_zone_parcels.html", {
        "zone": zone,
        "parcel_zones": parcel_zones,
    })


@login_required
def zone_parcel_search(request, pk):
    """HTMX GET endpoint: search parcels not already in this zone."""
    zone = get_object_or_404(Zone, pk=pk)
    q = request.GET.get("q", "").strip()

    results = []
    if q:
        already_assigned = ParcelZone.objects.filter(
            zone=zone
        ).values_list("parcel_id", flat=True)

        results = (
            Parcel.objects.filter(
                Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
            )
            .exclude(pk__in=already_assigned)
            .order_by("parcel_number")[:10]
        )

    return render(request, "geography/partials/_zone_parcel_search_results.html", {
        "zone": zone,
        "results": results,
        "q": q,
    })


@login_required
def zone_geojson_single(request, pk):
    """Return GeoJSON for a single zone."""
    zone = get_object_or_404(Zone, pk=pk)
    if not zone.geometry:
        return HttpResponse(
            json.dumps({"type": "FeatureCollection", "features": []}),
            content_type="application/json",
        )
    data = serialize(
        "geojson",
        Zone.objects.filter(pk=pk),
        geometry_field="geometry",
        fields=["name", "zone_type"],
    )
    return HttpResponse(data, content_type="application/json")


# ---------------------------------------------------------------------------
# GeoJSON endpoints
# ---------------------------------------------------------------------------


@login_required
def tie_lines_geojson(request):
    """Return GeoJSON FeatureCollection of LineString tie lines connecting wells/PODs to parcel centroids."""
    features = []

    # Groundwater tie lines: well -> parcel centroid
    for wip in WellIrrigatedParcel.objects.select_related("well", "parcel").all():
        parcel = wip.parcel
        if not parcel.geometry:
            continue
        well = wip.well
        centroid = parcel.geometry.centroid
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [well.location.x, well.location.y],
                    [centroid.x, centroid.y],
                ],
            },
            "properties": {
                "source_type": "gw",
                "source_name": str(well),
                "parcel_number": parcel.parcel_number,
                "fraction": float(wip.fraction),
                "source_id": well.pk,
                "parcel_id": parcel.pk,
            },
        })

    # Surface water tie lines: POD -> parcel centroid
    # Local import: `surface` is an optional module (Phase 87) — see
    # `_zone_detail_context`.
    from surface.models import PointOfDiversionParcel

    for podp in PointOfDiversionParcel.objects.select_related("point_of_diversion", "parcel").all():
        parcel = podp.parcel
        if not parcel.geometry:
            continue
        pod = podp.point_of_diversion
        centroid = parcel.geometry.centroid
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [pod.location.x, pod.location.y],
                    [centroid.x, centroid.y],
                ],
            },
            "properties": {
                "source_type": "sw",
                "source_name": str(pod),
                "parcel_number": parcel.parcel_number,
                "fraction": float(podp.fraction),
                "source_id": pod.pk,
                "parcel_id": parcel.pk,
            },
        })

    data = json.dumps({"type": "FeatureCollection", "features": features})
    return HttpResponse(data, content_type="application/json")


def _round_coords(node, ndigits=6):
    """Recursively round the coordinate floats in a GeoJSON coordinates array.

    A leaf is a flat list of numbers (one position, possibly with a Z value);
    anything deeper is a nested ring/part, so recurse. Non-floats (ints) pass
    through untouched.
    """
    if isinstance(node, list):
        if node and all(isinstance(n, (int, float)) for n in node):
            return [round(n, ndigits) if isinstance(n, float) else n for n in node]
        return [_round_coords(c, ndigits) for c in node]
    return node


def _layer_signature(qs):
    """A cheap (count, max-pk) cache signature for a layer queryset.

    One aggregate query. The pair is unique per dataset state: a reseed
    (delete+recreate) raises max-pk even if the count is unchanged, so a stale
    cached body is never served across a reseed, and two different layers that
    happen to share a count never collide.
    """
    agg = qs.aggregate(c=Count("pk"), m=Max("pk"))
    return f"{agg['c']}:{agg['m']}"


def _geojson_response(cache_key, build, *, max_age=3600, mutate=None):
    """Serialize a layer once, trim coordinate precision, cache the bytes, return.

    Map layers render at zoom <= 18, where 6-decimal degrees (~0.1 m) is already
    sub-pixel, so trimming Django's full float precision is visually lossless while
    roughly halving the payload (the flowlines layer alone is ~2.8 MB raw). The
    rounded, whitespace-stripped body is cached so the serialize+parse+round cost
    runs once per period instead of on every request; ``cache_key`` carries the
    layer's (count, max-pk) signature so a reseed busts it, and the per-process
    LocMemCache also clears on every deploy/rebuild. ``Cache-Control`` lets the
    browser reuse it across navigations.

    ``build`` is a callable returning the raw ``serialize("geojson", ...)`` string;
    ``mutate`` optionally post-processes the parsed dict before rounding.
    """
    body = cache.get(cache_key)
    if body is None:
        data = json.loads(build())
        if mutate is not None:
            mutate(data)
        for feature in data.get("features", []):
            geom = feature.get("geometry")
            if geom and geom.get("coordinates") is not None:
                geom["coordinates"] = _round_coords(geom["coordinates"])
        body = json.dumps(data, separators=(",", ":"))
        cache.set(cache_key, body, max_age)
    response = HttpResponse(body, content_type="application/json")
    response["Cache-Control"] = f"public, max-age={max_age}"
    return response


@login_required
def boundaries_geojson(request):
    """Return all boundaries as a GeoJSON FeatureCollection."""
    qs = Boundary.objects.filter(geometry__isnull=False)
    return _geojson_response(
        f"geojson:boundaries:{_layer_signature(qs)}",
        lambda: serialize(
            "geojson", qs, geometry_field="geometry",
            fields=["name", "description", "area_sq_miles"],
        ),
    )


@login_required
def flowlines_geojson(request):
    """Return the significant flowlines (named waterways + all canals) as GeoJSON.

    The hydrography renderer: the map's "Surface Water" layers filter on
    feature_type (canals vs natural channels) and label on name.

    **Scale guard (50-02):** the USGS 3DHP source is exhaustive — the real
    Merced data is ~48,700 flowlines (30 MB serialized), most of them tiny
    unnamed first-order capillaries in the Sierra headwaters of the upper
    watershed. Serving all of them makes the map payload unusable and buries
    the canal network in noise. We render the *significant* set: every canal
    (man-made infrastructure is always relevant) plus every named natural
    waterway (a GNIS name marks a flowline worth showing). That keeps the full
    Merced Irrigation District canal mesh and the named Merced River system
    while dropping the unnamed capillaries. Coordinate precision is trimmed to
    6 decimals (sub-pixel) which roughly halves the payload — the single biggest
    map asset.

    The `geometry__isnull=False` filter mirrors the peer endpoints;
    Flowline.geometry is non-nullable so it is defensive parity.
    """
    significant = Q(feature_type__icontains="Canal") | ~Q(name="")
    qs = Flowline.objects.filter(significant, geometry__isnull=False)
    return _geojson_response(
        f"geojson:flowlines:{_layer_signature(qs)}",
        lambda: serialize(
            "geojson", qs, geometry_field="geometry",
            fields=["name", "feature_type", "stream_order"],
        ),
    )


@login_required
def zones_geojson(request):
    """Return all zones as a GeoJSON FeatureCollection."""
    qs = Zone.objects.filter(geometry__isnull=False)
    return _geojson_response(
        f"geojson:zones:{_layer_signature(qs)}",
        lambda: serialize(
            "geojson", qs, geometry_field="geometry",
            fields=["name", "zone_type"],
        ),
    )


@login_required
def zone_overview_geojson(request):
    """Zone boundaries for the Zones overview map, with ``pk`` in properties.

    The shared ``zones_geojson`` above is built by Django's serializer, which
    puts the primary key at the GeoJSON feature's top level, not in
    ``properties`` — so a MapLibre click handler can't read it to build the
    detail URL. This endpoint hand-builds the FeatureCollection (the same way
    ``datasync.stations_geojson`` does) so the overview map can navigate to a
    zone's full detail page on click. Counts are cheap (a district has a handful
    of zones), so this is not on a hot path.
    """
    zones = (
        Zone.objects
        .filter(geometry__isnull=False)
        .annotate(parcel_count=Count("parcel_zones"))
    )
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(zone.geometry.geojson),
            "properties": {
                "pk": zone.pk,
                "name": zone.name,
                "zone_type": zone.zone_type,
                "zone_type_label": zone.get_zone_type_display(),
                "parcel_count": zone.parcel_count,
            },
        }
        for zone in zones
    ]
    return HttpResponse(
        json.dumps({"type": "FeatureCollection", "features": features}),
        content_type="application/json",
    )


@login_required
def zone_labels_geojson(request):
    """One label point per zone (point_on_surface).

    Zone geometries are MultiPolygons with many disjoint parts (a GSA is a
    union of scattered parcels). A symbol layer placed on the polygon source
    stamps the zone name once *per part* — a multi-part GSA appeared a dozen-plus
    times across the map. Labeling a single interior point per zone gives
    exactly one clean, well-placed label.
    """
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(zone.geometry.point_on_surface.geojson),
            "properties": {"name": zone.name},
        }
        for zone in Zone.objects.filter(geometry__isnull=False)
    ]
    return HttpResponse(
        json.dumps({"type": "FeatureCollection", "features": features}),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Helpers (duplicated from infrastructure/views.py — polygon parsing)
# ---------------------------------------------------------------------------


def _parse_polygon(geometry_json):
    """Parse a GeoJSON Polygon or MultiPolygon string into a MultiPolygon GEOS object."""
    if not geometry_json:
        return None
    try:
        data = json.loads(geometry_json)
        if data.get("type") == "Polygon":
            poly = Polygon(data["coordinates"][0], srid=4326)
            return MultiPolygon(poly, srid=4326)
        elif data.get("type") == "MultiPolygon":
            return MultiPolygon(GEOSGeometry(json.dumps(data), srid=4326))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    return None
