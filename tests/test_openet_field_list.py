# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crop ET and rain from OpenET's field list (rulings 159, 160, 163 step 1, 164).

What a correct site does:

* OpenET's fields are kept as their own records. A use area keeps its own outline and takes
  the acres of each OpenET field that lie inside it (its shares), measured in California
  Albers (EPSG 3310) after any crossed edge is repaired. Land in no OpenET field counts no
  crop use and no rain.
* A use area's crop ET for a month is each field's depth over that field's acres inside the
  use area, added up, and written as one depth over the use area's own acres.
* Rain is figured field by field: each field's effective rain from its own rain and crop ET,
  over its own acres.
* A month OpenET later sends at a different depth is shown as a newer figure; the recorded
  figure does not move on its own.
* The site asks OpenET in three kinds of request (a lookup of field numbers in a rectangle,
  the fields' outlines, and the fields' monthly crop ET and rain), sends field numbers as
  integers, sends no more numbers in a request than the account allows, and stops when a
  request is refused.
* A setup stopped by the monthly allowance picks up where it stopped.
* A run asks for the figures of the fields its use areas already share before anything else. A
  run without ``--whole-area`` never asks for the outline of a field only a whole-area lookup
  listed, and its dry run counts the requests the run sends.

**Every field number, outline and figure in this file is made up.** Field numbers start at
99000000001 (OpenET's own are 11-digit numbers starting 211 in Merced); outlines are plain
rectangles drawn in a made-up test area near the origin of California Albers; depths are
round numbers chosen for the arithmetic. None of them is OpenET's or gridMET's.
"""

import csv
import datetime as dt
import gzip
import io
import json
import math
import re
from decimal import Decimal as D
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import CommandError, call_command

from parcels.models import Parcel

pytestmark = pytest.mark.django_db

#: Made-up OpenET field numbers (never real ones).
MADE_UP_A = 99000000001
MADE_UP_B = 99000000002
MADE_UP_C = 99000000003
MADE_UP_SLIVER = 99000000004

JULY = "2025-07"
JULY_1 = dt.date(2025, 7, 1)
#: The made-up day the made-up figures were received.
RECEIVED = dt.date(2025, 8, 6)
LATER = dt.date(2025, 12, 10)

ACRE_M2 = 4046.8564224
#: The side of a 100-acre square, in metres.
SIDE = math.sqrt(100 * ACRE_M2)


# ---------------------------------------------------------------- made-up outlines


def _albers_rect(x0, y0, x1, y1):
    """A rectangle drawn in metres in California Albers, returned in longitude and latitude.

    The made-up test area sits near the projection's origin (x 0, y 0).
    """
    poly = Polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)), srid=3310)
    poly.transform(4326)
    return MultiPolygon(poly, srid=4326)


def _albers_ring(points):
    ring = list(points) + [points[0]]
    poly = Polygon(ring, srid=3310)
    poly.transform(4326)
    return MultiPolygon(poly, srid=4326)


def _use_area(number="MADEUP-USE-AREA-1", geometry=None, acres="100.00"):
    """A made-up 100-acre square use area at x 0..SIDE, y 0..SIDE."""
    return Parcel.objects.create(
        parcel_number=number,
        geometry=geometry or _albers_rect(0, 0, SIDE, SIDE),
        area_acres=D(acres),
    )


def _field(field_id, geometry, received_on=RECEIVED):
    from datasync.models import OpenETField

    return OpenETField.objects.create(field_id=field_id, geometry=geometry, received_on=received_on)


def _sixty_thirty():
    """Made-up fields A and B: A holds 60 acres of the use area, B 30; 10 acres lie in no field.

    Both fields reach beyond the use area, so a field's own size is not its share.
    """
    a = _field(MADE_UP_A, _albers_rect(-200, -200, 0.6 * SIDE, SIDE + 200))
    b = _field(MADE_UP_B, _albers_rect(0.6 * SIDE, -200, 0.9 * SIDE, SIDE + 200))
    return a, b


def _shares(parcel):
    from datasync.models import OpenETFieldShare

    return {
        share.field.field_id: share.overlap_acres
        for share in OpenETFieldShare.objects.filter(parcel=parcel).select_related("field")
    }


def _month(field, et_mm, pr_mm, month=JULY_1, received_on=RECEIVED):
    from datasync.models import OpenETFieldMonth

    row, _ = OpenETFieldMonth.objects.update_or_create(
        field=field,
        month=month,
        defaults={"et_mm": D(str(et_mm)), "pr_mm": D(str(pr_mm)), "received_on": received_on},
    )
    return row


# ---------------------------------------------------------------- 1. shares


def test_a_use_area_takes_the_acres_of_each_field_inside_it():
    from datasync.field_list import compute_shares

    parcel = _use_area()
    _sixty_thirty()
    compute_shares(parcel)
    assert _shares(parcel) == {MADE_UP_A: D("60.00"), MADE_UP_B: D("30.00")}


def test_an_overlap_that_rounds_to_nothing_makes_no_share():
    from datasync.field_list import compute_shares

    parcel = _use_area()
    _sixty_thirty()
    # A made-up field that touches the use area along a strip 1 m wide and 4 m long (0.001 acre).
    _field(MADE_UP_SLIVER, _albers_rect(SIDE - 1, -200, SIDE + 300, 4))
    compute_shares(parcel)
    assert MADE_UP_SLIVER not in _shares(parcel)
    assert set(_shares(parcel)) == {MADE_UP_A, MADE_UP_B}


def test_a_use_area_with_a_crossed_edge_still_gets_its_shares():
    """A bow-tie outline (two triangles meeting at the centre) is repaired before measuring."""
    from datasync.field_list import compute_shares

    bow_tie = _albers_ring([(0, 0), (SIDE, SIDE), (SIDE, 0), (0, SIDE)])
    parcel = _use_area(number="MADEUP-BOW-TIE", geometry=bow_tie)
    _field(MADE_UP_A, _albers_rect(-200, -200, SIDE + 200, SIDE + 200))
    compute_shares(parcel)
    shares = _shares(parcel)
    assert set(shares) == {MADE_UP_A}
    # The two triangles are each a quarter of the 100-acre square.
    assert abs(shares[MADE_UP_A] - D("50.00")) <= D("0.01")


def test_a_changed_use_area_outline_recomputes_its_shares():
    from datasync.field_list import compute_shares

    parcel = _use_area()
    _sixty_thirty()
    compute_shares(parcel)
    # The use area is redrawn to the left half: 50 acres, all of it in field A.
    parcel.geometry = _albers_rect(0, 0, 0.5 * SIDE, SIDE)
    parcel.area_acres = D("50.00")
    parcel.save()
    assert _shares(parcel) == {MADE_UP_A: D("50.00")}


# ---------------------------------------------------------------- 2. crop ET


def test_the_recorded_crop_et_is_the_area_weighted_depth_over_the_use_areas_acres():
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=500, pr_mm=0)
    _month(b, et_mm=400, pr_mm=0)

    crop_et.record_fetched_months(parcel, [JULY])

    record = crop_et.current_record(parcel, JULY)
    assert record is not None
    # (500 x 60 + 400 x 30) / 100 = 420 mm over the use area's 100 acres.
    assert D(record.depth_mm) == D("420")
    assert record.fetched_on == RECEIVED
    # The note names each field and its acres inside the use area.
    assert str(MADE_UP_A) in record.note and "60.00" in record.note
    assert str(MADE_UP_B) in record.note and "30.00" in record.note


def test_et_gross_books_the_sum_of_each_fields_acre_feet():
    from accounting.steps import et_gross
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=500, pr_mm=0)
    _month(b, et_mm=400, pr_mm=0)
    crop_et.record_fetched_months(parcel, [JULY])

    af, _record = et_gross(D("0"), parcel, JULY, {}, {})
    # 500 x 60 / 304.8 + 400 x 30 / 304.8 = 98.43 + 39.37
    assert af.quantize(D("0.01")) == D("137.80")


def test_a_use_area_with_no_share_gets_no_figure_from_the_field_list():
    from datasync import crop_et
    from datasync.field_list import compute_shares

    a, b = _sixty_thirty()
    _month(a, et_mm=500, pr_mm=0)
    _month(b, et_mm=400, pr_mm=0)
    # A made-up use area far from both fields.
    lonely = _use_area(number="MADEUP-NO-FIELD", geometry=_albers_rect(5000, 5000, 5000 + SIDE, 5000 + SIDE))
    compute_shares(lonely)
    assert _shares(lonely) == {}
    assert crop_et.record_fetched_months(lonely, [JULY]) == []
    assert crop_et.current_record(lonely, JULY) is None


def test_a_month_missing_for_one_of_the_fields_is_not_figured():
    """A field OpenET sent nothing for leaves the use area's month without a figure, never a partial one."""
    from datasync import crop_et
    from datasync.field_list import compute_shares, field_share_mm

    parcel = _use_area()
    a, _b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=500, pr_mm=0)
    assert field_share_mm(parcel, JULY, "et") is None
    assert crop_et.record_fetched_months(parcel, [JULY]) == []


