# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's fields across the whole area: the outlines and crop ET depths the Map page shades.

Every stored OpenET field whose outline lies inside the site's boundary, whether or not it
overlaps a use area. Depth is crop ET in inches (OpenET's millimetres / 25.4, to 0.01) for one
month, or summed over a water year's months that have figures. A field with no figure for the
month carries none, so the map leaves it unshaded.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.gis.db.models import GeometryField
from django.db.models import Func, Sum

from datasync.models import OpenETField, OpenETFieldMonth

MM_PER_INCH = Decimal("25.4")
CENT = Decimal("0.01")
# About 2 m at these latitudes, in degrees, so it holds for a site anywhere. Measured on
# 8,905 outlines: 917 kB gzip, first draw under 0.8 s at 1,730 px on a local network.
SIMPLIFY_DEGREES = 0.00002
DECIMALS = 5


class _Simplify(Func):
    function = "ST_SimplifyPreserveTopology"
    output_field = GeometryField(srid=4326)


def _boundary_union():
    from geography.models import Boundary

    union = None
    for geometry in Boundary.objects.filter(geometry__isnull=False).values_list("geometry", flat=True):
        union = geometry if union is None else union.union(geometry)
    return union


def fields_in_area():
    """Stored OpenET fields with an outline inside the site's boundary (every field when the
    site has no boundary)."""
    qs = OpenETField.objects.filter(geometry__isnull=False)
    union = _boundary_union()
    if union is not None:
        qs = qs.filter(geometry__intersects=union)
    return qs


def outlines():
    """A GeoJSON FeatureCollection of the fields' outlines, simplified and rounded; each feature's
    id is its OpenET field number, its properties the number and acres."""
    import json

    rows = (
        fields_in_area()
        .annotate(gj=AsGeoJSON(_Simplify("geometry", SIMPLIFY_DEGREES), precision=DECIMALS))
        .values_list("field_id", "area_acres", "gj")
        .order_by("field_id")
    )
    features = [
        {
            "type": "Feature",
            "id": number,
            "properties": {"f": str(number), "a": float(acres) if acres is not None else None},
            "geometry": json.loads(gj),
        }
        for number, acres, gj in rows
    ]
    return {"type": "FeatureCollection", "features": features}


def inches(mm):
    return (Decimal(mm) / MM_PER_INCH).quantize(CENT, rounding=ROUND_HALF_UP)


def water_years():
    """The site's water years that hold any field month, newest first, each as
    ``(name, start, end, last month with figures)``."""
    try:
        from accounting.models import ReportingPeriod
    except ImportError:  # pragma: no cover - accounting is optional
        return []
    months = OpenETFieldMonth.objects.filter(et_mm__isnull=False)
    out = []
    for period in ReportingPeriod.objects.order_by("-start_date"):
        last = (
            months.filter(month__gte=period.start_date, month__lte=period.end_date)
            .order_by("-month").values_list("month", flat=True).first()
        )
        if last is not None:
            out.append((period.name, period.start_date, period.end_date, last))
    return out


def months_with_figures():
    """Every month any field has a crop ET figure for, newest first."""
    return list(
        OpenETFieldMonth.objects.filter(et_mm__isnull=False)
        .order_by("-month").values_list("month", flat=True).distinct()
    )


def depths_for_month(month: date) -> dict[int, Decimal]:
    rows = OpenETFieldMonth.objects.filter(
        field__in=fields_in_area(), month=month, et_mm__isnull=False
    ).values_list("field__field_id", "et_mm")
    return {number: inches(mm) for number, mm in rows}


def depths_for_span(start: date, end: date) -> dict[int, Decimal]:
    rows = (
        OpenETFieldMonth.objects.filter(
            field__in=fields_in_area(), month__gte=start, month__lte=end, et_mm__isnull=False
        )
        .values("field__field_id").annotate(total=Sum("et_mm"))
        .values_list("field__field_id", "total")
    )
    return {number: inches(total) for number, total in rows}
