# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the offline dry-year generator.

The demonstration's second water year is fabricated, so nothing outside this
suite can contradict it. What these tests hold down is therefore not "is the
weather right" — it is a fabricated basin by ruling — but the four properties a
wrong answer would hide behind:

  - every item lands INSIDE its own row's span (F-math-03 / ISS-032: an item
    outside its span is skipped with a log line and reads downstream as zero),
  - every variable keys its value under its own name (only ``ET`` keys under
    ``et``; a wrong key is a silent zero, accounting/steps.py:36),
  - a re-run is byte-identical, which is the whole basis for treating
    ``git diff`` on the committed fixture as an honest answer,
  - the ``--precip-factor`` promise about the annual total is kept per parcel.
"""

import datetime as dt

import pytest
from django.core.management import call_command

from datasync.management.commands.synthesize_dry_year import (
    ET_WINTER_FLOOR,
    VARIABLE_KEYS,
)
from datasync.models import OpenETCache
from tests.factories import ParcelFactory

SOURCE_START = dt.date(2024, 10, 1)
SOURCE_END = dt.date(2025, 9, 30)
TARGET_START = dt.date(2025, 10, 1)
TARGET_END = dt.date(2026, 9, 30)

SOURCE_MONTHS = [
    "2024-10",
    "2024-11",
    "2024-12",
    "2025-01",
    "2025-02",
    "2025-03",
    "2025-04",
    "2025-05",
    "2025-06",
    "2025-07",
    "2025-08",
    "2025-09",
]

# Roughly the committed basin-mean shape, so the transform is exercised against
# a wet winter and a dry summer rather than against a flat twelve.
PRECIP_MM = [0.0, 37.0, 42.1, 45.6, 68.7, 78.9, 15.0, 0.0, 0.0, 0.0, 2.3, 5.4]
ET_MM = [50.4, 28.7, 19.8, 27.5, 44.3, 66.4, 97.8, 126.5, 116.9, 121.2, 118.2, 77.0]


def _values(variable, index):
    """One parcel's twelve monthly values for a variable, offset per parcel."""
    bump = 1.0 + index * 0.1  # per-parcel texture, so a flattening transform shows
    if variable == "precip":
        return [v * bump for v in PRECIP_MM]
    if variable == "ET":
        return [v * bump for v in ET_MM]
    if variable == "et_mad_min":
        return [v * bump * 0.72 for v in ET_MM]
    if variable == "et_mad_max":
        return [v * bump * 1.31 for v in ET_MM]
    return [5.0 + index for _ in ET_MM]  # model_count — not weather


@pytest.fixture
def source_window(db):
    """Two parcels, all five variables, twelve months — the real shape in small."""
    parcels = [
        ParcelFactory(parcel_number="MER-TEST-001"),
        ParcelFactory(parcel_number="MER-TEST-002"),
    ]
    for index, parcel in enumerate(parcels):
        for variable, (model_name, key) in VARIABLE_KEYS.items():
            values = _values(variable, index)
            OpenETCache.objects.create(
                parcel=parcel,
                geometry=parcel.geometry,
                start_date=SOURCE_START,
                end_date=SOURCE_END,
                variable=variable,
                model_name=model_name,
                et_data=[
                    {"date": month, key: value, "unit": "mm"}
                    for month, value in zip(SOURCE_MONTHS, values)
                ],
            )
    return parcels


def _target_rows():
    return OpenETCache.objects.filter(
        start_date=TARGET_START, end_date=TARGET_END
    ).order_by("parcel__parcel_number", "variable")


@pytest.mark.django_db
def test_writes_one_row_per_parcel_variable_in_the_target_window(source_window):
    """Five variables x two parcels land in the new window, and nowhere else."""
    call_command("synthesize_dry_year", prefix="MER-TEST-")

    assert _target_rows().count() == 10
    assert {row.variable for row in _target_rows()} == set(VARIABLE_KEYS)
    # The source window is untouched — this command derives, it does not move.
    assert (
        OpenETCache.objects.filter(
            start_date=SOURCE_START, end_date=SOURCE_END
        ).count()
        == 10
    )
    # No third window appeared.
    assert OpenETCache.objects.values("start_date", "end_date").distinct().count() == 2


@pytest.mark.django_db
def test_every_item_falls_inside_its_own_rows_span(source_window):
    """F-math-03 / ISS-032, asserted directly.

    ``_read_cache_mm`` skips an item dated outside its row's span and logs a
    warning. Downstream that is a zero, not an error, so the span property has
    to be tested rather than trusted.
    """
    call_command("synthesize_dry_year", prefix="MER-TEST-")

    for row in _target_rows():
        assert row.et_data, f"{row.variable} wrote no items"
        for item in row.et_data:
            first = dt.date(int(item["date"][:4]), int(item["date"][5:7]), 1)
            assert row.start_date <= first <= row.end_date, (
                f"{row.parcel.parcel_number} {row.variable} item {item['date']} "
                f"is outside {row.start_date}..{row.end_date}"
            )
        assert [item["date"] for item in row.et_data] == [
            "2025-10",
            "2025-11",
            "2025-12",
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
            "2026-08",
            "2026-09",
        ]