# ---------------------------------------------------------------- 3. rain, field by field


def _rain_case():
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    # Made-up winter month: field A wet with little crop use (its effective rain is capped
    # at its 5 mm of crop ET), field B dry with a growing crop (capped at its 10 mm of rain).
    _month(a, et_mm=5, pr_mm=100)
    _month(b, et_mm=400, pr_mm=10)
    crop_et.record_fetched_months(parcel, [JULY])
    return parcel


def test_effective_rain_is_figured_field_by_field():
    from accounting.steps import subtract_effective_precip

    parcel = _rain_case()
    _new, record = subtract_effective_precip(
        D("500"), parcel, JULY, {}, {"method": "usda_scs", "soil_storage_in": 3.0}
    )
    pe_af = D(record["detail"]["effective_precip_af"])
    # Field A: 5 mm over 60 acres; field B: 10 mm over 30 acres. 600 / 304.8.
    assert pe_af.quantize(D("0.0001")) == D("1.9685")
    # Applying the rule once to the area-weighted depths (63 mm rain, 123 mm crop ET over
    # 100 acres) would give 15.0815 AF, which is not the figure.
    assert pe_af.quantize(D("0.0001")) != D("15.0815")


def test_the_step_records_the_area_weighted_rain_depth():
    """The month page prints precip_mm x area_acres as the rain on the covered acres."""
    from accounting.steps import subtract_effective_precip

    parcel = _rain_case()
    _new, record = subtract_effective_precip(
        D("500"), parcel, JULY, {}, {"method": "usda_scs", "soil_storage_in": 3.0}
    )
    # (100 x 60 + 10 x 30) / 100 = 63 mm over the use area's 100 acres.
    assert D(record["detail"]["precip_mm"]) == D("63")
    assert set(record["detail"]) == {
        "method", "precip_mm", "et_mm", "effective_precip_mm", "effective_precip_af",
    }


def test_raw_rain_counts_only_the_acres_inside_fields():
    from accounting.steps import subtract_effective_precip
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=50, pr_mm=30)
    _month(b, et_mm=50, pr_mm=10)
    crop_et.record_fetched_months(parcel, [JULY])
    _new, record = subtract_effective_precip(D("100"), parcel, JULY, {}, {"method": "raw"})
    # 30 x 60 / 304.8 + 10 x 30 / 304.8; the 10 acres in no field count no rain.
    assert D(record["detail"]["effective_precip_af"]).quantize(D("0.0001")) == D("6.8898")


def test_a_use_area_with_no_share_keeps_the_cached_rain_path():
    """Without OpenET fields the step reads the month's recorded rain, as on a site using the older routes."""
    from accounting.steps import subtract_effective_precip
    from datasync import crop_et
    from datasync.models import OpenETCache

    parcel = _use_area(number="MADEUP-CACHE-ONLY")
    for variable, model, key, value in (("ET", "Ensemble", "et", 120.0), ("precip", "GRIDMET", "precip", 30.0)):
        OpenETCache.objects.create(
            parcel=parcel, geometry=parcel.geometry, start_date=JULY_1, end_date=dt.date(2025, 7, 31),
            variable=variable, model_name=model, origin="fixture",
            et_data=[{key: value, "date": JULY, "unit": "mm"}],
        )
    crop_et.record_fetched_months(parcel, [JULY])
    crop_et.record_fetched_months(parcel, [JULY], variable="precip", model="GRIDMET")
    _new, record = subtract_effective_precip(D("100"), parcel, JULY, {}, {"method": "raw"})
    assert record["detail"]["precip_mm"] == "30.0"
    # 30 mm over the whole 100 acres.
    assert D(record["detail"]["effective_precip_af"]).quantize(D("0.0001")) == D("9.8425")


