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

from datasync.adapters.registry import get_parameter_label
from datasync.models import (
    DataRecordStaging,
    DataSource,
    DataSyncLog,
    MonitoredStation,
    OpenETCache,
)
from geography.models import Boundary


@login_required
def station_list(request):
    """Unified station list with monitoring stats, freshness map, and enriched table."""
    now = timezone.now()
    threshold_24h = now - timedelta(hours=24)
    threshold_7d = now - timedelta(days=7)

    q = request.GET.get("q", "").strip()
    source = request.GET.get("source", "").strip()
    active = request.GET.get("active", "").strip()

    boundary = Boundary.objects.first()

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

    # Freshness classification for current page stations
    station_freshness = {}
    for s in page_obj:
        if s.last_data_at and s.last_data_at >= threshold_24h:
            station_freshness[s.pk] = "fresh"
        elif s.last_data_at and s.last_data_at >= threshold_7d:
            station_freshness[s.pk] = "stale"
        else:
            station_freshness[s.pk] = "dead"

    # Sparkline data for current page stations
    page_station_ids = [s.pk for s in page_obj]
    staging_qs = (
        DataRecordStaging.objects
        .filter(station__in=page_station_ids)
        .order_by("station_id", "-observation_date")
        .values("station_id", "value")
    )
    raw_records: dict = {}
    for row in staging_qs:
        sid = row["station_id"]
        if sid not in raw_records:
            raw_records[sid] = []
        if len(raw_records[sid]) < 10:
            raw_records[sid].append(row["value"])

    station_sparklines = {}
    for sid, values in raw_records.items():
        vals = list(reversed(values))
        numeric = [float(v) for v in vals if v is not None]
        if len(numeric) < 2:
            continue
        min_v, max_v = min(numeric), max(numeric)
        span = max_v - min_v if max_v != min_v else 1.0
        points = []
        for i, v in enumerate(numeric):
            x = round(i * 119 / (len(numeric) - 1), 2)
            y = round(40 - ((v - min_v) / span) * 34 - 2, 2)
            points.append(f"{x},{y}")
        station_sparklines[sid] = " ".join(points)

    # Enrich page objects with freshness and sparkline
    enriched_stations = []
    for s in page_obj:
        enriched_stations.append({
            "station": s,
            "freshness": station_freshness.get(s.pk, "dead"),
            "sparkline_points": station_sparklines.get(s.pk),
        })

    context = {
        "page_obj": page_obj,
        "enriched_stations": enriched_stations,
        "total_count": paginator.count,
        "q": q,
        "source": source,
        "active": active,
        "data_sources": DataSource.objects.filter(is_active=True).order_by("code"),
    }

    if request.headers.get("HX-Request"):
        return render(request, "datasync/partials/_station_list_results.html", context)

    # Full page: add summary stats and source status
    all_active = MonitoredStation.objects.filter(is_active=True)
    total_active = all_active.count()
    fresh_count = sum(1 for s in all_active if s.last_data_at and s.last_data_at >= threshold_24h)
    stale_count = total_active - fresh_count

    sources = DataSource.objects.filter(is_active=True).order_by("code")
    source_status_list = []
    for src in sources:
        log = DataSyncLog.objects.filter(data_source=src).order_by("-started_at").first()
        src_stations = MonitoredStation.objects.filter(data_source=src)
        total = src_stations.count()
        src_active = src_stations.filter(is_active=True).count()
        source_status_list.append({
            "source": src,
            "log": log,
            "total": total,
            "active": src_active,
        })

    _, openet_used, openet_limit = OpenETCache.check_budget()

    context.update({
        "total_active": total_active,
        "fresh_count": fresh_count,
        "stale_count": stale_count,
        "source_status_list": source_status_list,
        "openet_used": openet_used,
        "openet_limit": openet_limit,
        "boundary_name": boundary.name if boundary else None,
    })

    return render(request, "datasync/station_list.html", context)


