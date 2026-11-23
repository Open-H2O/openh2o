# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the part left after rounding goes when one supply is divided among use areas.

A headgate's delivery divided by shares (or by acreage where no shares are entered) gives each
use area its exact part of the delivery, rounded to four places. The few ten-thousandths of an
acre-foot that rounding leaves go to the use area with the largest part; between equal parts, to
the lower parcel number. The same rule places the leftover of the shares themselves.

Before this rule, each share was rounded to four places first and the delivery multiplied by the
rounded shares, and the whole gap went to the use area whose database id sorted last as text. A
share gap of 0.0002 on a 687 acre-foot delivery put 0.13 acre-feet on one use area, and loading the
same records again with other ids could move it to another.
"""
from decimal import Decimal

import pytest

from accounting.allocation_math import apportion_shared_supply
from surface.services import _fraction_rows
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
)


def _sum(d):
    return sum(d.values(), Decimal("0"))


def test_the_shares_leftover_goes_to_the_largest_share():
    # 3 : 1 : 1 : 1 -> 0.5, 0.1667 x 3 = 1.0001; the -0.0001 comes off the largest, A.
    got = apportion_shared_supply(
        [
            ("A", Decimal("1.0"), Decimal("3")),
            ("B", Decimal("1.0"), Decimal("1")),
            ("C", Decimal("1.0"), Decimal("1")),
            ("D", Decimal("1.0"), Decimal("1")),
        ]
    )
    assert got == {
        "A": Decimal("0.4999"),
        "B": Decimal("0.1667"),
        "C": Decimal("0.1667"),
        "D": Decimal("0.1667"),
    }, f"got {got}"
    assert _sum(got) == Decimal("1.0000")


def test_between_equal_shares_the_leftover_goes_to_the_first_in_order():
    # Three equal shares: 0.3333 x 3 = 0.9999; the 0.0001 goes to the lowest key, A.
    got = apportion_shared_supply(
        [
            ("C", Decimal("1.0"), Decimal("1")),
            ("A", Decimal("1.0"), Decimal("1")),
            ("B", Decimal("1.0"), Decimal("1")),
        ]
    )
    assert got == {"A": Decimal("0.3334"), "B": Decimal("0.3333"), "C": Decimal("0.3333")}, f"got {got}"


def _headgate(numbers_in_load_order, acres, delivery):
    """A headgate serving one use area per parcel number, created in the order given."""
    pod = PointOfDiversionFactory()
    links = []
    for number, area in zip(numbers_in_load_order, acres):
        parcel = ParcelFactory(parcel_number=number, area_acres=area)
        links.append(PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel))
    record = DiversionRecordFactory(point_of_diversion=pod, volume_acre_feet=Decimal(delivery))
    return record, links, pod


def _amounts(record, links, pod):
    rows = _fraction_rows(record, links, pod, None)
    return {row.parcel.parcel_number: -row.amount_acre_feet for row in rows}


@pytest.mark.django_db
def test_each_use_area_gets_its_exact_part_of_a_large_delivery():
    # 18 equal use areas on 687.2161 AF: each exact part is 38.17867.., so each row is 38.1787
    # and the -0.0005 rounding leaves comes off the first parcel number. Rounding the shares
    # first (1/18 -> 0.0556) put -0.0008 of the shares, about half an acre-foot, on one row.
    numbers = [f"LEFT-{n:02d}" for n in range(1, 19)]
    record, links, pod = _headgate(numbers, [Decimal("40.00")] * 18, "687.2161")
    got = _amounts(record, links, pod)
    assert _sum(got) == Decimal("687.2161")
    assert got["LEFT-01"] == Decimal("38.1782"), f"got {got}"
    assert all(got[n] == Decimal("38.1787") for n in numbers[1:]), f"got {got}"


@pytest.mark.django_db
def test_the_delivery_leftover_goes_to_the_largest_part():
    # 2 AF over 10 : 10 : 10 : 30 acres: exact parts 0.33333.. x 3 and 1.0, rounded
    # 0.3333 x 3 + 1.0000 = 1.9999; the 0.0001 goes to the largest part, LEFT-D.
    record, links, pod = _headgate(
        ["LEFT-A", "LEFT-B", "LEFT-C", "LEFT-D"],
        [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("30")],
        "2.0000",
    )
    got = _amounts(record, links, pod)
    assert got == {
        "LEFT-A": Decimal("0.3333"),
        "LEFT-B": Decimal("0.3333"),
        "LEFT-C": Decimal("0.3333"),
        "LEFT-D": Decimal("1.0001"),
    }, f"got {got}"


@pytest.mark.django_db
def test_the_same_records_loaded_in_another_order_give_the_same_rows():
    # Three equal use areas on 100 AF: 33.3333 x 3 = 99.9999; the 0.0001 goes to the lowest
    # parcel number, however the records were loaded and whatever their ids.
    first = _amounts(*_headgate(["LEFT-1", "LEFT-2", "LEFT-3"], [Decimal("20")] * 3, "100.0000"))
    second = _amounts(*_headgate(["MORE-3", "MORE-2", "MORE-1"], [Decimal("20")] * 3, "100.0000"))
    assert first == {
        "LEFT-1": Decimal("33.3334"), "LEFT-2": Decimal("33.3333"), "LEFT-3": Decimal("33.3333"),
    }, f"first load: {first}"
    assert second == {
        "MORE-1": Decimal("33.3334"), "MORE-2": Decimal("33.3333"), "MORE-3": Decimal("33.3333"),
    }, f"second load, created in reverse: {second}"
