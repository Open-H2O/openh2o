# SPDX-License-Identifier: AGPL-3.0-or-later
"""The month page lists the OpenET fields its crop ET came from (153.2-02).

* The list is the Crop ET figure's parts, inside its cell: each OpenET field's number, its
  acres inside the use area and its crop ET in acre-feet, then the acres outside every OpenET
  field. The crop ET column adds to the figure above it exactly.
* On the receipt each field's rainfall is listed under the Rainfall row and adds to it.
* The page reads only what the run stamped: a run with no stamp lists nothing.

**Every OpenET field number and figure in this file is made up** (field numbers from
99000000101; OpenET's own are 11-digit numbers starting 211 in Merced). The use areas are the
made-up 100-acre fields of ``tests/ledger_districts``.
"""

import datetime as dt
import re
from decimal import Decimal as D

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from accounting.models import CalculationRun
from tests import ledger_districts as ld
from tests.test_openet_recorded_figure import (  # noqa: F401  (fixtures)
    JULY,
    _client,
    _corn_field,
    operator,
)

pytestmark = pytest.mark.django_db

MADE_UP_WEST = 99000000101
MADE_UP_EAST = 99000000102
RECEIVED = dt.date(2025, 8, 6)


def _strip(parcel, x0, x1):
    """A made-up OpenET field: the strip of the use area's box from fraction x0 to x1 of its width,
    reaching past it north and south."""
    minx, miny, maxx, maxy = parcel.geometry.extent
    w = maxx - minx
    poly = Polygon.from_bbox((minx + x0 * w, miny - 0.01, minx + x1 * w, maxy + 0.01))
    return poly


def _fields_over(parcel, et=(500, 400), pr=(40, 20)):
    """Two made-up OpenET fields over 60% and 30% of the use area; 10% in neither."""
    from datasync import crop_et
    from datasync.field_list import compute_shares
    from datasync.models import OpenETField, OpenETFieldMonth

    for number, (x0, x1), et_mm, pr_mm in (
        (MADE_UP_WEST, (0.0, 0.6), et[0], pr[0]),
        (MADE_UP_EAST, (0.6, 0.9), et[1], pr[1]),
    ):
        field = OpenETField.objects.create(
            field_id=number, geometry=MultiPolygon(_strip(parcel, x0, x1), srid=4326), received_on=RECEIVED
        )
        OpenETFieldMonth.objects.create(
            field=field, month=dt.date(2025, 7, 1), et_mm=D(et_mm), pr_mm=D(pr_mm), received_on=RECEIVED
        )
    compute_shares(parcel)
    crop_et.record_fetched_months(parcel, [JULY])


def _page(user, parcel):
    from django.urls import reverse

    response = _client(user).get(reverse("accounting:calculation_run_detail", args=[parcel.pk, JULY]))
    assert response.status_code == 200
    return response.content.decode()


def _list(page):
    """The fields list's rows as text cells, header first."""
    start = page.index("budget-breakdown-group--fields")
    rows = re.findall(r'<div class="budget-breakdown-row[^"]*">(.*?)</div>', page[start:])
    out = []
    for row in rows:
        cells = re.findall(r"<(?:span|b)[^>]*>(.*?)</(?:span|b)>", row)
        out.append(cells)
        if cells and cells[0] == "Outside the OpenET fields":
            break
    return out


def _figure(page):
    return re.search(r'id="crop-et">\s*<div class="crop-et-figure">\s*<div class="budget-seg-label">Crop ET</div>\s*'
                     r'<div class="budget-seg-value"[^>]*>([\d,.]+)<', page).group(1)


def test_the_receipt_lists_each_field_inside_the_crop_et_cell(operator):
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])

    page = _page(operator, field)
    rows = _list(page)
    assert rows[0] == ["OpenET field", "Acres", "AF"]
    names = [r[0] for r in rows[1:]]
    assert names[:2] == [str(MADE_UP_WEST), str(MADE_UP_EAST)]
    assert names[-1] == "Outside the OpenET fields"
    crop = [D(r[2]) for r in rows[1:-1]]
    assert sum(crop) == D(_figure(page).replace(",", ""))
    # The outside row has acres and an empty AF cell.
    assert rows[-1][2] == ""
    # The acres column adds to the use area's outline (measured the way the overlaps are).
    from datasync.field_list import outline_acres

    acres = [D(r[1].replace(",", "")) for r in rows[1:]]
    assert sum(acres) == outline_acres(field.geometry)
    # The list sits inside the Crop ET cell, before the next cell.
    cell = page[page.index('id="crop-et"'):page.index("Effective precipitation")]
    assert "budget-breakdown-group--fields" in cell


def test_each_fields_rainfall_is_listed_under_rainfall_and_adds_to_it(operator):
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])

    page = _page(operator, field)
    rainfall = re.search(r"<span>Rainfall</span><b[^>]*>([\d,.]+)</b>", page).group(1)
    listed = re.findall(
        r'<div class="budget-breakdown-row budget-breakdown-row--listed"><span>(\d+)</span><span>([\d,.]+)</span></div>', page
    )
    assert [n for n, _ in listed] == [str(MADE_UP_WEST), str(MADE_UP_EAST)]
    assert sum(D(v) for _, v in listed) == D(rainfall)


def test_the_short_page_lists_the_fields_beside_the_figure_without_rainfall(operator):
    field = _corn_field(number="F9", well=False)
    _fields_over(field)
    ld.run_months([JULY])
    run = CalculationRun.objects.get(parcel=field, period=JULY)
    assert run.residual_disposition != "groundwater"

    page = _page(operator, field)
    assert "budget-seg budget-seg--fields" in page
    rows = _list(page)
    assert rows[0] == ["OpenET field", "Acres", "AF"]
    assert sum(D(r[2]) for r in rows[1:-1]) == D(_figure(page).replace(",", ""))
    assert "budget-breakdown-row--listed" not in page


def test_a_run_with_no_stamp_lists_no_fields(operator):
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])
    run = CalculationRun.objects.get(parcel=field, period=JULY)
    breakdown = run.breakdown
    for step in breakdown:
        if step.get("step_type") == "et_gross":
            step["detail"].pop("fields", None)
            step["detail"].pop("outside_acres", None)
    CalculationRun.objects.filter(pk=run.pk).update(breakdown=breakdown)

    page = _page(operator, field)
    assert "budget-breakdown-group--fields" not in page
    assert "budget-breakdown-row--listed" not in page


def test_the_page_reads_the_stamp_not_the_fields_figures_now(operator):
    """OpenET revising a field later does not change what the month's page says it was made of."""
    from datasync.models import OpenETFieldMonth

    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])
    before = _list(_page(operator, field))
    OpenETFieldMonth.objects.filter(field__field_id=MADE_UP_WEST).update(et_mm=D("900"))
    assert _list(_page(operator, field)) == before
