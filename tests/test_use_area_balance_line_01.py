# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Water use card ends its months with one Water balance line (ruling 53).

* The line reads Supplies minus Uses equals Balance, in acre-feet, for the water year.
* The figure is the account page's and the Dashboard's (supplies minus crop ET and the
  pumped water not consumed), so a use area shows one balance on every page.
* The balance is coloured by its sign and carries no word: "Surplus" is never printed
  on the use area page (DESIGN.md, the vocabulary table).
* One sentence under it names what went into each side.
* A water year with no calculation has no line.

Every expected figure is a literal worked by hand.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from tests.factories import WaterAccountParcelFactory, WellIrrigatedParcelFactory
from tests.test_water_use_card_01 import (
    NOV,
    calculated_row,
    card,
    delivery,
    fetch,
    run,
    use_area,
    water_year,
    words,
)

pytestmark = pytest.mark.django_db


def balance_line(card_html):
    """The Water balance block: from its title to the end of its sentence."""
    assert "statement-balance" in card_html, "the card has no Water balance line"
    return card_html.split('class="statement-table-title">Water balance', 1)[1].split("</p>", 1)[0]


def test_the_line_reads_supplies_minus_uses_equals_balance():
    # Supplies 5.00 delivered + 1.00 rain = 6.00; uses 4.00 crop ET; balance 2.00.
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000", precip="1.0000")
    delivery(parcel, rp, NOV, "5.0000")
    line = balance_line(card(parcel, rp))
    assert "Supplies 6.00 AF − Uses 4.00 AF = Balance 2.00 AF" in words(line)


def test_a_positive_balance_is_green_and_carries_no_word():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000", precip="1.0000")
    delivery(parcel, rp, NOV, "5.0000")
    line = balance_line(card(parcel, rp))
    assert 'class="statement-balance-value text-surplus"' in line
    for word in ("Surplus", "Deficit", "Balanced"):
        assert word not in words(line)


def test_a_negative_balance_is_orange_with_its_minus_sign():
    # Supplies 1.00 delivered; uses 4.00 crop ET; balance -3.00.
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    delivery(parcel, rp, NOV, "1.0000")
    line = balance_line(card(parcel, rp))
    assert "Balance -3.00 AF" in words(line)
    assert 'class="statement-balance-value text-deficit"' in line


def test_a_balance_that_prints_zero_takes_the_plain_colour():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    delivery(parcel, rp, NOV, "4.0000")
    line = balance_line(card(parcel, rp))
    assert "Balance 0.00 AF" in words(line)
    assert 'class="statement-balance-value"' in line


def test_the_sentence_names_each_side_on_a_use_area_with_no_well():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000", precip="1.0000")
    delivery(parcel, rp, NOV, "5.0000")
    assert (
        "Supplies are surface water delivered and effective precipitation. Uses are crop ET."
    ) in words(balance_line(card(parcel, rp)))


def test_the_sentence_names_groundwater_on_a_use_area_with_a_well():
    rp = water_year()
    parcel = use_area()
    WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, NOV, et="4.0000")
    calculated_row(parcel, rp, NOV)
    assert (
        "Supplies are surface water delivered, groundwater extraction and effective precipitation."
    ) in words(balance_line(card(parcel, rp)))


def test_pumped_water_not_consumed_is_named_with_its_amount_when_there_is_some():
    # The estimated run stamps 3.0000 AF extracted, 0.6000 AF of it not consumed by the
    # crop. Uses: 4.00 crop ET + 0.60 = 4.60.
    rp = water_year()
    parcel = use_area()
    WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, NOV, et="4.0000", gw_extracted_af="3.0000", deep_percolation_gw_af="0.6000")
    calculated_row(parcel, rp, NOV, af="2.4000")
    line = words(balance_line(card(parcel, rp)))
    assert "Uses 4.60 AF" in line
    assert "Uses are crop ET and the pumped water not consumed, 0.60 AF." in line


def test_the_balance_is_the_one_the_account_page_prints_for_the_use_area():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    delivery(parcel, rp, NOV, "1.0000")
    assignment = WaterAccountParcelFactory(parcel=parcel)
    user, _ = get_user_model().objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    account = client.get(
        reverse("accounting:account_detail", args=[assignment.water_account.pk]), {"period": rp.pk}
    ).content.decode()
    row = account.split(parcel.parcel_number, 1)[1].split("</tr>", 1)[0]
    assert "-3.00" in words(row)
    assert "Balance -3.00 AF" in words(balance_line(card(parcel, rp)))


def test_a_water_year_with_no_calculation_has_no_balance_line():
    rp = water_year()
    parcel = use_area()
    delivery(parcel, rp, NOV, "1.0000")
    assert "statement-balance" not in fetch(parcel, rp)
