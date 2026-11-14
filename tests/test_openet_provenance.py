# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the demonstration's crop ET and rain come from, and when they arrived.

The demonstration's figures are labelled OpenET on every page that shows them, so every
figure in ``data/merced/openet_fields.json`` must be one OpenET's field list sent. These
tests hold four things:

* the committed file names its source, carries each field's outline as OpenET's field list
  sent it (ruling 166), and every field and month row carries the day it was received,
  after the month ended;
* every use area takes its crop ET and rain from at least one OpenET field, and every such
  field has crop ET and rain for all 24 months, figures as OpenET's field list sent them;
* no water year in it is derived from the other (a copy, a multiple, or the same shape bent
  the same way across fields), and the command that derived one is gone;
* the older routes' dump and load still write and keep the received day and the source.
"""

import datetime as dt
import importlib.util
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.utils import timezone

from datasync.models import CropETFigure, OpenETCache

FIXTURE = Path("data/merced/openet_fields.json")
OLD_FIXTURE = Path("data/merced/openet_cache.json")
#: The day OpenET's field list answered the demonstration's figures request (Pacific).
FIELD_LIST_RECEIVED = "2026-11-14"
RECEIVED = dt.date(2026, 11, 12)

DEMONSTRATION_MONTHS = [
    f"{2024 + (month + 9) // 12}-{(month + 9) % 12 + 1:02d}" for month in range(24)
]


def _committed():
    return json.loads(FIXTURE.read_text())


def _month_end(month):
    year, number = int(month[:4]), int(month[5:7])
    following = dt.date(year + (number == 12), number % 12 + 1, 1)
    return following - dt.timedelta(days=1)


# -- The committed file --------------------------------------------------------------------


def test_the_earth_engine_file_is_gone():
    """The demonstration no longer loads Earth Engine's figures; git history keeps the file."""
    assert not OLD_FIXTURE.exists()


def test_the_file_names_openets_field_list_and_carries_no_stamp():
    payload = _committed()
    assert payload["meta"]["source"] == "OpenET's field list (https://etdata.org)"
    assert payload["meta"]["received"] == FIELD_LIST_RECEIVED
    raw = FIXTURE.read_text()
    # No stamp of any kind, or every regeneration reads as a change.
    for banned in ("generated_at", "timestamp", "hostname", "git_hash"):
        assert banned not in raw


def test_every_field_carries_its_outline_and_its_acres_are_the_outlines():
    """78 of 78 fields carry OpenET's outline; each field's acres are its outline's, to 0.5%."""
    from django.contrib.gis.geos import GEOSGeometry

    from datasync.field_list import outline_acres

    payload = _committed()
    assert len(payload["fields"]) == 78
    off = []
    for row in payload["fields"]:
        outline = row["outline"]
        assert outline["type"] in ("Polygon", "MultiPolygon")
        geometry = GEOSGeometry(json.dumps(outline), srid=4326)
        measured = outline_acres(geometry)
        stored = Decimal(row["area_acres"])
        if abs(measured - stored) > stored * Decimal("0.005"):
            off.append((row["field_id"], stored, measured))
    assert off == []


def test_the_outlines_keep_openets_six_decimals():
    """Coordinates as OpenET sent them: none carries more than six decimals."""
    import re

    for row in _committed()["fields"]:
        text = json.dumps(row["outline"])
        assert max(len(d) for d in re.findall(r"\.(\d+)", text)) <= 6, row["field_id"]


def test_every_row_carries_the_day_it_was_received_after_its_month_ended():
    payload = _committed()
    assert all(row["received_on"] == FIELD_LIST_RECEIVED for row in payload["fields"])
    late = [
        (row["field_id"], row["month"])
        for row in payload["months"]
        if dt.date.fromisoformat(row["received_on"]) <= _month_end(row["month"][:7])
    ]
    assert late == []


def test_the_counts_the_file_states_are_the_rows_it_holds():
    payload = _committed()
    meta = payload["meta"]
    assert meta["field_count"] == len(payload["fields"]) == 78
    assert meta["share_count"] == len(payload["shares"]) == 84
    assert meta["month_count"] == len(payload["months"]) == 78 * 24


def test_every_use_area_takes_its_figures_from_at_least_one_openet_field():
    payload = _committed()
    areas = {row["parcel_number"] for row in payload["shares"]}
    assert len(areas) == 76
    listed = {row["field_id"] for row in payload["fields"]}
    assert {row["field_id"] for row in payload["shares"]} == listed
    assert all(Decimal(row["overlap_acres"]) > 0 for row in payload["shares"])