# ---------------------------------------------------------------- 4. the newer figure


def test_a_field_month_received_again_at_another_depth_is_a_newer_figure():
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=500, pr_mm=0)
    _month(b, et_mm=400, pr_mm=0)
    crop_et.record_fetched_months(parcel, [JULY])

    # OpenET (in this made-up case) later sends field A's July at 550 mm.
    _month(a, et_mm=550, pr_mm=0, received_on=LATER)

    newest = crop_et.newest_fetched(parcel, JULY)
    # (550 x 60 + 400 x 30) / 100 = 450 mm, received on the newer of the two fields' days.
    assert newest.mm == D("450")
    assert newest.fetched_on == LATER

    record = crop_et.current_record(parcel, JULY)
    assert D(record.depth_mm) == D("420")
    newer = crop_et.newer_figure(record)
    assert newer is not None and newer.mm == D("450")
    # Recording again leaves the recorded month alone.
    assert crop_et.record_fetched_months(parcel, [JULY]) == []
    assert D(crop_et.current_record(parcel, JULY).depth_mm) == D("420")


# ---------------------------------------------------------------- 5. the client


def _gz(payload):
    return gzip.compress(payload if isinstance(payload, bytes) else json.dumps(payload).encode())


def _square_feature(field_id, x0, y0, size=0.001):
    ring = [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]
    return {"type": "Feature", "properties": {"field_id": field_id},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _figures_csv(rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["time", "field_id", "collection", "value_mm"])
    writer.writerows(rows)
    return out.getvalue().encode()


def _response(status, body, content_type="application/json"):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    resp.headers["Content-Type"] = content_type
    resp.url = "https://openet-api.org/"
    return resp


class MadeUpOpenET:
    """A made-up OpenET service. Every answer is shaped like a recorded answer, with made-up values.

    ``fields`` maps a made-up field number to its made-up outline square (lower-left corner in
    longitude and latitude); ``lookups`` maps a rectangle's west edge to the numbers it holds;
    ``refuse`` names paths answered with OpenET's refusal.
    """

    def __init__(self, fields=None, lookups=None, refuse=(), max_area=200000):
        self.fields = fields or {}
        self.lookups = lookups or {}
        self.refuse = set(refuse)
        #: The account's "Max Area Acres"; None makes the status read fail to give one.
        self.max_area = max_area
        self.calls = []
        self.used = 0

    def paid(self, path=None):
        return [c for c in self.calls if c["path"] != "/account/status" and (path is None or c["path"] == path)]

    def __call__(self, method, url, **kwargs):
        path = url.replace("https://openet-api.org", "")
        body = kwargs.get("json")
        if body is None and kwargs.get("data"):
            body = json.loads(kwargs["data"])
        self.calls.append({"method": method, "path": path, "body": body})
        if path == "/account/status":
            return _response(200, {"Tier": 1, "Monthly Requests": f"{self.used} used of 100",
                                   "Max Area Acres": self.max_area, "Max Field IDS": 400})
        if path in self.refuse:
            return _response(404, {"detail": "No conforming data found in geodatabase."})
        self.used += 1
        if path == "/geodatabase/metadata/ids":
            west = min(body["geometry"][0::2])
            ids = next((v for k, v in self.lookups.items() if abs(k - west) < 0.01), [])
            return _response(200, _gz(ids), "application/x-zip-compressed")
        if path == "/geodatabase/metadata/boundaries":
            feats = [_square_feature(i, *self.fields[i]) for i in body["field_ids"] if i in self.fields]
            return _response(200, _gz({"type": "FeatureCollection", "features": feats}),
                             "application/x-zip-compressed")
        if path == "/geodatabase/timeseries":
            rows = []
            for i in body["field_ids"]:
                rows.append(["2025-07-01", i, "ensemble_et", "111.111"])
                rows.append(["2025-07-01", i, "gridmet_pr", "2.222"])
            return _response(200, _figures_csv(rows), "text/csv; charset=utf-8")
        return _response(404, {"detail": "Not Found"})


@pytest.fixture
def openet_key(monkeypatch):
    monkeypatch.setenv("OPENET_API_KEY", "made-up-key-not-real")


@pytest.fixture
def no_wait():
    with mock.patch("time.sleep"):
        yield


def test_lookup_sends_four_corners_and_reads_integer_field_numbers(openet_key, no_wait):
    from datasync import field_list

    service = MadeUpOpenET(lookups={-120.31: [MADE_UP_A, MADE_UP_B]})
    with mock.patch("requests.request", side_effect=service):
        ids = field_list.lookup((-120.31, 37.30, -120.24, 37.34))
    assert ids == [MADE_UP_A, MADE_UP_B]
    assert all(isinstance(i, int) for i in ids)
    (call,) = service.paid("/geodatabase/metadata/ids")
    corners = list(zip(call["body"]["geometry"][0::2], call["body"]["geometry"][1::2]))
    assert set(corners) == {(-120.31, 37.30), (-120.31, 37.34), (-120.24, 37.34), (-120.24, 37.30)}


def test_outlines_send_integers_and_read_the_outlines(openet_key, no_wait):
    from datasync import field_list

    service = MadeUpOpenET(fields={MADE_UP_A: (-120.30, 37.31), MADE_UP_B: (-120.29, 37.32)})
    with mock.patch("requests.request", side_effect=service):
        pairs = field_list.outlines([MADE_UP_A, MADE_UP_B])
    (call,) = service.paid("/geodatabase/metadata/boundaries")
    assert call["body"]["field_ids"] == [MADE_UP_A, MADE_UP_B]
    assert all(isinstance(i, int) for i in call["body"]["field_ids"])
    got = dict(pairs)
    assert set(got) == {MADE_UP_A, MADE_UP_B}
    assert got[MADE_UP_A].srid == 4326
    assert got[MADE_UP_A].geom_type in ("Polygon", "MultiPolygon")


def test_figures_ask_for_monthly_crop_et_and_rain_and_read_the_csv(openet_key, no_wait):
    from datasync import field_list

    service = MadeUpOpenET()
    with mock.patch("requests.request", side_effect=service):
        rows = field_list.figures([MADE_UP_A], dt.date(2025, 7, 1), dt.date(2025, 7, 31))
    (call,) = service.paid("/geodatabase/timeseries")
    body = call["body"]
    assert body["interval"] == "monthly"
    assert body["models"] == ["ensemble"]
    assert sorted(body["variables"]) == ["et", "pr"]
    assert body["file_format"].lower() == "csv"
    assert body["field_ids"] == [MADE_UP_A]
    assert body["date_range"] == ["2025-07-01", "2025-07-31"]
    assert list(rows) == [(MADE_UP_A, JULY_1, D("111.111"), D("2.222"))]


def test_a_request_never_carries_more_field_numbers_than_the_account_allows(openet_key, no_wait, settings):
    from datasync import field_list

    settings.OPENET_FIELDS_PER_REQUEST = 100
    made_up = list(range(99000000001, 99000000251))  # 250 made-up numbers
    service = MadeUpOpenET()
    with mock.patch("requests.request", side_effect=service):
        field_list.figures(made_up, dt.date(2025, 7, 1), dt.date(2025, 7, 31))
    sizes = [len(c["body"]["field_ids"]) for c in service.paid("/geodatabase/timeseries")]
    assert sizes == [100, 100, 50]
    sent = [i for c in service.paid("/geodatabase/timeseries") for i in c["body"]["field_ids"]]
    assert sent == made_up


def test_the_default_is_the_published_first_tier_of_100():
    from django.conf import settings as live

    assert live.OPENET_FIELDS_PER_REQUEST == 100


def test_a_refused_request_raises_with_openets_words_and_writes_nothing(openet_key, no_wait):
    from datasync import field_list
    from datasync.models import OpenETField, OpenETFieldMonth

    service = MadeUpOpenET(refuse={"/geodatabase/metadata/boundaries"})
    with mock.patch("requests.request", side_effect=service), pytest.raises(field_list.OpenETRefused) as refused:
        field_list.outlines([MADE_UP_A])
    assert "No conforming data found in geodatabase." in str(refused.value)
    assert not OpenETField.objects.exists()
    assert not OpenETFieldMonth.objects.exists()


def test_every_request_is_written_down_with_openets_own_count_after_it(openet_key, no_wait):
    from datasync import field_list
    from datasync.models import OpenETRequest

    service = MadeUpOpenET(fields={MADE_UP_A: (-120.30, 37.31)})
    service.used = 40
    with mock.patch("requests.request", side_effect=service):
        field_list.outlines([MADE_UP_A])
    (row,) = OpenETRequest.objects.all()
    assert row.kind == "outlines"
    assert row.answered is True
    assert row.http_status == 200
    assert row.ids_count == 1
    assert row.provider_used == 41
    # The status read came after the request.
    paths = [c["path"] for c in service.calls]
    assert paths.index("/account/status") > paths.index("/geodatabase/metadata/boundaries")


def test_the_field_list_is_the_default_route(settings):
    """With no OPENET_MODE set, a site takes the field list; "api" and "gee" still choose their routes."""
    from pathlib import Path

    from django.conf import settings as live

    from datasync.adapters import get_openet_adapter

    base = (Path(live.BASE_DIR) / "config" / "settings" / "base.py").read_text()
    assert 'OPENET_MODE", default="fields")' in base
    del settings.OPENET_MODE
    assert type(get_openet_adapter()).__name__ not in ("OpenETAdapter", "GEEOpenETAdapter")
    settings.OPENET_MODE = "fields"
    assert type(get_openet_adapter()).__name__ not in ("OpenETAdapter", "GEEOpenETAdapter")
    settings.OPENET_MODE = "api"
    assert type(get_openet_adapter()).__name__ == "OpenETAdapter"


def test_no_word_a_person_reads_says_fetch(openet_key, no_wait, settings):
    """The sync's output says what OpenET sent and the day received, never 'fetch'."""
    settings.OPENET_MODE = "fields"
    _use_area(number="MADEUP-WORDS", geometry=MultiPolygon(
        Polygon(((-120.300, 37.310), (-120.299, 37.310), (-120.299, 37.311), (-120.300, 37.311), (-120.300, 37.310))),
        srid=4326,
    ))
    service = MadeUpOpenET(fields={MADE_UP_A: (-120.3002, 37.3098)}, lookups={-120.30: [MADE_UP_A]})
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=service):
        call_command("sync_openet_parcels", start_date="2025-07-01", end_date="2025-07-31", stdout=out)
        call_command("sync_openet_parcels", start_date="2025-07-01", end_date="2025-07-31",
                     dry_run=True, stdout=out)
    assert "OpenET sent" in out.getvalue()
    assert "fetch" not in out.getvalue().lower()


