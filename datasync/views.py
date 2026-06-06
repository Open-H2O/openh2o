# SPDX-License-Identifier: AGPL-3.0-or-later
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

from datasync import freshness
from datasync.adapters.registry import get_parameter_label
from datasync.models import (
    DataRecordStaging,
    DataSource,
    DataSyncLog,
    MonitoredStation,
    OpenETCache,
)
from geography.models import Boundary


def _build_source_status(boundary, now):
    """
    Per-source status for the dashboard cards: station counts, the most recent
    sync log, a source-aware fresh count, and an honest status code/label that
    distinguishes "needs key" / "no stations" / "no recent data" from "failed".
    """
    sources = DataSource.objects.filter(is_active=True).order_by("code")
    result = []
    for src in sources:
        src_stations = MonitoredStation.objects.filter(data_source=src)
        if boundary:
            src_stations = src_stations.filter(location__within=boundary.geometry)
        total = src_stations.count()
        active_qs = src_stations.filter(is_active=True)
        active = active_qs.count()
        fresh = sum(
            1 for s in active_qs
            if freshness.classify_freshness(src.code, s.last_data_at, now) == "fresh"
        )
        log = DataSyncLog.objects.filter(data_source=src).order_by("-started_at").first()
        status_code = freshness.classify_source_status(src.code, active, log, fresh)
        result.append({
            "source": src,
            "display": freshness.source_display(src.code),
            "log": log,
            "total": total,
            "active": active,
            "fresh": fresh,
            "blurb": freshness.source_blurb(src.code),
            "status_code": status_code,
            "status_label": freshness.status_label(status_code),
            "status_tone": freshness.status_tone(status_code),
        })
    return result


