# SPDX-License-Identifier: AGPL-3.0-or-later
"""The account page's Groundwater budget card states its figures as a sum (ruling 233).

Allocation - Used = Remaining in the house centred equation panel; with credits,
Allocation + Credits - Used = Remaining, every credit listed under the sum in
two columns. These tests read the figures, the operators and the cells, not
sentences. The budget is patched for the shapes the card must draw; the last
test reads a real recharge credit through the whole page.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal as D
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import WaterAccount

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

AUG = (dt.date(2025, 8, 1), dt.date(2025, 8, 31))


@pytest.fixture
def client():
    c = Client()
    c.force_login(get_user_model().objects.create_user(username="op", email="op@example.com", password="x"))
    return c


@pytest.fixture
def d3():
    ld.seed_reference()
    d3 = ld.build_d3(with_event=False)
    d3["account"] = WaterAccount.objects.create(name="D3 District", account_number="D3-D", unit_kind="farm_unit")
    return d3


def _credit(description, amount):
    return SimpleNamespace(description=description, amount_af=D(amount))


def _card(client, account, budget):
    period = ld.period_of(AUG[0])
    with mock.patch("accounting.views.accounts.account_groundwater_budget", return_value=budget):
        body = client.get(reverse("accounting:account_detail", args=[account.pk]) + f"?period={period.pk}").content.decode()
    start = body.index("Groundwater budget</h3>")
    end = body.index('<div class="card-raised page-grid-account-full">', start)
    return body[start:end]


def _cells(card):
    return re.findall(r'<div class="budget-seg-label">([^<]+)</div>', card)


def _values(card):
    return [re.sub(r"<[^>]+>", " ", v).split()[0] for v in re.findall(r'<div class="budget-seg-value[^"]*">(.*?)</div>', card)]


def _operators(card):
    return re.findall(r'<div class="budget-op">([^<]+)</div>', card)


def test_without_credits_the_card_is_three_cells_and_two_operators(d3, client):
    card = _card(client, d3["account"], {"allocation": D("184.71"), "credits": [], "used": D("777.02"), "remaining": D("-592.31")})
    assert "budget-panel--centered" in card
    assert "budget-panel-row--four" not in card
    assert len(_cells(card)) == 3
    assert _values(card) == ["184.71", "777.02", "-592.31"]
    assert _operators(card) == ["&minus;", "&equals;"]
    assert "credit-list" not in card
    assert "<table" not in card


def test_with_credits_the_card_is_four_cells_and_three_operators(d3, client):
    credits = [_credit("Recharge at Basin 2, Jan 15, 2026", "345.8970"), _credit("Carried forward from WY 2024-2025", "-12.5000")]
    card = _card(client, d3["account"], {"allocation": D("100.00"), "credits": credits, "used": D("50.00"), "remaining": D("383.3970")})
    assert "budget-panel-row--four" in card
    assert len(_cells(card)) == 4
    # The credits cell holds the total of the stored amounts: 345.897 - 12.5.
    assert _values(card) == ["100.00", "333.40", "50.00", "383.40"]
    assert _operators(card) == ["+", "&minus;", "&equals;"]


# wording approved: ruling 246
def test_the_two_new_labels_are_the_approved_words(d3, client):
    card = _card(client, d3["account"], {"allocation": D("1"), "credits": [_credit("A", "1")], "used": D("0"), "remaining": D("2")})
    assert _cells(card)[1] == "Credits"
    assert '<div class="budget-breakdown-title">Credits by source and date</div>' in card


def test_every_credit_is_listed_with_its_signed_amount_in_two_columns(d3, client):
    credits = [_credit(f"Recharge at Basin {n}, Jan 15, 2026", f"{n}.2500") for n in range(1, 15)]
    credits.append(_credit("Carried forward from WY 2024-2025", "-3.0000"))
    card = _card(client, d3["account"], {"allocation": None, "credits": credits, "used": D("0"), "remaining": None})
    for n in range(1, 15):
        assert f"Recharge at Basin {n}, Jan 15, 2026" in card
        assert f"+{n}.25" in card
    assert "-3.00" in card
    columns = re.split(r'<div class="credit-list-column">', card)[1:]
    assert len(columns) == 2
    assert [col.count("budget-breakdown-row") for col in columns] == [8, 7]


def test_a_missing_allocation_and_remaining_print_a_dash_with_no_unit(d3, client):
    card = _card(client, d3["account"], {"allocation": None, "credits": [_credit("A", "5")], "used": D("0"), "remaining": None})
    dashes = re.findall(r'<div class="budget-seg-value text-tertiary">&mdash;</div>', card)
    assert len(dashes) == 2


def test_a_real_recharge_credit_reaches_the_sum(d3, client):
    # The district runs the basin and farms nothing: no allocation, one credit
    # of 50 AF less the 10% left in the basin.
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    ld.log_event(d3["site"], *AUG, "50.0000", "GW")
    period = ld.period_of(AUG[0])
    body = client.get(reverse("accounting:account_detail", args=[d3["account"].pk]) + f"?period={period.pk}").content.decode()
    card = body[body.index("Groundwater budget</h3>"):]
    assert _values(card)[:2] == ["&mdash;", "45.00"]
    assert "+45.00" in card
