import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import Point
from django.core.paginator import Paginator
from django.core.serializers import serialize
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from datasync.models import (
    DataRecordStaging,
    DataSource,
    DataSyncLog,
    MonitoredStation,
    OpenETCache,
)


@login_required
def station_list(request):
    """Paginated list of monitored stations with HTMX search and filter."""
    q = request.GET.get("q", "").strip()
    source = request.GET.get("source", "").strip()
    active = request.GET.get("active", "").strip()

    queryset = MonitoredStation.objects.select_related("data_source").order_by(
        "data_source__code", "station_name"
    )

    if q:
        queryset = queryset.filter(
            Q(station_name__icontains=q) | Q(external_station_id__icontains=q)
        )
    if source:
        queryset = queryset.filter(data_source__code=source)
    if active == "1":
        queryset = queryset.filter(is_active=True)
    elif active == "0":
        queryset = queryset.filter(is_active=False)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "source": source,
        "active": active,
        "data_sources": DataSource.objects.filter(is_active=True).order_by("code"),
    }

    if request.headers.get("HX-Request"):
        return render(request, "datasync/partials/_station_list_results.html", context)

    return render(request, "datasync/station_list.html", context)


@login_required
def station_detail(request, pk):
    """Detail view for a single monitoring station."""
    station = get_object_or_404(
        MonitoredStation.objects.select_related("data_source"), pk=pk
    )

    recent_records = DataRecordStaging.objects.filter(station=station).order_by(
        "-observation_date"
    )[:20]

    recent_logs = DataSyncLog.objects.filter(data_source=station.data_source).order_by(
        "-started_at"
    )[:10]

    # Build point GeoJSON for the embedded map
    station_geojson = None
    if station.location:
        station_geojson = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [station.location.x, station.location.y],
                        },
                        "properties": {
                            "station_name": station.station_name,
                            "external_station_id": station.external_station_id,
                        },
                    }
                ],
            }
        )

    context = {
        "station": station,
        "recent_records": recent_records,
        "recent_logs": recent_logs,
        "station_geojson": station_geojson,
        "lat": station.location.y if station.location else None,
        "lng": station.location.x if station.location else None,
    }
    return render(request, "datasync/station_detail.html", context)


@login_required
@require_http_methods(["POST"])
def station_toggle(request, pk):
    """Toggle is_active for a monitoring station. Returns updated toggle partial."""
    station = get_object_or_404(MonitoredStation, pk=pk)
    station.is_active = not station.is_active
    station.save(update_fields=["is_active", "updated_at"])
    return render(request, "datasync/partials/_station_toggle.html", {"station": station})


@login_required
def station_add(request):
    """Form to add a custom monitoring station."""
    if request.method == "POST":
        source_id = request.POST.get("data_source")
        external_id = request.POST.get("external_station_id", "").strip()
        name = request.POST.get("station_name", "").strip()
        lat_raw = request.POST.get("lat", "").strip()
        lng_raw = request.POST.get("lng", "").strip()

        errors = []
        if not source_id:
            errors.append("Data source is required.")
        if not external_id:
            errors.append("External station ID is required.")
        if not name:
            errors.append("Station name is required.")
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (ValueError, TypeError):
            errors.append("Valid latitude and longitude are required.")
            lat = lng = None

        if not errors:
            try:
                data_source = DataSource.objects.get(pk=source_id)
                station = MonitoredStation.objects.create(
                    data_source=data_source,
                    external_station_id=external_id,
                    station_name=name,
                    location=Point(lng, lat, srid=4326),
                    is_active=True,
                )
                return redirect("datasync:station_detail", pk=station.pk)
            except DataSource.DoesNotExist:
                errors.append("Selected data source does not exist.")

        context = {
            "data_sources": DataSource.objects.filter(is_active=True).order_by("code"),
            "errors": errors,
            "form_data": request.POST,
        }
        return render(request, "datasync/station_add.html", context)

    context = {
        "data_sources": DataSource.objects.filter(is_active=True).order_by("code"),
    }
    return render(request, "datasync/station_add.html", context)