# ---------------------------------------------------------------- 7. setup resumes


def _two_groups():
    """Two made-up use areas about 2 km apart, so each is its own lookup rectangle."""
    near = MultiPolygon(Polygon(((-120.300, 37.310), (-120.299, 37.310), (-120.299, 37.311),
                                 (-120.300, 37.311), (-120.300, 37.310))), srid=4326)
    far = MultiPolygon(Polygon(((-120.270, 37.310), (-120.269, 37.310), (-120.269, 37.311),
                                (-120.270, 37.311), (-120.270, 37.310))), srid=4326)
    _use_area(number="MADEUP-GROUP-NEAR", geometry=near)
    _use_area(number="MADEUP-GROUP-FAR", geometry=far)
    return MadeUpOpenET(
        fields={
            MADE_UP_A: (-120.3002, 37.3098),
            MADE_UP_B: (-120.2995, 37.3102),
            MADE_UP_C: (-120.2702, 37.3098),
        },
        lookups={-120.30: [MADE_UP_A, MADE_UP_B], -120.27: [MADE_UP_C]},
    )


def _run(service, **opts):
    with mock.patch("requests.request", side_effect=service):
        try:
            call_command("sync_openet_parcels", start_date="2025-07-01", end_date="2025-07-31",
                         stdout=io.StringIO(), **opts)
        except CommandError:
            pass