def test_every_field_has_crop_et_and_rain_for_all_24_months():
    payload = _committed()
    have = defaultdict(set)
    for row in payload["months"]:
        if row["et_mm"] is not None and row["pr_mm"] is not None:
            have[row["field_id"]].add(row["month"][:7])
    absent = [
        (row["field_id"], month)
        for row in payload["fields"]
        for month in DEMONSTRATION_MONTHS
        if month not in have[row["field_id"]]
    ]
    assert absent == [], f"{len(absent)} field-months have no figure, first {absent[:5]}"


def test_figures_are_as_openets_field_list_sent_them():
    """Three of OpenET's answers, character for character (mm)."""
    months = {(row["field_id"], row["month"][:7]): row for row in _committed()["months"]}
    assert months[(21106403648, "2025-12")]["et_mm"] == "25.967"
    assert months[(21106403648, "2025-12")]["pr_mm"] == "48.359"
    assert months[(21106398638, "2025-12")]["et_mm"] == "22.408285714285714"


def _monthly(key):
    """``{field: {"YYYY-MM": value}}`` for crop ET ("et_mm") or rain ("pr_mm")."""
    values = defaultdict(dict)
    for row in _committed()["months"]:
        if row[key] is not None:
            values[row["field_id"]][row["month"][:7]] = float(row[key])
    return values


def _open_to_closed(months):
    """``{"MM": open-year value / closed-year value}`` where both are non-zero."""
    ratios = {}
    for month, value in months.items():
        if month < "2025-10":
            continue
        prior = f"{int(month[:4]) - 1}-{month[5:]}"
        if months.get(prior) and value:
            ratios[month[5:]] = value / months[prior]
    return ratios


@pytest.mark.parametrize("key", ["et_mm", "pr_mm"])
def test_no_open_year_month_is_a_copy_of_the_closed_year(key):
    copies = []
    for field, months in _monthly(key).items():
        for month, value in months.items():
            if month < "2025-10" or not value:
                continue
            prior = months.get(f"{int(month[:4]) - 1}-{month[5:]}")
            if prior is not None and abs(value - prior) <= 1e-6:
                copies.append((field, month))
    assert copies == [], f"{len(copies)} open-year months copy the closed year, first {copies[:5]}"


@pytest.mark.parametrize("key", ["et_mm", "pr_mm"])
def test_no_open_year_is_a_multiple_of_the_closed_year(key):
    scaled = []
    for field, months in _monthly(key).items():
        ratios = list(_open_to_closed(months).values())
        if len(ratios) > 1 and max(ratios) - min(ratios) <= 1e-6:
            scaled.append(field)
    assert scaled == [], f"{len(scaled)} fields' open year is a multiple of the closed year: {scaled[:5]}"


@pytest.mark.parametrize("key", ["et_mm", "pr_mm"])
def test_no_two_fields_share_one_open_year_shape(key):
    """Fields with different closed years cannot bend into the same open year.

    gridMET's grid gives neighbouring fields the same rainfall, so fields whose closed
    years are identical are left out of the comparison: only a shape that repeats across
    DIFFERENT closed years is the mark of a rule applied to them.
    """
    shapes = defaultdict(dict)
    for months in _monthly(key).values():
        ratios = _open_to_closed(months)
        if len(ratios) < 2:
            continue
        mean = sum(ratios.values()) / len(ratios)
        closed = tuple(round(months[m], 6) for m in sorted(months) if m < "2025-10")
        shape = tuple(round(ratios[m] / mean, 6) for m in sorted(ratios))
        shapes[tuple(sorted(ratios))][closed] = shape
    repeats = sum(len(group) - len(set(group.values())) for group in shapes.values())
    assert repeats == 0, f"{repeats} fields share an open-year shape with a different field"


def test_the_command_that_derived_a_year_is_gone():
    name = "synthesize_dry_year"
    assert importlib.util.find_spec(f"datasync.management.commands.{name}") is None
    assert name not in get_commands()


def test_the_load_records_each_use_areas_months_on_the_day_received(db, tmp_path):
    """A made-up use area and a made-up field (99000000021): the loader records the months."""
    from parcels.models import Parcel

    Parcel.objects.create(
        parcel_number="MADEUP-PROV-LOAD",
        geometry=MultiPolygon(Polygon.from_bbox((-120.5, 37.2, -120.4, 37.3)), srid=4326),
        area_acres=10,
        status="active",
    )
    made_up = {
        "meta": {"source": "made up for this test"},
        "fields": [{"field_id": 99000000021, "area_acres": "10.00", "received_on": "2025-12-01"}],
        "shares": [{"parcel_number": "MADEUP-PROV-LOAD", "field_id": 99000000021, "overlap_acres": "10.00"}],
        "months": [{"field_id": 99000000021, "month": "2025-10", "et_mm": "30.48", "pr_mm": "1.0",
                    "received_on": "2025-12-01"}],
    }
    path = tmp_path / "made_up_fields.json"
    path.write_text(json.dumps(made_up))
    call_command("load_openet_fields_fixture", "--fixture", str(path), stdout=None)
    (figure,) = CropETFigure.objects.filter(parcel__parcel_number="MADEUP-PROV-LOAD")
    assert figure.month == dt.date(2025, 10, 1)
    assert figure.depth_mm == Decimal("30.48")
    assert figure.fetched_on == dt.date(2025, 12, 1)


