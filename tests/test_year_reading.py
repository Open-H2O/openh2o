# SPDX-License-Identifier: AGPL-3.0-or-later
"""The year reading's surface split gives the same parts whatever order the database returns the kinds in."""
from datetime import date
from decimal import Decimal as D

from accounting.services import split_surface_kinds

KEY = (1, date(2025, 7, 1))


def test_the_surface_split_does_not_depend_on_the_order_of_the_kinds():
    # Chosen so that the two orders round differently at the last digit before the split is sorted.
    one = split_surface_kinds(D("0"), {KEY: D("123.4567")}, {KEY: {"estimated": D("1"), "metered": D("6")}})
    other = split_surface_kinds(D("0"), {KEY: D("123.4567")}, {KEY: {"metered": D("6"), "estimated": D("1")}})

    assert dict(one) == dict(other)
    assert sum(dict(one).values()) == D("123.4567")