@login_required
def station_detail(request, pk):
    """Detail view for a single monitoring station."""
    station = get_object_or_404(
        MonitoredStation.objects.select_related("data_source"), pk=pk
    )

    recent_records_qs = DataRecordStaging.objects.filter(station=station).order_by(
        "-observation_date"
    )[:10]
    recent_records = list(recent_records_qs)
    source_code = station.data_source.code
    for rec in recent_records:
        rec.param_display = get_parameter_label(source_code, rec.parameter_code)

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

    # Determine freshness for chart color
    now_ts = timezone.now()
    threshold_24h = now_ts - timedelta(hours=24)
    if station.last_data_at and station.last_data_at >= threshold_24h:
        station_freshness = "fresh"
    elif station.last_data_at:
        station_freshness = "stale"
    else:
        station_freshness = "dead"

    # Build enriched parameter list so template dropdown shows human labels on first render
    enriched_parameters = [
        {"code": code, "label": get_parameter_label(source_code, code)}
        for code in (station.parameters or [])
    ]

    context = {
        "station": station,
        "recent_records": recent_records,
        "recent_logs": recent_logs,
        "station_geojson": station_geojson,
        "lat": station.location.y if station.location else None,
        "lng": station.location.x if station.location else None,
        "station_freshness": station_freshness,
        "chart_data_url": f"/datasync/stations/{station.pk}/chart-data/",
        "enriched_parameters": enriched_parameters,
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

    boundary = Boundary.objects.first()

    active_stations = MonitoredStation.objects.filter(
        is_active=True
    ).select_related("data_source").order_by("data_source__code", "station_name")
    if boundary:
        active_stations = active_stations.filter(location__within=boundary.geometry)

    fresh_count = sum(
        1 for s in active_stations
        if s.last_data_at and s.last_data_at >= threshold_24h
    )
    stale_count = sum(
        1 for s in active_stations
        if not s.last_data_at or s.last_data_at < threshold_24h
    )
    total_active = active_stations.count()

    # Source stats with most recent log per source (boundary-scoped)
    sources = DataSource.objects.filter(is_active=True).order_by("code")
    source_status_list = []
    for source in sources:
        log = DataSyncLog.objects.filter(data_source=source).order_by("-started_at").first()
        src_stations = MonitoredStation.objects.filter(data_source=source)
        if boundary:
            src_stations = src_stations.filter(location__within=boundary.geometry)
        total = src_stations.count()
        active = src_stations.filter(is_active=True).count()
        source_status_list.append({
            "source": source,
            "log": log,
            "total": total,
            "active": active,
        })

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
        width = 120
        height = 40
        n = len(numeric)
        points = []
        for i, v in enumerate(numeric):
            x = round(i * (width - 1) / (n - 1), 2)
            y = round(height - ((v - min_v) / span) * (height - 6) - 2, 2)
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
        "source_status_list": source_status_list,
        "stale_count": stale_count,
        "fresh_count": fresh_count,
        "total_active": total_active,
        "station_list": station_list,
        "openet_used": openet_used,
        "openet_limit": openet_limit,
        "boundary_name": boundary.name if boundary else None,
    }

    if request.headers.get("HX-Request"):
        return render(request, "datasync/partials/_monitoring_content.html", context)

    return render(request, "datasync/monitoring_dashboard.html", context)


@login_required
def station_chart_data(request, pk):
    """Return JSON chart data for a station's telemetry records."""
    station = get_object_or_404(MonitoredStation, pk=pk)

    parameter = request.GET.get("parameter", "").strip()
    days_raw = request.GET.get("days", "0")
    try:
        days = int(days_raw)
    except (ValueError, TypeError):
        days = 0
    if days > 0:
        days = max(7, days)

    date_filter = {}
    if days > 0:
        date_filter["observation_date__gte"] = timezone.now() - timedelta(days=days)

    # Determine available parameters from published records
    available_params_qs = (
        DataRecordStaging.objects
        .filter(station=station, status="published", **date_filter)
        .values("parameter_code", "unit")
        .distinct()
        .order_by("parameter_code")
    )
    param_codes = [r["parameter_code"] for r in available_params_qs]
    units_by_code = {r["parameter_code"]: r["unit"] for r in available_params_qs}

    # Fall back to station.parameters if no published data yet
    if not param_codes and station.parameters:
        param_codes = list(station.parameters)

    # Default to first parameter if none specified or specified one not available
    if not parameter or parameter not in param_codes:
        parameter = param_codes[0] if param_codes else None

    # Build parameter metadata list using the unified registry
    source_code = station.data_source.code
    parameters_meta = []
    for code in param_codes:
        unit = units_by_code.get(code, "")
        label = get_parameter_label(source_code, code)
        # Extract name without unit for the name field (strip trailing " (unit)" if present)
        if unit and label.endswith(f" ({unit})"):
            name = label[: -(len(unit) + 3)]
        else:
            name = label
        parameters_meta.append({"code": code, "name": name, "unit": unit, "label": label})

    labels = []
    data_values = []
    dataset_label = ""

    if parameter:
        records = (
            DataRecordStaging.objects
            .filter(station=station, status="published", parameter_code=parameter,
                    **date_filter)
            .order_by("observation_date")
            .values("observation_date", "value", "unit")
        )
        for r in records:
            labels.append(r["observation_date"].strftime("%Y-%m-%d"))
            data_values.append(float(r["value"]) if r["value"] is not None else None)

        dataset_label = get_parameter_label(source_code, parameter)

    result = {
        "labels": labels,
        "datasets": [
            {
                "label": dataset_label,
                "data": data_values,
                "parameter_code": parameter,
            }
        ] if parameter else [],
        "parameters": parameters_meta,
        "selected_parameter": parameter,
        "days": days,
    }
    return JsonResponse(result)


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