@pytest.mark.parametrize("broken", ["no_day", "early", "unknown_area"])
def test_the_fields_load_refuses_a_row_it_cannot_prove_and_writes_nothing(db, tmp_path, broken):
    from datasync.models import OpenETField
    from parcels.models import Parcel

    Parcel.objects.create(parcel_number="MADEUP-PROV-HERE", area_acres=10, status="active")
    area = "MADEUP-NOT-HERE" if broken == "unknown_area" else "MADEUP-PROV-HERE"
    made_up = {
        "fields": [{"field_id": 99000000022, "area_acres": "10.00", "received_on": "2025-12-01"}],
        "shares": [{"parcel_number": area, "field_id": 99000000022, "overlap_acres": "1.00"}],
        "months": [{"field_id": 99000000022, "month": "2025-10", "et_mm": "1", "pr_mm": "1",
                    "received_on": {"no_day": None, "early": "2025-10-15", "unknown_area": "2025-12-01"}[broken]}],
    }
    path = tmp_path / "made_up_fields.json"
    path.write_text(json.dumps(made_up))
    with pytest.raises(CommandError):
        call_command("load_openet_fields_fixture", "--fixture", str(path))
    assert not OpenETField.objects.exists()


# -- The dump --------------------------------------------------------------------------------


@pytest.fixture
def area(db):
    from parcels.models import Parcel

    return Parcel.objects.create(
        parcel_number="MER-PROV-001",
        geometry=MultiPolygon(Polygon.from_bbox((-120.5, 37.2, -120.4, 37.3)), srid=4326),
        area_acres=10,
        status="active",
    )


def _cache(area, variable, model, items):
    return OpenETCache.objects.create(
        parcel=area,
        geometry=area.geometry,
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
        variable=variable,
        model_name=model,
        et_data=items,
    )


def _stamped(items, day=RECEIVED):
    return [{**item, "fetched": day.isoformat()} for item in items]


ET_ITEMS = [{"date": "2025-10", "et": 84.1, "unit": "mm"}, {"date": "2025-11", "et": 38.5, "unit": "mm"}]
RAIN_ITEMS = [{"date": "2025-10", "precip": 0.0, "unit": "mm"}, {"date": "2025-11", "precip": 34.4, "unit": "mm"}]


@pytest.mark.django_db
def test_the_dump_writes_the_received_day_and_the_source(area, tmp_path):
    _cache(area, "ET", "Ensemble", _stamped(ET_ITEMS))
    _cache(area, "precip", "GRIDMET", _stamped(RAIN_ITEMS))
    out = tmp_path / "cache.json"

    call_command("dump_openet_fixture", output=str(out), prefix="MER-PROV-")

    rows = {row["variable"]: row for row in json.loads(out.read_text())["rows"]}
    assert rows["ET"]["received"] == "2026-11-12"
    assert rows["ET"]["source"] == "OpenET"
    assert rows["precip"]["received"] == "2026-11-12"
    assert rows["precip"]["source"] == "gridMET"
    assert rows["ET"]["et_data"] == ET_ITEMS


@pytest.mark.django_db
def test_the_dump_refuses_a_row_with_no_received_day_and_writes_nothing(area, tmp_path):
    _cache(area, "ET", "Ensemble", _stamped(ET_ITEMS))
    _cache(area, "precip", "GRIDMET", RAIN_ITEMS)
    out = tmp_path / "cache.json"

    with pytest.raises(CommandError, match="MER-PROV-001"):
        call_command("dump_openet_fixture", output=str(out), prefix="MER-PROV-")
    assert not out.exists()


@pytest.mark.django_db
def test_the_dump_refuses_a_row_received_on_two_days(area, tmp_path):
    items = [_stamped(ET_ITEMS[:1])[0], _stamped(ET_ITEMS[1:], dt.date(2026, 11, 13))[0]]
    _cache(area, "ET", "Ensemble", items)
    out = tmp_path / "cache.json"

    with pytest.raises(CommandError, match="MER-PROV-001"):
        call_command("dump_openet_fixture", output=str(out), prefix="MER-PROV-")
    assert not out.exists()