def test_a_setup_stopped_by_the_allowance_continues_where_it_stopped(openet_key, no_wait, settings):
    settings.OPENET_MODE = "fields"
    settings.OPENET_FIELDS_PER_REQUEST = 2
    service = _two_groups()

    # This month's allowance has room for three requests: both lookups and one outline batch.
    settings.OPENET_MONTHLY_BUDGET = 3
    _run(service)
    first = list(service.paid())
    assert [c["path"] for c in first] == [
        "/geodatabase/metadata/ids",
        "/geodatabase/metadata/ids",
        "/geodatabase/metadata/boundaries",
    ]

    # The month turns over (made up here by a larger allowance).
    settings.OPENET_MONTHLY_BUDGET = 10
    _run(service)
    second = service.paid()[len(first):]
    assert "/geodatabase/metadata/ids" not in [c["path"] for c in second]
    asked_outlines = [i for c in service.paid("/geodatabase/metadata/boundaries") for i in c["body"]["field_ids"]]
    assert sorted(asked_outlines) == sorted([MADE_UP_A, MADE_UP_B, MADE_UP_C])
    assert len(asked_outlines) == len(set(asked_outlines))
    asked_figures = {i for c in service.paid("/geodatabase/timeseries") for i in c["body"]["field_ids"]}
    assert asked_figures == {MADE_UP_A, MADE_UP_B, MADE_UP_C}


def test_a_finished_setup_is_not_asked_again(openet_key, no_wait, settings):
    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _two_groups()
    _run(service)
    setup_calls = [c for c in service.paid() if c["path"] != "/geodatabase/timeseries"]
    _run(service)
    again = [c for c in service.paid() if c["path"] != "/geodatabase/timeseries"]
    assert again == setup_calls
    assert len(service.paid("/geodatabase/timeseries")) == 2


def test_the_route_records_each_use_areas_month_from_its_fields(openet_key, no_wait, settings):
    from datasync import crop_et
    from datasync.models import OpenETFieldMonth

    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _two_groups()
    _run(service)
    assert OpenETFieldMonth.objects.filter(month=JULY_1).count() == 3
    for number in ("MADEUP-GROUP-NEAR", "MADEUP-GROUP-FAR"):
        parcel = Parcel.objects.get(parcel_number=number)
        assert crop_et.current_record(parcel, JULY) is not None


# ---------------------------------------------------------------- 8. the use areas' figures first


#: Made-up fields a stopped whole-area run listed and never outlined: no outline, no share.
MADE_UP_LEFTOVERS = [99000000101, 99000000102, 99000000103]


def _leftovers_after_a_finished_setup(settings):
    """Both made-up use areas set up and figured, then three listed fields left with no outline,
    as a whole-area run the allowance stopped leaves them. Returns the service and the count of
    requests sent so far."""
    from datasync.models import OpenETField

    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _two_groups()
    _run(service)
    for number in MADE_UP_LEFTOVERS:
        OpenETField.objects.create(field_id=number, geometry=None, received_on=RECEIVED,
                                   whole_area_only=True)
    return service, len(service.paid())


def test_with_one_request_left_the_monthly_run_asks_the_use_areas_figures_not_leftover_outlines(
        openet_key, no_wait, settings):
    service, sent = _leftovers_after_a_finished_setup(settings)
    settings.OPENET_MONTHLY_BUDGET = sent + 1
    _run(service)
    assert [c["path"] for c in service.paid()[sent:]] == ["/geodatabase/timeseries"]


def test_the_monthly_run_leaves_a_whole_area_runs_outlines_to_the_next_whole_area_run(
        openet_key, no_wait, settings):
    service, sent = _leftovers_after_a_finished_setup(settings)
    _run(service)
    assert [c["path"] for c in service.paid()[sent:]] == ["/geodatabase/timeseries"]
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=AssertionError("a dry run sent a request")):
        call_command("sync_openet_parcels", "--dry-run", start_date="2025-07-01",
                     end_date="2025-07-31", stdout=out)
    assert "outlines" not in out.getvalue()


def _whole_area_leftovers_beside_a_use_area_on_no_field(settings):
    """The finished setup of ``_two_groups``, a third made-up use area whose lookup OpenET
    answered with no field (so it never gets a share), and three fields only a whole-area lookup
    listed, left with no outline by a run the allowance stopped."""
    from datasync.models import OpenETField

    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _two_groups()
    bare = MultiPolygon(Polygon(((-120.240, 37.310), (-120.239, 37.310), (-120.239, 37.311),
                                 (-120.240, 37.311), (-120.240, 37.310))), srid=4326)
    _use_area(number="MADEUP-ON-NO-FIELD", geometry=bare)
    _run(service)
    for number in MADE_UP_LEFTOVERS:
        OpenETField.objects.create(field_id=number, geometry=None, received_on=RECEIVED,
                                   whole_area_only=True)
    return service, len(service.paid())


def test_a_use_area_on_no_openet_field_does_not_send_the_monthly_run_after_whole_area_outlines(
        openet_key, no_wait, settings):
    service, sent = _whole_area_leftovers_beside_a_use_area_on_no_field(settings)
    _run(service)
    assert "/geodatabase/metadata/boundaries" not in [c["path"] for c in service.paid()[sent:]]


def test_a_use_area_lookup_that_lists_a_whole_area_field_makes_it_the_use_areas_again():
    from datasync import field_list
    from datasync.models import OpenETField

    OpenETField.objects.create(field_id=MADE_UP_A, geometry=None, received_on=RECEIVED, whole_area_only=True)
    field_list.store_listed([MADE_UP_A, MADE_UP_B], RECEIVED, whole_area=False)
    field_list.store_listed([MADE_UP_B, MADE_UP_C], RECEIVED, whole_area=True)
    held = dict(OpenETField.objects.values_list("field_id", "whole_area_only"))
    assert held == {MADE_UP_A: False, MADE_UP_B: False, MADE_UP_C: True}