@pytest.mark.django_db
def test_each_variable_keys_its_value_under_its_own_name(source_window):
    """The silent-zero trap: only ``ET`` keys its items under ``et``."""
    call_command("synthesize_dry_year", prefix="MER-TEST-")

    for row in _target_rows():
        expected_key = VARIABLE_KEYS[row.variable][1]
        for item in row.et_data:
            assert expected_key in item, (
                f"{row.variable} item {item['date']} has no {expected_key!r} key — "
                "the engine would read this parcel-month as zero"
            )
            assert isinstance(item[expected_key], (int, float))


@pytest.mark.django_db
def test_a_second_run_produces_identical_payloads(source_window):
    """Determinism is the property the committed fixture's diff rests on."""
    call_command("synthesize_dry_year", prefix="MER-TEST-")
    first = {
        (row.parcel.parcel_number, row.variable): row.et_data for row in _target_rows()
    }

    call_command("synthesize_dry_year", prefix="MER-TEST-")
    second = {
        (row.parcel.parcel_number, row.variable): row.et_data for row in _target_rows()
    }

    assert first == second
    # An upsert on the uniqueness tuple, not a second set of rows.
    assert _target_rows().count() == 10


@pytest.mark.django_db
def test_model_count_is_carried_through_unchanged(source_window):
    """It counts contributing ET models, not weather."""
    call_command("synthesize_dry_year", prefix="MER-TEST-")

    for parcel_number in ("MER-TEST-001", "MER-TEST-002"):
        source = OpenETCache.objects.get(
            parcel__parcel_number=parcel_number,
            variable="model_count",
            start_date=SOURCE_START,
        )
        target = OpenETCache.objects.get(
            parcel__parcel_number=parcel_number,
            variable="model_count",
            start_date=TARGET_START,
        )
        assert [item["model_count"] for item in target.et_data] == pytest.approx(
            [item["model_count"] for item in source.et_data]
        )


@pytest.mark.django_db
def test_annual_precip_lands_on_the_factor_for_every_parcel(source_window):
    """``--precip-factor`` is a promise about each parcel's annual total."""
    factor = 0.5
    call_command("synthesize_dry_year", prefix="MER-TEST-", precip_factor=str(factor))

    for parcel_number in ("MER-TEST-001", "MER-TEST-002"):
        source = OpenETCache.objects.get(
            parcel__parcel_number=parcel_number,
            variable="precip",
            start_date=SOURCE_START,
        )
        target = OpenETCache.objects.get(
            parcel__parcel_number=parcel_number,
            variable="precip",
            start_date=TARGET_START,
        )
        committed = sum(item["precip"] for item in source.et_data)
        dry = sum(item["precip"] for item in target.et_data)
        assert abs(dry - committed * factor) < 0.5, (
            f"{parcel_number}: {dry:.3f} mm against a target of "
            f"{committed * factor:.3f} mm"
        )
        # And the shape moved, not just the level: the peak storm months take a
        # deeper cut than the shoulders, which is what makes it read as dry.
        feb_ratio = target.et_data[4]["precip"] / source.et_data[4]["precip"]
        nov_ratio = target.et_data[1]["precip"] / source.et_data[1]["precip"]
        assert feb_ratio < nov_ratio


@pytest.mark.django_db
def test_growing_season_et_holds_and_winter_et_follows_the_rain(source_window):
    """The physical claim in the docstring, held down where it can drift."""
    call_command("synthesize_dry_year", prefix="MER-TEST-")

    source = OpenETCache.objects.get(
        parcel__parcel_number="MER-TEST-001", variable="ET", start_date=SOURCE_START
    )
    target = OpenETCache.objects.get(
        parcel__parcel_number="MER-TEST-001", variable="ET", start_date=TARGET_START
    )
    by_index = list(zip(source.et_data, target.et_data))

    # Apr-Sep (indices 6-11) and the Oct/Mar transitions (0 and 5) are untouched.
    for index in (0, 5, 6, 7, 8, 9, 10, 11):
        assert target.et_data[index]["et"] == pytest.approx(
            source.et_data[index]["et"]
        ), f"month index {index} should have been carried through unchanged"

    # Nov-Feb (indices 1-4) fall, and never below the floor.
    for index in (1, 2, 3, 4):
        old = by_index[index][0]["et"]
        new = by_index[index][1]["et"]
        assert new < old
        assert new >= old * float(ET_WINTER_FLOOR) - 1e-6


@pytest.mark.django_db
def test_dry_run_writes_nothing(source_window):
    call_command("synthesize_dry_year", prefix="MER-TEST-", dry_run=True)
    assert _target_rows().count() == 0