# -- The load --------------------------------------------------------------------------------


def _file(tmp_path, rows):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"meta": {}, "rows": rows}))
    return path


def _row(**changes):
    row = {
        "parcel_number": "MER-PROV-001",
        "start_date": "2025-10-01",
        "end_date": "2026-09-30",
        "variable": "ET",
        "model_name": "Ensemble",
        "et_data": ET_ITEMS,
        "received": "2026-11-12",
        "source": "OpenET",
    }
    row.update(changes)
    return {key: value for key, value in row.items() if value is not None}


@pytest.mark.django_db
def test_the_load_gives_each_month_its_received_day(area, tmp_path):
    call_command("load_openet_fixture", fixture=str(_file(tmp_path, [_row()])))

    row = OpenETCache.objects.get(parcel=area, variable="ET")
    assert [item["fetched"] for item in row.et_data] == ["2026-11-12", "2026-11-12"]
    assert row.origin == "fixture"
    figures = CropETFigure.objects.filter(parcel=area).order_by("month")
    assert [(f.month, f.fetched_on) for f in figures] == [
        (dt.date(2025, 10, 1), RECEIVED),
        (dt.date(2025, 11, 1), RECEIVED),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "broken",
    [{"received": None}, {"source": None}, {"source": "gridMET"}, {"received": "2025-11-15"}],
    ids=["no-received-day", "no-source", "wrong-source", "received-before-the-month-ended"],
)
def test_the_load_refuses_a_row_without_its_provenance_and_writes_nothing(area, tmp_path, broken):
    rows = [_row(variable="precip", model_name="GRIDMET", et_data=RAIN_ITEMS, source="gridMET"), _row(**broken)]

    with pytest.raises(CommandError, match="MER-PROV-001"):
        call_command("load_openet_fixture", fixture=str(_file(tmp_path, rows)))
    assert OpenETCache.objects.count() == 0
    assert CropETFigure.objects.count() == 0


# -- The writers -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_earth_engine_rows_say_so_and_carry_their_day(area):
    from datasync.adapters.openet_gee import GEEOpenETAdapter

    spread = {
        area.pk: {
            "2025-10": {
                "et_ensemble_mad": 84.1,
                "et_ensemble_mad_min": 70.2,
                "et_ensemble_mad_max": 99.0,
                "et_ensemble_mad_count": 6,
            }
        }
    }
    with patch("datasync.adapters.openet_gee.init_earth_engine", return_value=MagicMock()), patch(
        "datasync.adapters.openet_gee.reduce_et_by_parcel", return_value={area.pk: {"2025-10": 84.1}}
    ), patch("datasync.adapters.openet_gee.reduce_et_with_spread_by_parcel", return_value=spread):
        GEEOpenETAdapter().sync_parcel_et(
            [area], dt.date(2025, 10, 1), dt.date(2025, 10, 31), today=dt.date(2025, 11, 20)
        )

    rows = list(OpenETCache.objects.filter(parcel=area))
    assert {row.variable for row in rows} == {"ET", "et_mad_min", "et_mad_max", "model_count"}
    today = timezone.localdate().isoformat()
    for row in rows:
        assert row.origin == "gee", row.variable
        assert [item["fetched"] for item in row.et_data] == [today], row.variable


@pytest.mark.django_db
def test_rainfall_rows_say_so_and_carry_their_day(area):
    with patch(
        "datasync.management.commands.sync_precip_parcels.init_earth_engine", return_value=MagicMock()
    ), patch(
        "datasync.management.commands.sync_precip_parcels.reduce_precip_by_parcel",
        return_value={area.pk: {"2025-10": 0.0, "2025-11": 34.4}},
    ):
        call_command(
            "sync_precip_parcels", start_date="2025-10-01", end_date="2025-11-30", parcel_prefix="MER-PROV-"
        )

    row = OpenETCache.objects.get(parcel=area, variable="precip")
    assert row.origin == "gee"
    today = timezone.localdate().isoformat()
    assert [item["fetched"] for item in row.et_data] == [today, today]


@pytest.mark.django_db
def test_openet_spread_rows_carry_their_day(area):
    from datasync.adapters.openet import OpenETAdapter

    adapter = OpenETAdapter()
    with patch.object(adapter, "fetch_polygon", return_value=[{"time": "2025-10", "et_mad_max": 99.0}]):
        adapter.sync_spread_variable(area, dt.date(2025, 10, 1), dt.date(2025, 10, 31), "et_mad_max")

    row = OpenETCache.objects.get(parcel=area, variable="et_mad_max")
    assert row.origin == "api"
    assert [item["fetched"] for item in row.et_data] == [timezone.localdate().isoformat()]
