# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every water year of a right set against its face value (150-02 Task 5).

``surface.face_value.years_against_face_value`` reads the water-year groups
``surface.views._group_diversion_records`` builds from a right's records. The
fixture, worked by hand once:

    Face value 100.00 AF.
    WY 2023-2024: January 70.00 typed, February 50.00 estimated from use.
        recorded 70.00, estimated 50.00, total 120.00;
        120.00 - 100.00 = 20.00 over its face value; 1 of 2 months estimated.
    WY 2024-2025: January 80.00 typed.
        recorded 80.00, estimated 0.00, total 80.00;
        100.00 - 80.00 = 20.00 remaining.

Every expected figure below is that pasted literal, never the function's own
arithmetic run a second time (DESIGN.md rule 12).
"""
from datetime import date
from decimal import Decimal

import pytest

from surface.face_value import years_against_face_value
from surface.models import DiversionRecord
from surface.views import _group_diversion_records
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
)

pytestmark = pytest.mark.django_db


def _right_with_two_years(face_value=Decimal("100.0000")):
    right = WaterRightFactory(face_value_acre_feet=face_value)
    pod = PointOfDiversionFactory(water_right=right, name="Alder Ditch Headgate")
    wy2024 = ReportingPeriodFactory(
        name="WY 2023-2024", start_date=date(2023, 10, 1), end_date=date(2024, 9, 30)
    )
    wy2025 = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=wy2024, month=date(2024, 1, 1),
        volume_acre_feet=Decimal("70.0000"), method="methodology",
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=wy2024, month=date(2024, 2, 1),
        volume_acre_feet=Decimal("50.0000"), method="estimated_from_use",
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=wy2025, month=date(2025, 1, 1),
        volume_acre_feet=Decimal("80.0000"),
    )
    return right


def _years(right):
    records = list(
        DiversionRecord.objects.filter(point_of_diversion__water_right=right)
        .select_related("point_of_diversion", "reporting_period")
        .order_by("-month", "point_of_diversion__name")
    )
    return years_against_face_value(right, _group_diversion_records(records))


def test_a_year_past_its_face_value_is_over_by_the_difference_and_one_under_it_has_the_rest():
    right = _right_with_two_years()

    newer, older = _years(right)

    assert newer["period_name"] == "WY 2024-2025"
    assert newer["recorded_af"] == Decimal("80.0000")
    assert newer["estimated_af"] == Decimal("0.0000")
    assert newer["total_af"] == Decimal("80.0000")
    assert newer["months"] == 1
    assert newer["months_estimated"] == 0
    assert newer["record_count"] == 1
    assert newer["over_by_af"] is None
    assert newer["remaining_af"] == Decimal("20.0000")

    assert older["period_name"] == "WY 2023-2024"
    assert older["recorded_af"] == Decimal("70.0000")
    assert older["estimated_af"] == Decimal("50.0000")
    assert older["total_af"] == Decimal("120.0000")
    assert older["months"] == 2
    assert older["months_estimated"] == 1
    assert older["record_count"] == 2
    assert older["over_by_af"] == Decimal("20.0000")
    assert older["remaining_af"] is None


def test_only_the_year_past_its_face_value_is_flagged():
    right = _right_with_two_years()

    flagged = [row["period_name"] for row in _years(right) if row["over_by_af"] is not None]

    assert flagged == ["WY 2023-2024"]


def test_a_year_exactly_at_its_face_value_has_nothing_remaining_and_is_not_over():
    right = _right_with_two_years(face_value=Decimal("120.0000"))

    _newer, older = _years(right)

    assert older["over_by_af"] is None
    assert older["remaining_af"] == Decimal("0.0000")


def test_a_right_with_no_face_value_is_never_over_and_has_nothing_remaining():
    right = _right_with_two_years(face_value=None)

    rows = _years(right)

    assert [(r["over_by_af"], r["remaining_af"]) for r in rows] == [(None, None), (None, None)]
    assert [r["total_af"] for r in rows] == [Decimal("80.0000"), Decimal("120.0000")]


def test_a_right_with_no_records_has_no_years():
    right = WaterRightFactory(face_value_acre_feet=Decimal("100.0000"))

    assert _years(right) == []