@login_required
def monitoring_dashboard(request):
    """Monitoring dashboard with station health stats, sparklines, and freshness map."""
    now = timezone.now()
    threshold_24h = now - timedelta(hours=24)
    threshold_7d = now - timedelta(days=7)

    active_stations = MonitoredStation.objects.filter(
        is_active=True
    ).select_related("data_source").order_by("data_source__code", "station_name")

    fresh_count = sum(
        1 for s in active_stations
        if s.last_data_at and s.last_data_at >= threshold_24h
    )
    stale_count = sum(
        1 for s in active_stations
        if not s.last_data_at or s.last_data_at < threshold_24h
    )
    total_active = active_stations.count()

    # Most recent DataSyncLog per source
    sources = DataSource.objects.filter(is_active=True).order_by("code")
    recent_logs_by_source = {}
    for source in sources:
        log = DataSyncLog.objects.filter(data_source=source).order_by("-started_at").first()
        recent_logs_by_source[source.code] = {
            "source": source,
            "log": log,
        }

    # Station counts by source
    source_stats = {}
    for source in sources:
        source_stats[source.code] = {
            "source": source,
            "total": MonitoredStation.objects.filter(data_source=source).count(),
            "active": MonitoredStation.objects.filter(data_source=source, is_active=True).count(),
        }

    # Sparkline data: last 10 DataRecordStaging per active station
    station_ids = list(active_stations.values_list("pk", flat=True))
    staging_qs = (
        DataRecordStaging.objects
        .filter(station__in=station_ids)
        .order_by("station_id", "-observation_date")
        .values("station_id", "value", "observation_date")
    )

    # Group by station, keep latest 10 per station
    raw_records: dict = {}
    for row in staging_qs:
        sid = row["station_id"]
        if sid not in raw_records:
            raw_records[sid] = []
        if len(raw_records[sid]) < 10:
            raw_records[sid].append(row["value"])

    # Build sparkline SVG path strings per station
    station_sparklines = {}
    for sid, values in raw_records.items():
        # Reverse so oldest is on left
        vals = list(reversed(values))
        numeric = [float(v) for v in vals if v is not None]
        if len(numeric) < 2:
            station_sparklines[sid] = None
            continue
        min_v = min(numeric)
        max_v = max(numeric)
        span = max_v - min_v if max_v != min_v else 1.0
        width = 80
        height = 24
        n = len(numeric)
        points = []
        for i, v in enumerate(numeric):
            x = round(i * (width - 1) / (n - 1), 2)
            y = round(height - ((v - min_v) / span) * (height - 4) - 2, 2)
            points.append(f"{x},{y}")
        station_sparklines[sid] = " ".join(points)

    # Determine freshness class for each active station
    station_list = []
    for s in active_stations:
        if s.last_data_at and s.last_data_at >= threshold_24h:
            freshness = "fresh"
        elif s.last_data_at and s.last_data_at >= threshold_7d:
            freshness = "stale"
        else:
            freshness = "dead"
        station_list.append({
            "station": s,
            "freshness": freshness,
            "sparkline_points": station_sparklines.get(s.pk),
        })

    # OpenET budget
    _, openet_used, openet_limit = OpenETCache.check_budget()

    context = {
        "source_stats": source_stats,
        "stale_count": stale_count,
        "fresh_count": fresh_count,
        "total_active": total_active,
        "recent_logs_by_source": recent_logs_by_source,
        "station_list": station_list,
        "openet_used": openet_used,
        "openet_limit": openet_limit,
    }

    if request.headers.get("HX-Request"):
        return render(request, "datasync/partials/_monitoring_content.html", context)

    return render(request, "datasync/monitoring_dashboard.html", context)


@login_required
def stations_freshness_geojson(request):
    """Return active stations as GeoJSON with freshness metadata."""
    now = timezone.now()
    threshold_24h = now - timedelta(hours=24)
    threshold_7d = now - timedelta(days=7)

    stations = MonitoredStation.objects.filter(
        is_active=True, location__isnull=False
    ).select_related("data_source")

    features = []
    for s in stations:
        if s.last_data_at and s.last_data_at >= threshold_24h:
            freshness = "fresh"
            hours_since = (now - s.last_data_at).total_seconds() / 3600
        elif s.last_data_at and s.last_data_at >= threshold_7d:
            freshness = "stale"
            hours_since = (now - s.last_data_at).total_seconds() / 3600
        else:
            freshness = "dead"
            hours_since = (
                (now - s.last_data_at).total_seconds() / 3600
                if s.last_data_at else None
            )

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s.location.x, s.location.y],
            },
            "properties": {
                "pk": s.pk,
                "station_name": s.station_name,
                "external_station_id": s.external_station_id,
                "data_source_code": s.data_source.code,
                "freshness": freshness,
                "hours_since_data": round(hours_since, 1) if hours_since is not None else None,
                "last_data_at": s.last_data_at.isoformat() if s.last_data_at else None,
            },
        })

    data = {"type": "FeatureCollection", "features": features}
    return HttpResponse(json.dumps(data), content_type="application/json")


@login_required
def stations_geojson(request):
    """Return all active monitored stations as a GeoJSON FeatureCollection."""
    stations = MonitoredStation.objects.filter(
        is_active=True, location__isnull=False
    ).select_related("data_source")

    features = []
    for s in stations:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [s.location.x, s.location.y],
                },
                "properties": {
                    "pk": s.pk,
                    "station_name": s.station_name,
                    "external_station_id": s.external_station_id,
                    "data_source_code": s.data_source.code,
                    "is_active": s.is_active,
                    "last_data_at": s.last_data_at.isoformat() if s.last_data_at else None,
                },
            }
        )

    data = {"type": "FeatureCollection", "features": features}
    return HttpResponse(json.dumps(data), content_type="application/json")