def test_the_dry_run_counts_the_figures_requests_a_run_sends_in_its_two_steps(openet_key, no_wait, settings):
    """Figures go in two steps (the use areas' fields, then the rest), so the dry run counts each
    step's batches: 2 shared fields and 1 more at 3 a request is 2 requests, not 1."""
    from datasync.models import OpenETField, OpenETFieldShare

    _leftovers_after_a_finished_setup(settings)
    settings.OPENET_FIELDS_PER_REQUEST = 3
    OpenETFieldShare.objects.filter(field__field_id=MADE_UP_C).delete()
    OpenETField.objects.filter(field_id__in=MADE_UP_LEFTOVERS).delete()
    from geography.models import Boundary
    Boundary.objects.create(name="Made-up basin", geometry=MultiPolygon(
        Polygon.from_bbox((-120.31, 37.30, -120.26, 37.32)), srid=4326))
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=AssertionError("a dry run sent a request")):
        call_command("sync_openet_parcels", "--whole-area", "--dry-run", start_date="2025-07-01",
                     end_date="2025-08-31", stdout=out)
    figures = re.search(r"(\d+) request\(s\) for the figures of (\d+) fields", out.getvalue())
    assert figures and (figures.group(1), figures.group(2)) == ("2", "3")


def test_a_use_area_added_after_a_stopped_whole_area_lookup_gets_its_own_lookup_and_every_fields_share(
        openet_key, no_wait, settings):
    """A boundary lookup listed the use area's fields and the allowance stopped the run before
    their outlines. A plain run must not take shares from the outlines it happens to hold: the use
    area gets its own lookup, its fields' outlines, and a share in each."""
    from datasync.models import OpenETField
    from geography.models import Boundary

    settings.OPENET_MODE = "fields"
    Boundary.objects.create(name="Made-up basin", geometry=MultiPolygon(
        Polygon.from_bbox((-120.32, 37.30, -120.26, 37.32)), srid=4326))
    service = MadeUpOpenET(
        fields={MADE_UP_A: (-120.3002, 37.3098), MADE_UP_B: (-120.2995, 37.3102), MADE_UP_C: (-120.2702, 37.3098)},
        lookups={-120.32: [MADE_UP_A, MADE_UP_B, MADE_UP_C], -120.30: [MADE_UP_A, MADE_UP_B], -120.27: [MADE_UP_C]},
    )
    # A run needs a use area; this one lies east of the boundary, on no OpenET field.
    bare = MultiPolygon(Polygon(((-120.240, 37.310), (-120.239, 37.310), (-120.239, 37.311),
                                 (-120.240, 37.311), (-120.240, 37.310))), srid=4326)
    _use_area(number="MADEUP-ON-NO-FIELD", geometry=bare)
    settings.OPENET_MONTHLY_BUDGET = 2
    _run(service, whole_area=True)
    assert [c["path"] for c in service.paid()] == ["/geodatabase/metadata/ids"] * 2
    _two_groups()  # the two made-up use areas, added after the boundary lookup
    settings.OPENET_MONTHLY_BUDGET = 50
    _run(service)
    assert not OpenETField.objects.filter(geometry__isnull=True).exists()
    from datasync.models import OpenETFieldShare

    for number, fields in (("MADEUP-GROUP-NEAR", {MADE_UP_A, MADE_UP_B}), ("MADEUP-GROUP-FAR", {MADE_UP_C})):
        parcel = Parcel.objects.get(parcel_number=number)
        assert set(OpenETFieldShare.objects.filter(parcel=parcel).values_list("field__field_id", flat=True)) == fields


def test_a_field_that_takes_a_share_is_no_longer_whole_area_only():
    from datasync import field_list
    from datasync.models import OpenETField

    parcel = _use_area()
    field = _field(MADE_UP_A, _albers_rect(0, 0, SIDE, SIDE))
    OpenETField.objects.filter(pk=field.pk).update(whole_area_only=True)
    field_list.compute_shares(parcel)
    assert OpenETField.objects.get(pk=field.pk).whole_area_only is False


def test_a_whole_area_run_asks_the_use_areas_figures_before_any_outline(openet_key, no_wait, settings):
    from geography.models import Boundary

    service, sent = _leftovers_after_a_finished_setup(settings)
    Boundary.objects.create(name="Made-up basin", geometry=MultiPolygon(
        Polygon.from_bbox((-120.31, 37.30, -120.26, 37.32)), srid=4326))
    _run(service, whole_area=True)
    paths = [c["path"] for c in service.paid()[sent:]]
    assert paths[0] == "/geodatabase/timeseries"
    asked_outlines = [i for c in service.paid("/geodatabase/metadata/boundaries")[1:] for i in c["body"]["field_ids"]]
    assert sorted(asked_outlines) == MADE_UP_LEFTOVERS


# ---------------------------------------------------------------- 9. whole-area lookups follow the boundary

#: A made-up triangular basin: its bounding box is about 217,000 acres, so at the made-up
#: account's 200,000 acres a lookup it takes two strips, and at 50,000 five.
TRIANGLE = ((-120.60, 37.00), (-120.30, 37.00), (-120.60, 37.30))
#: The corner of the triangle's bounding box farthest from the triangle.
FAR_CORNER = (-120.30, 37.30)


def _triangle_basin():
    from geography.models import Boundary

    Boundary.objects.create(name="Made-up basin", geometry=MultiPolygon(
        Polygon(TRIANGLE + (TRIANGLE[0],)), srid=4326))
    # A run needs a use area; this one lies east of the basin, on no OpenET field.
    bare = MultiPolygon(Polygon(((-120.240, 37.310), (-120.239, 37.310), (-120.239, 37.311),
                                 (-120.240, 37.311), (-120.240, 37.310))), srid=4326)
    _use_area(number="MADEUP-ON-NO-FIELD", geometry=bare)
    return MadeUpOpenET(
        fields={MADE_UP_A: (-120.58, 37.01), MADE_UP_B: (-120.55, 37.10), MADE_UP_C: (-120.59, 37.25)},
        lookups={-120.60: [MADE_UP_A, MADE_UP_B, MADE_UP_C]},
    )


def _boundary_lookups(service):
    """The lookups a run sent over the basin (the use area's own lookup lies east of it)."""
    return [c for c in service.paid("/geodatabase/metadata/ids") if min(c["body"]["geometry"][0::2]) < -120.5]


def _ring(call):
    points = list(zip(call["body"]["geometry"][0::2], call["body"]["geometry"][1::2]))
    return Polygon(points + [points[0]], srid=4326)