@login_required
def station_list(request):
    """Unified station list with monitoring stats, freshness map, and enriched table."""
    now = timezone.now()

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
    # Default to active-only so the table doesn't surface dead/inactive stations.
    # Explicit opt-ins preserve the toggle: "0" = inactive only, "all" = everything.
    if active == "0":
        queryset = queryset.filter(is_active=False)
    elif active != "all":
        queryset = queryset.filter(is_active=True)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Freshness classification for current page stations (source-aware)
    station_freshness = {
        s.pk: freshness.classify_freshness(s.data_source.code, s.last_data_at, now)
        for s in page_obj
    }

    # Sparkline data for current page stations
    page_station_ids = [s.pk for s in page_obj]
    staging_qs = (
        DataRecordStaging.objects
        .filter(station__in=page_station_ids)
        .order_by("station_id", "-observation_date")
        .values("station_id", "value", "unit")
    )
    raw_records: dict = {}
    latest_unit: dict = {}
    latest_value: dict = {}
    for row in staging_qs:
        sid = row["station_id"]
        if sid not in raw_records:
            raw_records[sid] = []
            # First row is the most recent record for this station
            latest_value[sid] = row["value"]
            latest_unit[sid] = row["unit"] or ""
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

    # Enrich page objects with freshness, sparkline, and latest value/unit
    enriched_stations = []
    for s in page_obj:
        lv = latest_value.get(s.pk)
        lu = latest_unit.get(s.pk, "")
        if lv is not None:
            try:
                latest_tooltip = f"Latest: {float(lv):,.2f} {lu}".strip()
            except (ValueError, TypeError):
                latest_tooltip = None
        else:
            latest_tooltip = None
        enriched_stations.append({
            "station": s,
            "freshness": station_freshness.get(s.pk, "dead"),
            "sparkline_points": station_sparklines.get(s.pk),
            "latest_tooltip": latest_tooltip,
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

    # Full page: add summary stats and source status (source-aware freshness)
    all_active = MonitoredStation.objects.filter(is_active=True).select_related("data_source")
    total_active = all_active.count()
    fresh_count = sum(
        1 for s in all_active
        if freshness.classify_freshness(s.data_source.code, s.last_data_at, now) == "fresh"
    )
    stale_count = total_active - fresh_count

    source_status_list = _build_source_status(None, now)

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
        # Python object (not a json.dumps string): the template escapes it via
        # json_script so station_name / external_station_id can't break out of
        # <script>.
        station_geojson = {
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

    # Determine freshness for chart color (source-aware)
    station_freshness = freshness.classify_freshness(
        source_code, station.last_data_at, timezone.now()
    )

    # Build enriched parameter list for the dropdown + PARAMETERS chips. Only
    # parameters this station has ACTUALLY published — not the declared sensor
    # list — so it never offers an empty option for a sensor the site doesn't
    # measure (matches station_chart_data; 59-02).
    measured_codes = sorted(
        DataRecordStaging.objects
        .filter(station=station, status="published")
        .order_by()  # clear Meta.ordering (-observation_date) so DISTINCT keys on code alone
        .values_list("parameter_code", flat=True)
        .distinct()
    )
    enriched_parameters = [
        {"code": code, "label": get_parameter_label(source_code, code)}
        for code in measured_codes
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

    boundary = Boundary.objects.first()

    # Show ALL active monitored stations, not only those inside the GSA polygon.
    # Agencies legitimately track reservoirs and upstream river gauges that sit
    # outside their own boundary (e.g. the dam that feeds them), so geo-filtering
    # the monitoring view just hides relevant stations.
    active_stations = MonitoredStation.objects.filter(
        is_active=True
    ).select_related("data_source").order_by("data_source__code", "station_name")

    fresh_count = sum(
        1 for s in active_stations
        if freshness.classify_freshness(s.data_source.code, s.last_data_at, now) == "fresh"
    )
    total_active = active_stations.count()
    stale_count = total_active - fresh_count

    # Per-source status, source-aware freshness (not boundary-scoped — see above)
    source_status_list = _build_source_status(None, now)

    # Sparkline data: last 10 DataRecordStaging per active station
    station_ids = list(active_stations.values_list("pk", flat=True))
    staging_qs = (
        DataRecordStaging.objects
        .filter(station__in=station_ids)
        .order_by("station_id", "-observation_date")
        .values("station_id", "value", "unit", "observation_date")
    )

    # Group by station, keep latest 10 per station; capture latest value+unit
    raw_records: dict = {}
    latest_unit_dash: dict = {}
    latest_value_dash: dict = {}
    for row in staging_qs:
        sid = row["station_id"]
        if sid not in raw_records:
            raw_records[sid] = []
            latest_value_dash[sid] = row["value"]
            latest_unit_dash[sid] = row["unit"] or ""
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

    # Determine freshness class for each active station (source-aware)
    station_list = []
    for s in active_stations:
        fresh_class = freshness.classify_freshness(s.data_source.code, s.last_data_at, now)
        lv = latest_value_dash.get(s.pk)
        lu = latest_unit_dash.get(s.pk, "")
        if lv is not None:
            try:
                latest_tooltip = f"Latest: {float(lv):,.2f} {lu}".strip()
            except (ValueError, TypeError):
                latest_tooltip = None
        else:
            latest_tooltip = None
        station_list.append({
            "station": s,
            "freshness": fresh_class,
            "sparkline_points": station_sparklines.get(s.pk),
            "latest_tooltip": latest_tooltip,
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
    """
    Return JSON chart data for a station's telemetry.

    Robustness contract that fixes the "graph goes blank on range change" bug:
      * The list of available parameters is STABLE — derived from all published
        records for the station (plus the station's declared parameters), NOT
        from whatever happens to fall inside the selected time window. So the
        dropdown never empties and never desyncs when you switch ranges.
      * A selected parameter that has no data in the chosen window returns empty
        series + the full parameter list, so the page shows a clean "no data for
        this period" message instead of a blank canvas with a broken dropdown.
      * An optional second parameter (``parameter2``) is returned as a separate
        series so two variables (e.g. flow + stage) can be compared.
    """
    station = get_object_or_404(MonitoredStation, pk=pk)
    source_code = station.data_source.code

    parameter = request.GET.get("parameter", "").strip()
    parameter2 = request.GET.get("parameter2", "").strip()
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

    # STABLE parameter universe: every parameter this station has ACTUALLY
    # published. Window-independent on purpose (no date filter here), so the
    # dropdown never empties or desyncs when you change the time range. We do NOT
    # union the station's *declared* parameters — a site configured for a sensor
    # it doesn't actually report (e.g. a reservoir gauge that has Inflow declared
    # but never measures it) should not offer that empty option (59-02).
    published_param_rows = (
        DataRecordStaging.objects
        .filter(station=station, status="published")
        .order_by()  # clear Meta.ordering (-observation_date) so DISTINCT keys on code+unit alone
        .values("parameter_code", "unit")
        .distinct()
    )
    units_by_code = {r["parameter_code"]: r["unit"] for r in published_param_rows}
    param_codes = sorted(units_by_code.keys())

    # Resolve the selected parameter(s) against the stable universe.
    if not parameter or parameter not in param_codes:
        parameter = param_codes[0] if param_codes else None
    if parameter2 and (parameter2 not in param_codes or parameter2 == parameter):
        parameter2 = ""

    parameters_meta = []
    for code in param_codes:
        unit = units_by_code.get(code, "")
        label = get_parameter_label(source_code, code)
        if unit and label.endswith(f" ({unit})"):
            name = label[: -(len(unit) + 3)]
        else:
            name = label
        parameters_meta.append({"code": code, "name": name, "unit": unit, "label": label})

    def series_for(param):
        """Return {date: value} for one parameter inside the window."""
        rows = (
            DataRecordStaging.objects
            .filter(station=station, status="published", parameter_code=param, **date_filter)
            .order_by("observation_date")
            .values("observation_date", "value")
        )
        out = {}
        for r in rows:
            key = r["observation_date"].strftime("%Y-%m-%d")
            out[key] = float(r["value"]) if r["value"] is not None else None
        return out

    datasets = []
    labels = []
    if parameter:
        primary = series_for(parameter)
        secondary = series_for(parameter2) if parameter2 else {}
        # Shared, sorted date axis across both series.
        labels = sorted(set(primary) | set(secondary))
        datasets.append({
            "label": get_parameter_label(source_code, parameter),
            "data": [primary.get(d) for d in labels],
            "parameter_code": parameter,
            "unit": units_by_code.get(parameter, ""),
            "axis": "y",
        })
        if parameter2:
            datasets.append({
                "label": get_parameter_label(source_code, parameter2),
                "data": [secondary.get(d) for d in labels],
                "parameter_code": parameter2,
                "unit": units_by_code.get(parameter2, ""),
                "axis": "y1",
            })

    result = {
        "labels": labels,
        "datasets": datasets,
        "parameters": parameters_meta,
        "selected_parameter": parameter,
        "selected_parameter2": parameter2 or None,
        "days": days,
    }
    return JsonResponse(result)


@login_required
def stations_freshness_geojson(request):
    """Return active stations as GeoJSON with freshness metadata."""
    now = timezone.now()

    stations = MonitoredStation.objects.filter(
        is_active=True, location__isnull=False
    ).select_related("data_source")

    # Latest published reading (value/unit/parameter) per station, so the map
    # popup shows the actual measurement — not just a freshness colour. Ordered
    # newest-first; the first row seen per station is its latest.
    latest_reading: dict = {}
    reading_rows = (
        DataRecordStaging.objects
        .filter(station__in=stations, status="published")
        .order_by("station_id", "-observation_date")
        .values("station_id", "value", "unit", "parameter_code")
    )
    for row in reading_rows:
        if row["station_id"] not in latest_reading:
            latest_reading[row["station_id"]] = row

    features = []
    for s in stations:
        fresh_class = freshness.classify_freshness(s.data_source.code, s.last_data_at, now)
        hours_since = (
            (now - s.last_data_at).total_seconds() / 3600
            if s.last_data_at else None
        )

        reading = latest_reading.get(s.pk)
        latest_value = None
        latest_unit = ""
        latest_param = ""
        if reading and reading["value"] is not None:
            try:
                latest_value = round(float(reading["value"]), 2)
            except (ValueError, TypeError):
                latest_value = None
            latest_unit = reading["unit"] or ""
            latest_param = get_parameter_label(
                s.data_source.code, reading["parameter_code"]
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
                "freshness": fresh_class,
                "hours_since_data": round(hours_since, 1) if hours_since is not None else None,
                "last_data_at": s.last_data_at.isoformat() if s.last_data_at else None,
                "latest_value": latest_value,
                "latest_unit": latest_unit,
                "latest_parameter": latest_param,
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
