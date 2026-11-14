# SPDX-License-Identifier: AGPL-3.0-or-later
"""A use area's page says how much of it lies in OpenET's fields, and draws them on request.

* Under Crop ET's acres, a second note gives the acres in OpenET fields with an explainer,
  only when the use area has OpenET field overlaps.
* With no calculation in the year, the card adds "No OpenET field is on record for this use
  area." only when the use area has no overlap; otherwise its wording is unchanged.
* The page carries the outlines of the OpenET fields in the map's frame only when some reach
  into it; the map's checkbox starts unticked on every load (ruling 166).

**Every OpenET field number and figure in this file is made up**; the use areas are the
made-up fields of ``tests/ledger_districts``.
"""

import html
import re
from pathlib import Path

import pytest
from django.urls import reverse

from tests import ledger_districts as ld
from tests.test_openet_field_parts_page import MADE_UP_EAST, MADE_UP_WEST, _fields_over
from tests.test_openet_recorded_figure import (  # noqa: F401  (fixtures)
    JULY,
    _client,
    _corn_field,
    operator,
)

pytestmark = pytest.mark.django_db

NO_RUN = "OpenH2O has not calculated crop ET for this use area in this water year."
NO_FIELD = "No OpenET field is on record for this use area."
POPOUT = (
    "OpenET sends crop ET and gridMET rainfall for each OpenET field. OpenH2O counts both on "
    "the acres of each OpenET field that lie inside this use area. OpenH2O does not count crop "
    "ET or rainfall on acres outside the OpenET fields."
)


def _page(user, parcel):
    response = _client(user).get(reverse("parcels:detail", args=[parcel.pk]))
    assert response.status_code == 200
    return " ".join(html.unescape(response.content.decode()).replace("\xa0", " ").split())


def _shares_acres(parcel):
    from datasync.models import OpenETFieldShare

    return sum(s.overlap_acres for s in OpenETFieldShare.objects.filter(parcel=parcel))


def test_the_crop_et_lead_carries_the_acres_in_openet_fields_and_its_explainer(operator):
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])

    page = _page(operator, field)
    acres = f"{_shares_acres(field):,.2f}"
    assert re.search(
        rf'<p class="statement-lead-note">{re.escape(acres)} acres in OpenET fields\s?<span class="explainer-popout">',
        page,
    )
    assert "Explain: OpenET fields" in page
    assert POPOUT in page
    assert "Methods behind the numbers" in page


def test_no_note_on_a_use_area_with_no_openet_field(operator):
    field = _corn_field()
    page = _page(operator, field)
    assert "acres in OpenET fields" not in page


def test_no_run_and_no_openet_field_says_so(operator):
    field = _corn_field()
    page = _page(operator, field)
    assert f"{NO_RUN} {NO_FIELD} Recorded supplies:" in page


def test_no_run_with_openet_fields_keeps_todays_wording(operator):
    from datasync.models import CropETFigure

    field = _corn_field()
    _fields_over(field)
    CropETFigure.objects.filter(parcel=field).delete()
    page = _page(operator, field)
    assert f"{NO_RUN} Recorded supplies:" in page
    assert NO_FIELD not in page


def test_the_page_carries_the_outlines_in_frame(operator):
    field = _corn_field()
    _fields_over(field)
    page = _page(operator, field)
    data = re.search(r'<script id="openet-fields-data" type="application/json">(.*?)</script>', page).group(1)
    assert str(MADE_UP_WEST) in data and str(MADE_UP_EAST) in data


def test_no_outlines_when_none_reaches_the_frame(operator):
    from django.contrib.gis.geos import MultiPolygon, Polygon

    from datasync.models import OpenETField
    import datetime as dt

    field = _corn_field()
    OpenETField.objects.create(
        field_id=99000000199,
        geometry=MultiPolygon(Polygon.from_bbox((-119.0, 36.0, -118.99, 36.01)), srid=4326),
        received_on=dt.date(2025, 8, 6),
    )
    page = _page(operator, field)
    assert 'id="openet-fields-data"' not in page


def test_the_map_checkbox_starts_unticked_and_remembers_nothing():
    """The toggle is built by map-core.js: unticked on every call, no stored state."""
    source = Path("static/js/map-core.js").read_text()
    start = source.index("OH2O.mountOpenETFieldsToggle = function")
    body = source[start: source.index("\n};", start)]
    assert "box.checked = false;" in body
    assert "state.set(false);" in body
    for memory in ("localStorage", "sessionStorage", "cookie"):
        assert memory not in body
    assert "'OpenET fields'" in body
    assert "'OpenET field outlines'" in body