def test_a_whole_area_lookup_sends_the_boundarys_part_of_its_strip_not_its_four_corners(
        openet_key, no_wait, settings):
    from django.contrib.gis.geos import Point

    from datasync import field_list

    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _triangle_basin()
    _run(service, whole_area=True)
    sent = _boundary_lookups(service)
    assert len(sent) == len(field_list.boundary_areas(max_acres=200000)) == 2
    rings = [_ring(c) for c in sent]
    assert not any(ring.covers(Point(*FAR_CORNER, srid=4326)) for ring in rings)
    triangle = Polygon(TRIANGLE + (TRIANGLE[0],), srid=4326)
    union = rings[0].union(rings[1])
    assert union.covers(triangle)
    # Each request's note still names its strip, so a later run can tell what was answered.
    assert field_list.answered_rectangles(whole_area=True) == set(field_list.boundary_areas(max_acres=200000))


def test_a_strip_that_holds_none_of_the_boundary_sends_no_lookup(openet_key, no_wait, settings):
    from datasync import field_list

    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _triangle_basin()
    strips = field_list.boundary_areas(max_acres=200000)
    beside = (-121.20, 37.00, -121.10, 37.30)  # west of the basin
    with mock.patch.object(field_list, "boundary_areas", return_value=[beside] + strips):
        _run(service, whole_area=True)
    assert len(_boundary_lookups(service)) == 2
    assert not [c for c in service.paid("/geodatabase/metadata/ids") if min(c["body"]["geometry"][0::2]) < -121]


def test_a_stopped_whole_area_run_does_not_ask_an_answered_strip_again(openet_key, no_wait, settings):
    settings.OPENET_MODE = "fields"
    service = _triangle_basin()
    # Room for the use area's lookup and one strip.
    settings.OPENET_MONTHLY_BUDGET = 2
    _run(service, whole_area=True)
    assert len(_boundary_lookups(service)) == 1
    settings.OPENET_MONTHLY_BUDGET = 50
    _run(service, whole_area=True)
    sent = _boundary_lookups(service)
    assert len(sent) == 2
    assert sent[0]["body"] != sent[1]["body"]


@pytest.mark.parametrize("later_limit", [50000, None], ids=["smaller-limit", "status-read-fails"])
def test_answered_strips_are_not_asked_again_when_the_area_limit_cuts_them_differently(
        openet_key, no_wait, settings, later_limit):
    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    service = _triangle_basin()
    _run(service, whole_area=True)
    assert len(_boundary_lookups(service)) == 2
    service.max_area = later_limit
    _run(service, whole_area=True)
    assert len(_boundary_lookups(service)) == 2


def _dry_run_text(service, *args):
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=service):
        call_command("sync_openet_parcels", "--dry-run", *args, start_date="2025-07-01",
                     end_date="2025-07-31", stdout=out)
    return out.getvalue()


def test_the_dry_run_cuts_the_strips_at_the_accounts_own_limit_and_sends_no_paid_request(
        openet_key, no_wait, settings):
    from datasync import field_list

    settings.OPENET_MODE = "fields"
    service = _triangle_basin()
    text = _dry_run_text(service, "--whole-area")
    assert service.paid() == []
    for west, south, east, north in field_list.boundary_areas(max_acres=200000):
        assert f"{west}, {south}, {east}, {north}" in text
    assert len(re.findall(r"^  lookup ", text, re.M)) == 3  # the use area's own and two strips


def test_the_dry_run_counts_the_figures_of_fields_waiting_on_their_outlines(openet_key, no_wait, settings):
    """A whole-area run stopped after its lookups: three fields wait on their outlines. At two
    fields a request, a run sends 2 outline requests and up to 2 figures requests for them."""
    settings.OPENET_MODE = "fields"
    settings.OPENET_FIELDS_PER_REQUEST = 2
    service = _triangle_basin()
    settings.OPENET_MONTHLY_BUDGET = 3  # the use area's lookup and both strips
    _run(service, whole_area=True)
    assert len(_boundary_lookups(service)) == 2
    text = _dry_run_text(service, "--whole-area")
    total = re.search(r"Would send (up to )?(\d+)", text)
    assert total and total.group(2) == "4" and total.group(1)


def test_a_stopped_whole_area_run_says_to_run_it_again_with_whole_area(openet_key, no_wait, settings):
    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 2
    service = _triangle_basin()
    out = io.StringIO()
    with mock.patch("requests.request", side_effect=service):
        call_command("sync_openet_parcels", "--whole-area", start_date="2025-07-01",
                     end_date="2025-07-31", stdout=out)
    stop = [line for line in out.getvalue().splitlines() if "allowance is used" in line]
    assert stop and "--whole-area" in stop[0]


# ---------------------------------------------------------------- the fields file's outlines


def _fields_file(tmp_path, outline):
    """A made-up fields file: one made-up field with ``outline``, one made-up use area's share."""
    Parcel.objects.create(
        parcel_number="MADEUP-OUTLINE-LOAD",
        geometry=MultiPolygon(Polygon.from_bbox((-120.5, 37.2, -120.4, 37.3)), srid=4326),
        area_acres=10,
        status="active",
    )
    field = {"field_id": MADE_UP_A, "area_acres": "10.00", "received_on": "2025-12-01"}
    if outline is not None:
        field["outline"] = outline
    payload = {
        "meta": {"source": "made up for this test"},
        "fields": [field],
        # Deliberately not the outline's overlap: the load keeps the share the file states.
        "shares": [{"parcel_number": "MADEUP-OUTLINE-LOAD", "field_id": MADE_UP_A, "overlap_acres": "3.21"}],
        "months": [{"field_id": MADE_UP_A, "month": "2025-10", "et_mm": "30.48", "pr_mm": "1.0",
                    "received_on": "2025-12-01"}],
    }
    path = tmp_path / "made_up_fields.json"
    path.write_text(json.dumps(payload))
    return path


MADE_UP_RING = [[-120.46, 37.24], [-120.45, 37.24], [-120.45, 37.25], [-120.46, 37.25], [-120.46, 37.24]]


