# SPDX-License-Identifier: AGPL-3.0-or-later
"""The crop ET layer for the whole area: every OpenET field inside the site's boundary.

What a correct site does:

* The Map page's layer covers every stored OpenET field whose outline lies inside the site's
  boundary, whether or not it overlaps a use area, and leaves out a field outside it.
* A field's depth is OpenET's crop ET in millimetres / 25.4, to two decimals, for one month, or
  its millimetres summed over a span of months (a water year to date) and then turned to inches.
  A field with no figure for the month carries none.
* An OpenET field's page shows its number, acres, the use areas it overlaps and its months.
* ``sync_openet_parcels --whole-area --dry-run`` prints the lookups over rectangles covering the
  boundary (each within the account's area limit) and the figures requests for every field inside
  the boundary, and sends nothing. Without ``--whole-area`` nothing changes.
* The monthly scheduled job does not pass ``--whole-area``.

**Every field number, outline and figure in this file is made up.** Field numbers start at
99100000001 (OpenET's own are 11-digit numbers starting 211 in Merced); depths are round numbers
chosen for the arithmetic. None of them is OpenET's.
"""

import datetime as dt
import io
import math
import re
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from parcels.models import Parcel

pytestmark = pytest.mark.django_db

INSIDE_WITH_USE_AREA = 99100000001
INSIDE_NO_USE_AREA = 99100000002
OUTSIDE = 99100000003

JUNE_1 = dt.date(2025, 6, 1)
JULY_1 = dt.date(2025, 7, 1)
RECEIVED = dt.date(2025, 8, 6)


def _square(west, south, size):
    return MultiPolygon(Polygon((
        (west, south), (west + size, south), (west + size, south + size), (west, south + size), (west, south),
    )), srid=4326)


def _boundary(west=-120.40, south=37.20, width=0.20, height=0.20):
    from geography.models import Boundary

    return Boundary.objects.create(
        name="Made-up basin",
        geometry=MultiPolygon(Polygon((
            (west, south), (west + width, south), (west + width, south + height),
            (west, south + height), (west, south),
        )), srid=4326),
    )


def _field(number, geometry, acres="40.00"):
    from datasync.models import OpenETField

    return OpenETField.objects.create(
        field_id=number, geometry=geometry, area_acres=D(acres), received_on=RECEIVED
    )


def _month(field, month, et_mm, pr_mm="0"):
    from datasync.models import OpenETFieldMonth

    return OpenETFieldMonth.objects.create(
        field=field, month=month, et_mm=D(et_mm), pr_mm=D(pr_mm), received_on=RECEIVED
    )


@pytest.fixture
def area():
    """A made-up boundary holding two fields (one under a use area, one in none) and a third
    field outside it, with July figures for all three and June for the first."""
    from datasync.models import OpenETFieldShare

    _boundary()
    a = _field(INSIDE_WITH_USE_AREA, _square(-120.30, 37.30, 0.004))
    b = _field(INSIDE_NO_USE_AREA, _square(-120.25, 37.30, 0.004))
    c = _field(OUTSIDE, _square(-119.90, 37.30, 0.004))
    parcel = Parcel.objects.create(
        parcel_number="MADEUP-WHOLE-AREA-1", geometry=_square(-120.30, 37.30, 0.004), area_acres=D("40.00")
    )
    OpenETFieldShare.objects.create(parcel=parcel, field=a, overlap_acres=D("40.00"))
    _month(a, JULY_1, "101.6")   # 4.00 in
    _month(a, JUNE_1, "50.8")    # 2.00 in
    _month(b, JULY_1, "127")     # 5.00 in
    _month(c, JULY_1, "254")     # outside the boundary
    return {"a": a, "b": b, "c": c, "parcel": parcel}


@pytest.fixture
def signed_in(client, django_user_model):
    user = django_user_model.objects.create_user(username="made-up-reader", password="made-up-pass-1")
    client.force_login(user)
    return client


