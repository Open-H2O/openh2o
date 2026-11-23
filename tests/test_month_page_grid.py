# SPDX-License-Identifier: AGPL-3.0-or-later
"""A short month page sits on a two-column grid.

A metered month, a month on a use area with no well and a month waiting for OpenET each show the
short card on the left and, beside it, a card for the month on the ledger: the month's ledger entries
(Date, Amount, Water) and the water year's other months, each linking to its own page when it has
one, the month on screen marked and not a link. The waiting card no longer carries the entries
itself, and the page is named by the use area and the month.
"""

import datetime as dt
import re
from pathlib import Path

import pytest
from django.urls import reverse

from tests import ledger_districts as ld
from tests.test_openet_recorded_figure import (  # noqa: F401  (fixtures)
    _client,
    _enforced,
    _hand_cache,
    operator,
)

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "static" / "css" / "app.css"
TEMPLATE = ROOT / "templates" / "accounting" / "calculation_run_detail.html"


def _field(number, well=True, meter=False):
    """A 100-acre corn field with crop ET for July to September 2025, each month calculated."""
    if not ld.ReportingPeriod.objects.exists():
        ld.seed_reference()
    zone = ld.make_zone(f"{number} GSA", "management_area", -120.59, 37.1, -120.39, 37.3)
    w = ld.make_well(f"{number} well", -120.485, 37.21) if well else None
    field = ld.add_field(number, 100, "Corn", "Sprinkler", [zone], -120.49, 37.2,
                         [{"2025-07": 91.44, "2025-08": 60.96, "2025-09": 30.48}], w)
    if meter:
        ld.ledger(field, dt.date(2025, 7, 20), -5.07, "meter_reading", "GW")
    ld.ledger(field, dt.date(2025, 6, 10), -2.5, "surface_diversion", "SW")  # another month's entry
    ld.run_months(["2025-07", "2025-08", "2025-09"])
    return field


def _waiting_field():
    if not ld.ReportingPeriod.objects.exists():
        ld.seed_reference()
    zone = ld.make_zone("F7 GSA", "management_area", -120.59, 37.1, -120.39, 37.3)
    w = ld.make_well("F7 well", -120.485, 37.21)
    field = ld.add_field("F7", 100, "Corn", "Sprinkler", [zone], -120.49, 37.2, [], w)
    _hand_cache(field, {"2025-08": 15.24, "2025-09": 15.24}, "2025-07-01", "2025-09-30")
    return field


def _main(user, field, month="2025-07"):
    response = _client(user).get(reverse("accounting:calculation_run_detail", args=[field.pk, month]))
    assert response.status_code == 200
    text = response.content.decode()
    return text, text[text.index("<main"): text.index("</main>")]


def _ledger_card(main):
    start = main.index('class="card-raised month-ledger"')
    return main[start:]


def _month_link(field, period):
    return reverse("accounting:calculation_run_detail", args=[field.pk, period])


@pytest.mark.parametrize("kind", ["metered", "no_well", "waiting"])
def test_every_short_month_page_puts_the_short_card_beside_the_months_ledger_card(operator, kind):
    if kind == "waiting":
        field = _waiting_field()
        ld.ledger(field, dt.date(2025, 7, 15), -4.8, "surface_diversion", "SW")
    else:
        field = _field("F8", well=(kind == "metered"), meter=(kind == "metered"))
        if kind == "no_well":
            ld.ledger(field, dt.date(2025, 7, 15), -4.8, "surface_diversion", "SW")

    _text, main = _main(operator, field)

    assert 'class="page-grid-month"' in main
    grid = main[main.index('class="page-grid-month"'):]
    assert grid.index("receipt-short") < grid.index("month-ledger")
    card = _ledger_card(main)
    assert "July 2025 on the ledger" in card
    assert "Jul 15, 2025" in card or "Jul 20, 2025" in card
    assert "Jun 10, 2025" not in card  # another month's entry stays off


def test_the_waiting_card_no_longer_holds_the_months_table(operator):
    field = _waiting_field()
    ld.ledger(field, dt.date(2025, 7, 15), -4.8, "surface_diversion", "SW")

    _text, main = _main(operator, field)

    short = main[main.index("receipt-short"): main.index('class="card-raised month-ledger"')]
    assert "<table" not in short
    assert "<table" in _ledger_card(main)
    assert "ledger entries are below" not in main


def test_the_other_months_link_to_their_own_pages_and_the_current_month_is_marked(operator):
    field = _field("F9", meter=True)

    _text, main = _main(operator, field)
    card = _ledger_card(main)

    assert "Other months, WY 2024-2025" in card
    assert f'href="{_month_link(field, "2025-08")}"' in card
    assert f'href="{_month_link(field, "2025-09")}"' in card
    assert f'href="{_month_link(field, "2025-07")}"' not in card
    assert re.search(r'<span[^>]*aria-current="page"[^>]*>Jul</span>', card)
    # A month with no page of its own is named but not linked.
    assert f'href="{_month_link(field, "2025-03")}"' not in card
    assert re.search(r">Mar<", card)
    months = re.findall(r">(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep)<", card)
    assert months == ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


# Default wording, approved by the maintainer on 2026-11-22. To change the wording, update this test in the same commit.
def test_a_short_month_with_no_ledger_entries_says_so(operator):
    field = _field("F10", well=False)

    _text, main = _main(operator, field)
    card = _ledger_card(main)

    assert "No ledger entries for July 2025." in card
    assert "<table" not in card


def test_a_metered_months_page_is_named_by_the_use_area_and_the_month(operator):
    field = _field("F11", meter=True)

    text, main = _main(operator, field)

    assert "<title>F11, July 2025 - " in text
    assert "Groundwater extraction (estimated)" not in text[: text.index("<main")]


def test_the_month_page_template_carries_no_inline_style():
    assert 'style="' not in TEMPLATE.read_text()


def test_the_month_grid_has_two_columns_and_stacks_in_a_narrow_container():
    css = APP_CSS.read_text()
    rule = re.search(r"(?m)^\.page-grid-month\s*\{([^}]*)\}", css)
    assert rule, "no .page-grid-month rule in app.css"
    assert "grid-template-columns" in rule.group(1)
    assert re.search(r"@container[^{]*\{\s*\.page-grid-month\s*\{[^}]*minmax\(0, 1fr\)", css)