def test_the_fields_load_stores_each_outline_as_a_multipolygon(tmp_path):
    from datasync.models import OpenETField, OpenETFieldShare

    path = _fields_file(tmp_path, {"type": "Polygon", "coordinates": [MADE_UP_RING]})
    call_command("load_openet_fields_fixture", "--fixture", str(path), stdout=io.StringIO())
    field = OpenETField.objects.get(field_id=MADE_UP_A)
    assert field.geometry.geom_type == "MultiPolygon"
    assert field.geometry.srid == 4326
    assert field.geometry[0].exterior_ring.coords[0] == (-120.46, 37.24)
    # The outline is stored; the share stays as the file states it.
    (share,) = OpenETFieldShare.objects.filter(field=field)
    assert share.overlap_acres == D("3.21")


def test_the_fields_load_keeps_a_multipolygon_outline(tmp_path):
    from datasync.models import OpenETField

    path = _fields_file(tmp_path, {"type": "MultiPolygon", "coordinates": [[MADE_UP_RING]]})
    call_command("load_openet_fields_fixture", "--fixture", str(path), stdout=io.StringIO())
    assert OpenETField.objects.get(field_id=MADE_UP_A).geometry.num_geom == 1


def test_a_field_with_no_outline_in_the_file_loads_with_none(tmp_path):
    from datasync.models import OpenETField

    path = _fields_file(tmp_path, None)
    call_command("load_openet_fields_fixture", "--fixture", str(path), stdout=io.StringIO())
    assert OpenETField.objects.get(field_id=MADE_UP_A).geometry is None


# ---------------------------------------------------------------- the run stamps its fields


def _stamped(record):
    """The per-field list the et_gross step stamped, or None."""
    return record["detail"].get("fields")


def _sixty_thirty_july(et_a=500, et_b=400, pr_a=40, pr_b=20):
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=et_a, pr_mm=pr_a)
    _month(b, et_mm=et_b, pr_mm=pr_b)
    crop_et.record_fetched_months(parcel, [JULY])
    return parcel, a, b


def test_et_gross_stamps_each_field_its_acres_crop_et_and_rainfall():
    from accounting.steps import et_gross

    parcel, a, b = _sixty_thirty_july()
    af, record = et_gross(D("0"), parcel, JULY, {}, {})
    rows = _stamped(record)
    # Largest share first.
    assert [r["field_id"] for r in rows] == [MADE_UP_A, MADE_UP_B]
    assert [D(r["acres"]) for r in rows] == [D("60.00"), D("30.00")]
    crop = [D(r["crop_et_af"]) for r in rows]
    rain = [D(r["rainfall_af"]) for r in rows]
    # 500 x 60 / 304.8 and 400 x 30 / 304.8; rain 40 x 60 / 304.8 and 20 x 30 / 304.8.
    assert [c.quantize(D("0.01")) for c in crop] == [D("98.43"), D("39.37")]
    assert [r.quantize(D("0.01")) for r in rain] == [D("7.87"), D("1.97")]
    # The parts add to the figure the step booked.
    assert abs(sum(crop) - af) < D("0.0001")
    # 100 acres of outline, 90 in the two fields.
    assert D(record["detail"]["outside_acres"]) == D("10.00")


def test_the_stamped_rainfall_adds_to_the_rain_the_precip_step_counts():
    from accounting.steps import et_gross, subtract_effective_precip

    parcel, a, b = _sixty_thirty_july()
    _, gross = et_gross(D("0"), parcel, JULY, {}, {})
    _, rain = subtract_effective_precip(D("0"), parcel, JULY, {}, {"method": "usda_scs"})
    stamped = sum(D(r["rainfall_af"]) for r in _stamped(gross))
    # The receipt's Rainfall row: the step's precip_mm over the use area's acres.
    rainfall_af = D(rain["detail"]["precip_mm"]) * D(gross["detail"]["area_acres"]) / D("304.8")
    assert abs(stamped - rainfall_af) < D("0.0001")


def test_the_stamp_lists_the_recorded_fields_when_a_newer_figure_has_not_been_accepted():
    """A newer answer nobody accepted leaves the list as recorded."""
    from accounting.steps import et_gross

    parcel, a, b = _sixty_thirty_july()
    _, before = et_gross(D("0"), parcel, JULY, {}, {})
    _month(a, et_mm=550, pr_mm=40, received_on=LATER)
    _, after = et_gross(D("0"), parcel, JULY, {}, {})
    assert _stamped(before) and _stamped(after) == _stamped(before)


def test_no_stamp_for_a_use_area_with_no_share():
    from accounting.steps import et_gross

    parcel = _use_area()
    _, record = et_gross(D("0"), parcel, JULY, {}, {})
    assert _stamped(record) is None


def test_no_stamp_in_a_fallow_month():
    from accounting.steps import et_gross
    from parcels.models import FallowPeriod

    parcel, a, b = _sixty_thirty_july()
    FallowPeriod.objects.create(parcel=parcel, start_month=JULY_1)
    af, record = et_gross(D("0"), parcel, JULY, {}, {})
    assert af == 0
    assert _stamped(record) is None


def test_outside_acres_come_from_the_outline_never_the_typed_acres():
    """A typed acreage below the overlaps never prints a negative outside figure."""
    from accounting.steps import et_gross
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    Parcel.objects.filter(pk=parcel.pk).update(area_acres=D("50.00"), area_override=True)
    parcel.refresh_from_db()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=500, pr_mm=40)
    _month(b, et_mm=400, pr_mm=20)
    crop_et.record_fetched_months(parcel, [JULY])
    _, record = et_gross(D("0"), parcel, JULY, {}, {})
    assert record["detail"]["fields"]
    assert D(record["detail"]["outside_acres"]) == D("10.00")


def test_outside_acres_never_go_below_zero():
    """A use area wholly inside one field: the overlaps' rounding can pass the outline's acres."""
    from accounting.steps import et_gross
    from datasync import crop_et
    from datasync.field_list import compute_shares

    parcel = _use_area()
    whole = _field(MADE_UP_C, _albers_rect(-500, -500, SIDE + 500, SIDE + 500))
    compute_shares(parcel)
    _month(whole, et_mm=300, pr_mm=10)
    crop_et.record_fetched_months(parcel, [JULY])
    _, record = et_gross(D("0"), parcel, JULY, {}, {})
    assert D(record["detail"]["outside_acres"]) >= 0