# ---------------------------------------------------------------- 1. the layer


def test_the_outlines_cover_every_field_inside_the_boundary_and_no_other(area, signed_in):
    from django.urls import reverse

    body = signed_in.get(reverse("datasync:openet_area_outlines")).json()
    numbers = {feature["id"] for feature in body["features"]}
    assert numbers == {INSIDE_WITH_USE_AREA, INSIDE_NO_USE_AREA}


def test_a_months_depth_is_its_millimetres_over_25_4_and_a_field_with_none_carries_none(area, signed_in):
    from django.urls import reverse

    url = reverse("datasync:openet_area_depths")
    july = signed_in.get(url, {"month": "2025-07"}).json()["fields"]
    assert july == {str(INSIDE_WITH_USE_AREA): 4.0, str(INSIDE_NO_USE_AREA): 5.0}
    june = signed_in.get(url, {"month": "2025-06"}).json()["fields"]
    assert june == {str(INSIDE_WITH_USE_AREA): 2.0}


def test_a_water_year_to_date_sums_the_millimetres_before_turning_them_to_inches(area, signed_in):
    from django.urls import reverse

    from datasync.models import OpenETFieldMonth

    # Two months that are each 1.004 in, so inches rounded month by month would add to 2.00
    # while the summed millimetres give 2.01.
    field = area["b"]
    OpenETFieldMonth.objects.filter(field=field).delete()
    _month(field, JUNE_1, "25.5")
    _month(field, JULY_1, "25.5")
    body = signed_in.get(
        reverse("datasync:openet_area_depths"), {"from": "2024-10", "to": "2025-09"}
    ).json()["fields"]
    assert body[str(INSIDE_NO_USE_AREA)] == 2.01
    assert body[str(INSIDE_WITH_USE_AREA)] == 6.0
    assert str(OUTSIDE) not in body


def test_the_map_page_offers_the_layer_with_each_month_that_has_figures(area, signed_in):
    from django.urls import reverse

    response = signed_in.get(reverse("geography:map"))
    queries = [choice["query"] for choice in response.context["crop_et_choices"]]
    assert "month=2025-07" in queries and "month=2025-06" in queries
    assert response.context["crop_et_count"] == 2


def test_each_choice_names_its_kind_so_the_layer_uses_that_kinds_fixed_breaks(area, signed_in):
    from django.urls import reverse

    choices = signed_in.get(reverse("geography:map")).context["crop_et_choices"]
    assert choices
    assert all(c["kind"] == {"Months": "month", "Water years": "wy"}[c["group"]] for c in choices)


def test_the_layer_shades_on_the_shared_ramp_and_fixed_breaks_never_its_own():
    core = (Path(__file__).resolve().parent.parent / "static/js/map-core.js").read_text()
    layer = core[core.index("OH2O.mountCropETLayer = function"):]
    # One crop ET object: the map's symbols set its ramp, breaks and no-figure grey once.
    assert core.count("OH2O.cropET = {") == 1
    assert "C.BREAKS[choice.kind]" in layer
    assert "breaks: function" not in core and "C.breaks(" not in layer
    assert "OH2O.cropET.NO_FIGURE" in core[core.index("Object.assign(OH2O.cropET"):]
    assert not re.search(r"#[0-9a-fA-F]{6}\b", layer)


def test_the_layer_sits_in_its_own_section_and_starts_off(area, signed_in):
    from django.urls import reverse

    html = signed_in.get(reverse("geography:map")).content.decode()
    fill = re.search(r"\{\s*id: 'openet-area-fill'.*?\}", html, re.S).group(0)
    assert "visible: false" in fill and "section: 'Crop ET'" in fill


# ---------------------------------------------------------------- 2. the field page


