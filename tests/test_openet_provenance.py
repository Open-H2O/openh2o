# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the demonstration's crop ET and rainfall come from, and when they arrived.

The demonstration's figures are labelled OpenET and gridMET on every page that
shows them, so every figure in ``data/merced/openet_cache.json`` must be one
those services sent. These tests hold four things:

* every row of the committed file names its source and the day it was received;
* no water year in it is derived from the other (a copy, a multiple, or the same
  shape bent the same way across fields), and the command that derived one is
  gone;
* the dump writes the received day and the source, and refuses a row that does
  not carry a received day rather than inventing one;
* the load gives each item, and so each recorded crop ET month, that day, and
  every writer of these rows marks how it came to exist.
"""

import datetime as dt
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.utils import timezone

from datasync.models import CropETFigure, OpenETCache

FIXTURE = Path("data/merced/openet_cache.json")
SOURCE_OF_MODEL = {"Ensemble": "OpenET", "GRIDMET": "gridMET"}
VALUE_KEY = {"ET": "et", "precip": "precip"}
RECEIVED = dt.date(2026, 11, 12)


def _committed_rows():
    return json.loads(FIXTURE.read_text())["rows"]


def _month_end(month):
    year, number = int(month[:4]), int(month[5:7])
    following = dt.date(year + (number == 12), number % 12 + 1, 1)
    return following - dt.timedelta(days=1)


# -- The committed file --------------------------------------------------------------------


def test_every_committed_row_names_its_source_and_the_day_it_was_received():
    rows = _committed_rows()
    assert rows
    missing = [
        (row["parcel_number"], row["variable"], row["start_date"])
        for row in rows
        if "received" not in row or "source" not in row
    ]
    assert missing == [], f"{len(missing)} rows carry no received day or source, first {missing[:3]}"

    for row in rows:
        assert row["source"] == SOURCE_OF_MODEL[row["model_name"]], row["parcel_number"]
        received = dt.date.fromisoformat(row["received"])
        last_month = max(item["date"] for item in row["et_data"])
        # A figure cannot arrive before the month it describes has ended.
        assert received > _month_end(last_month), (row["parcel_number"], row["variable"], last_month)
        # One day per row, stated once: no item carries a day of its own.
        assert all("fetched" not in item for item in row["et_data"])


def _monthly(variable):
    """``{use area: {"YYYY-MM": value}}`` for one variable of the committed file."""
    key = VALUE_KEY[variable]
    values = defaultdict(dict)
    for row in _committed_rows():
        if row["variable"] != variable:
            continue
        for item in row["et_data"]:
            if item.get(key) is not None:
                values[row["parcel_number"]][item["date"]] = float(item[key])
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


@pytest.mark.parametrize("variable", ["ET", "precip"])
def test_no_open_year_month_is_a_copy_of_the_closed_year(variable):
    copies = []
    for area, months in _monthly(variable).items():
        for month, value in months.items():
            if month < "2025-10" or not value:
                continue
            prior = months.get(f"{int(month[:4]) - 1}-{month[5:]}")
            if prior is not None and abs(value - prior) <= 1e-6:
                copies.append((area, month))
    assert copies == [], f"{len(copies)} open-year months copy the closed year, first {copies[:5]}"


@pytest.mark.parametrize("variable", ["ET", "precip"])
def test_no_open_year_is_a_multiple_of_the_closed_year(variable):
    scaled = []
    for area, months in _monthly(variable).items():
        ratios = list(_open_to_closed(months).values())
        if len(ratios) > 1 and max(ratios) - min(ratios) <= 1e-6:
            scaled.append(area)
    assert scaled == [], f"{len(scaled)} use areas' open year is a multiple of the closed year: {scaled[:5]}"


@pytest.mark.parametrize("variable", ["ET", "precip"])
def test_no_two_use_areas_share_one_open_year_shape(variable):
    """Fields with different closed years cannot bend into the same open year.

    gridMET's grid gives neighbouring fields the same rainfall, so fields whose
    closed years are identical are left out of the comparison: only a shape that
    repeats across DIFFERENT closed years is the mark of a rule applied to them.
    """
    shapes = defaultdict(dict)
    for months in _monthly(variable).values():
        ratios = _open_to_closed(months)
        if len(ratios) < 2:
            continue
        mean = sum(ratios.values()) / len(ratios)
        closed = tuple(round(months[m], 6) for m in sorted(months) if m < "2025-10")
        shape = tuple(round(ratios[m] / mean, 6) for m in sorted(ratios))
        shapes[tuple(sorted(ratios))][closed] = shape
    repeats = sum(len(group) - len(set(group.values())) for group in shapes.values())
    assert repeats == 0, f"{repeats} use areas share an open-year shape with a different field"


DEMONSTRATION_MONTHS = [
    f"{2024 + (month + 9) // 12}-{(month + 9) % 12 + 1:02d}" for month in range(24)
]


def test_every_use_area_has_crop_et_for_all_24_months():
    """October 2024 to September 2026, every month of every use area.

    Earth Engine's record had no crop ET for 61 use areas in December 2025 and 46
    in January 2026 (cloud). OpenET's own service sends a figure for those months
    (ruling 146), so no month of the demonstration is without one.
    """
    monthly = _monthly("ET")
    assert len(monthly) == 76
    absent = [
        (area, month)
        for area, months in sorted(monthly.items())
        for month in DEMONSTRATION_MONTHS
        if month not in months
    ]
    assert absent == [], f"{len(absent)} use-area months have no crop ET, first {absent[:5]}"


def test_the_cloud_months_are_openets_received_nov_12_2026_in_the_years_own_row():
    """Each use area's December 2025 and January 2026 crop ET sits in its one row for
    WY 2025-26, which names OpenET and the day it was received.

    One row per use area and water year: a second row over the same months would
    read on Site Health as two OpenET estimates for one month.
    """
    found = defaultdict(list)
    for row in _committed_rows():
        if row["variable"] != "ET":
            continue
        for item in row["et_data"]:
            if item["date"] in ("2025-12", "2026-01") and item.get("et") is not None:
                found[(row["parcel_number"], item["date"])].append(
                    (row["start_date"], row["end_date"], row["source"], row["received"], item["unit"])
                )
    areas = {row["parcel_number"] for row in _committed_rows()}
    expected = {(area, month) for area in areas for month in ("2025-12", "2026-01")}
    assert set(found) == expected, f"{len(expected - set(found))} cloud months have no figure"
    wrong = {
        key: places
        for key, places in found.items()
        if places != [("2025-10-01", "2026-09-30", "OpenET", "2026-11-12", "mm")]
    }
    assert wrong == {}, f"{len(wrong)} cloud months sit elsewhere, first {list(wrong.items())[:3]}"


def test_the_cloud_months_are_the_figures_openets_service_sent():
    """Two fields, as OpenET's service answered them on 2026-11-12 (mm, three decimals)."""
    monthly = _monthly("ET")
    assert monthly["MER-APN-001"]["2025-12"] == 37.142
    assert monthly["MER-APN-001"]["2026-01"] == 35.834
    assert monthly["MER-APN-003"]["2025-12"] == 27.803
    assert monthly["MER-APN-003"]["2026-01"] == 40.467


def test_the_command_that_derived_a_year_is_gone():
    name = "synthesize_dry_year"
    assert importlib.util.find_spec(f"datasync.management.commands.{name}") is None
    assert name not in get_commands()


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
