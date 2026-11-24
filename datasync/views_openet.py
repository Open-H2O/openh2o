# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Map page's crop ET layer and an OpenET field's own page."""
from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date

from django.core.cache import cache
from django.db.models import Count, Max
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render

from core.access import public_in_open_demo
from datasync import whole_area
from datasync.models import OpenETField, OpenETFieldMonth, OpenETFieldShare


def _month(text):
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1)
    except (AttributeError, ValueError):
        return None


@public_in_open_demo
def openet_area_outlines(request):
    """Every OpenET field inside the site's boundary, as simplified GeoJSON outlines."""
    agg = OpenETField.objects.aggregate(c=Count("pk"), m=Max("pk"))
    key = f"geojson:openet-area:{agg['c']}:{agg['m']}"
    body = cache.get(key)
    if body is None:
        body = json.dumps(whole_area.outlines(), separators=(",", ":"))
        cache.set(key, body, 3600)
    response = HttpResponse(body, content_type="application/json")
    response["Cache-Control"] = "public, max-age=3600"
    return response


@public_in_open_demo
def openet_area_depths(request):
    """Crop ET depth in inches for each field inside the boundary: ``?month=YYYY-MM`` for one
    month, or ``?from=YYYY-MM&to=YYYY-MM`` summed over the months between (a water year to date)."""
    if "month" in request.GET:
        month = _month(request.GET["month"])
        if month is None:
            return HttpResponseBadRequest("month is YYYY-MM")
        depths = whole_area.depths_for_month(month)
    else:
        start, end = _month(request.GET.get("from")), _month(request.GET.get("to"))
        if start is None or end is None or end < start:
            return HttpResponseBadRequest("from and to are YYYY-MM")
        depths = whole_area.depths_for_span(start, end)
    return JsonResponse({"fields": {str(k): float(v) for k, v in depths.items()}})


@public_in_open_demo
def openet_field_detail(request, field_id):
    """One OpenET field: its number, acres, the use areas it overlaps and its months."""
    field = get_object_or_404(OpenETField, field_id=field_id)
    if field.geometry is None:
        raise Http404
    shares = (
        OpenETFieldShare.objects.filter(field=field).select_related("parcel")
        .order_by("parcel__parcel_number")
    )
    months = list(OpenETFieldMonth.objects.filter(field=field).order_by("-month"))
    years = OrderedDict()
    named = whole_area.water_years()
    for row in months:
        name = next((n for n, start, end, _last in named if start <= row.month <= end), None)
        year = years.setdefault(name or row.month.strftime("%Y"), {"rows": [], "et_mm": 0, "pr_mm": 0})
        et = whole_area.inches(row.et_mm) if row.et_mm is not None else None
        pr = whole_area.inches(row.pr_mm) if row.pr_mm is not None else None
        year["rows"].append({"month": row.month, "et": et, "pr": pr})
        year["et_mm"] += row.et_mm or 0
        year["pr_mm"] += row.pr_mm or 0
    # A year's total is its millimetres summed, then turned to inches, as the map's water
    # year to date is, so the two never differ by a rounding.
    for year in years.values():
        year["et"] = whole_area.inches(year["et_mm"])
        year["months_with_figures"] = sum(1 for r in year["rows"] if r["et"] is not None)
        year["pr"] = whole_area.inches(year["pr_mm"])
    geometry = json.loads(field.geometry.geojson)
    return render(request, "datasync/openet_field_detail.html", {
        "field": field,
        "shares": shares,
        "years": years,
        "outline": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": geometry}]},
    })