def test_a_fields_page_shows_its_number_acres_use_areas_and_months(area, signed_in):
    from django.urls import reverse

    response = signed_in.get(reverse("datasync:openet_field_detail", args=[INSIDE_WITH_USE_AREA]))
    assert response.status_code == 200
    assert response.context["field"].field_id == INSIDE_WITH_USE_AREA
    assert [s.parcel.parcel_number for s in response.context["shares"]] == ["MADEUP-WHOLE-AREA-1"]
    rows = [row for year in response.context["years"].values() for row in year["rows"]]
    assert [(r["month"], r["et"]) for r in rows] == [(JULY_1, D("4.00")), (JUNE_1, D("2.00"))]
    body = response.content.decode()
    assert str(INSIDE_WITH_USE_AREA) in body and "40.00" in body and "MADEUP-WHOLE-AREA-1" in body


def test_a_field_in_no_use_area_has_a_page_with_no_use_area(area, signed_in):
    from django.urls import reverse

    response = signed_in.get(reverse("datasync:openet_field_detail", args=[INSIDE_NO_USE_AREA]))
    assert response.status_code == 200
    assert list(response.context["shares"]) == []


# ---------------------------------------------------------------- 3. the whole-area option


def _refuse(*args, **kwargs):
    raise AssertionError("a dry run sent a request to OpenET")


def test_a_whole_area_dry_run_prints_lookups_over_the_boundary_and_sends_nothing(area, settings):
    from datasync import field_list
    from datasync.models import OpenETRequest

    settings.OPENET_MODE = "fields"
    settings.OPENET_API_KEY = "made-up-key"
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=_refuse):
        call_command("sync_openet_parcels", "--whole-area", "--dry-run",
                     start_date="2025-06-01", end_date="2025-07-31", stdout=out)
    text = out.getvalue()
    rectangles = field_list.boundary_areas(max_acres=field_list.DEFAULT_MAX_AREA_ACRES)
    # The made-up boundary is about 108,000 acres, so it takes three rectangles at 50,000.
    assert len(rectangles) == math.ceil(
        field_list._acres((-120.40, 37.20, -120.20, 37.40)) / field_list.DEFAULT_MAX_AREA_ACRES
    )
    for west, south, east, north in rectangles:
        assert f"{west}, {south}, {east}, {north}" in text
    # Figures for both fields inside the boundary, the one in no use area too (it lacks June).
    figures = re.search(r"(\d+) request\(s\) for the figures of (\d+) fields", text)
    assert figures and figures.group(2) == "2"
    assert OpenETRequest.objects.count() == 0


def test_a_whole_area_run_does_not_ask_again_for_a_field_outside_use_areas_that_holds_every_month(area, settings):
    """The field in no use area already holds July, so a July run asks figures only for the field
    under a use area; a run the allowance stopped continues with the fields still missing."""
    settings.OPENET_MODE = "fields"
    settings.OPENET_API_KEY = "made-up-key"
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=_refuse):
        call_command("sync_openet_parcels", "--whole-area", "--dry-run",
                     start_date="2025-07-01", end_date="2025-07-31", stdout=out)
    figures = re.search(r"(\d+) request\(s\) for the figures of (\d+) fields", out.getvalue())
    assert figures and figures.group(2) == "1"


def test_without_whole_area_the_dry_run_asks_only_for_fields_with_a_use_area(area, settings):
    settings.OPENET_MODE = "fields"
    settings.OPENET_API_KEY = "made-up-key"
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=_refuse):
        call_command("sync_openet_parcels", "--dry-run",
                     start_date="2025-07-01", end_date="2025-07-31", stdout=out)
    figures = re.search(r"(\d+) request\(s\) for the figures of (\d+) fields", out.getvalue())
    assert figures and figures.group(2) == "1"


def test_the_monthly_scheduled_job_does_not_ask_for_the_whole_area():
    crontab = Path(__file__).resolve().parent.parent / "crontab.txt"
    lines = [line for line in crontab.read_text().splitlines()
             if "sync_openet_parcels" in line and not line.lstrip().startswith("#")]
    assert lines
    assert all("--whole-area" not in line for line in lines)
