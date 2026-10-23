# SPDX-License-Identifier: AGPL-3.0-or-later
"""The run's notes as one table.

The kinds that were bullets (headgate water left over, canal evaporation, the
unmetered estimate) become one group each, one row per point of diversion, a
total where a group has more than one point. (A fourth, the curtailed point,
went with the curtailment feature, 150.5-01.) Sentences
that ask for attention stay sentences, above the table.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.engine_run import _note_sentences, _note_table, note_lines
from accounting.models import CalculationRequest
from tests.factories import ReportingPeriodFactory

@pytest.fixture
def auth_client(db):
    user = get_user_model().objects.create_user(
        username="notes-reader", email="notes@example.com", password="x-notes-pass-1"
    )
    client = Client()
    client.force_login(user)
    return client


OCT = date(2025, 10, 1)
NOV = date(2025, 11, 1)

RAW = [
    {"kind": "unallocated", "pod": "Crocker", "month": OCT, "amount_af": Decimal("20.00")},
    {"kind": "unallocated", "pod": "Crocker", "month": NOV, "amount_af": Decimal("7.35")},
    {"kind": "unallocated", "pod": "Stevinson", "month": OCT, "amount_af": Decimal("16.05")},
    {"kind": "canal_losses", "pod": "Le Grand", "month": OCT,
     "evaporation_af": Decimal("55.0136"), "spill_af": Decimal("0")},
    {"kind": "canal_losses", "pod": "Atwater", "month": OCT,
     "evaporation_af": Decimal("1.6273"), "spill_af": Decimal("0")},
    {"kind": "estimate_written", "pod": "Atwater", "month": OCT, "estimate_af": Decimal("100")},
    {"kind": "estimate_written", "pod": "Atwater", "month": NOV, "estimate_af": Decimal("62.7261")},
    {"kind": "estimate_right_not_active", "pod": "Old Gate", "month": OCT, "status": "revoked"},
]


def test_each_kind_is_one_group_with_one_row_per_point():
    groups = _note_table(RAW)

    assert [g["table"] for g in groups] == [
        "unallocated", "evaporation", "estimate",
    ]
    left, evap, est = groups
    assert left["rows"] == [
        {"af": "27.35", "where": "Crocker"},
        {"af": "16.05", "where": "Stevinson"},
    ]
    assert left["total"] == "43.40"
    assert evap["rows"] == [
        {"af": "55.01", "where": "Le Grand"},
        {"af": "1.63", "where": "Atwater"},
    ]
    assert evap["total"] == "56.64"
    assert est["rows"] == [{"af": "162.73", "where": "Atwater, 2 months"}]
    assert est["total"] is None


def test_the_labels_are_the_approved_words():
    groups = {g["table"]: g for g in _note_table(RAW)}

    assert groups["unallocated"]["lead"] + groups["unallocated"]["rest"] == (
        "Headgate water left after each field received its ETAW divided by its "
        "irrigation efficiency. Listed on Site Health under Unallocated Delivery."
    )
    assert groups["evaporation"]["lead"] == (
        "Canal evaporation subtracted from the water diverted"
    )
    assert groups["estimate"]["lead"] + groups["estimate"]["rest"] == (
        "Delivery estimated at an unmetered point of diversion as the ETAW of "
        "the fields it serves divided by each field's irrigation efficiency"
    )
    assert "curtailed" not in groups


def test_tabled_sentences_leave_out_only_what_the_table_carries():
    _attention, tabled = _note_sentences(RAW, tabled=True)
    _attention, plain = _note_sentences(RAW)

    assert tabled == ["OpenH2O did not estimate a delivery for Old Gate because the water right is revoked."]
    assert len(plain) == 4


def test_an_estimate_note_without_an_amount_shows_no_amount():
    raw = [{"kind": "estimate_written", "pod": "A Gate", "month": OCT}]

    assert _note_table(raw)[0]["rows"] == [{"af": None, "where": "A Gate, 1 month"}]


def test_note_lines_prints_a_group_as_its_label_and_one_line_per_point():
    left = _note_table(RAW)[0]

    assert note_lines(left) == [
        "Headgate water left after each field received its ETAW divided by its "
        "irrigation efficiency. Listed on Site Health under Unallocated Delivery.",
        "    Crocker: 27.35 AF",
        "    Stevinson: 16.05 AF",
        "    Total: 43.40 AF",
    ]
    assert note_lines("A sentence.") == ["A sentence."]


@pytest.mark.django_db
def test_the_water_year_page_shows_sentences_above_one_table(auth_client):
    period = ReportingPeriodFactory()
    CalculationRequest.objects.create(
        trigger="command",
        reporting_period=period,
        status="succeeded",
        outcome="Calculated 2 months, October 2025 to November 2025.",
        notes=["OpenH2O did not estimate a delivery for Old Gate because the water right is revoked."]
        + _note_table(RAW),
    )

    html = auth_client.get(
        reverse("accounting:period_detail", args=[period.pk])
    ).content.decode()

    assert "What the calculation found" in html
    assert "<li>OpenH2O did not estimate a delivery for Old Gate" in html
    assert html.count('class="data-table calculation-notes-table"') == 1
    assert "Canal evaporation subtracted from the water diverted" in html
    assert ">43.40<" in html
    assert "&#x27;table&#x27;" not in html and "{&#x27;" not in html


@pytest.mark.django_db
def test_the_table_spans_the_card_and_the_poll_sends_it_out_of_band(auth_client):
    # Looked at 1,730 (16:31): in the status column the point names wrapped to
    # four lines beside an empty half card. The page places the table after the
    # card's grid; the 3-second poll returns it with hx-swap-oob.
    period = ReportingPeriodFactory()
    CalculationRequest.objects.create(
        trigger="command", reporting_period=period, status="succeeded",
        outcome="Calculated 2 months.", notes=_note_table(RAW),
    )

    page = auth_client.get(
        reverse("accounting:period_detail", args=[period.pk])
    ).content.decode()
    status = page.index('id="calculation-status"')
    notes = page.index('id="calculation-notes"')
    assert notes > page.index("</div>", status)
    assert 'id="calculation-notes" hx-swap-oob' not in page

    poll = auth_client.get(
        reverse("accounting:period_calculation_status", args=[period.pk])
    ).content.decode()
    assert '<div id="calculation-notes" hx-swap-oob="true">' in poll
    assert "Canal evaporation subtracted from the water diverted" in poll
