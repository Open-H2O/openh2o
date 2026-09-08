# SPDX-License-Identifier: AGPL-3.0-or-later
"""The account balance card says what its numbers mean, and its footer adds.

Phase 143 (R-037, R-038, R-039, R-040), carrying to the account pages the
pattern DESIGN.md → *Tables that explain their numbers* records from the
dashboard. Before this plan the card headed six numeric columns identically,
set Balance at the same size as its own two inputs, listed the three supplies
with nothing saying they were parts of a total, and ordered its rows by the day
an operator happened to assign them.

**How this file is built, and the trap it is written around.** STATE.md's
review questions, and `tests/test_allocations_footer.py`'s own docstring, say a
test may not re-derive the formula it tests: a
``surface + groundwater + rain == total`` assertion cannot disagree with the
view, because it computes what the view computes, and so it measures the test
author's arithmetic rather than the screen. So there is no such assertion here.

Every numeric assertion instead names the LITERAL figure the fixture puts in a
NAMED cell. The fixture's numbers are deliberately not round and do not repeat
each other, so a figure landing in the wrong column fails rather than passing on
a coincidence.

**What the footer is, and why it is allowed to exist at all.** DESIGN.md rule 5
permits a footer only where rows are addable. These rows are: one quantity, one
period, every use area assigned to one account, each appearing once. The footer
cells are the account roll-up's own context values rather than a template sum,
so the footer and the panel above cannot drift apart — and
``test_the_footer_is_the_panel`` is what holds that true.

⚠ The standing risk this file guards: ``WaterAccountParcel`` is unique on
(account, parcel, PERIOD) and the assignment queryset is NOT filtered by the
selected period, so a use area assigned under two periods would render twice and
the rows would then exceed the footer. ``test_the_rows_add_up_to_the_footer`` is
the tripwire.
"""

import re
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
)

pytestmark = pytest.mark.django_db


def _user():
    class _User(factory.django.DjangoModelFactory):
        class Meta:
            model = "core.User"

        username = factory.Sequence(lambda n: f"acctbaluser{n}")
        email = factory.Sequence(lambda n: f"acctbaluser{n}@example.com")
        password = factory.LazyFunction(lambda: make_password("testpass123"))
        is_active = True

    return _User()


#: One `<tr>` of the rendered table, tags stripped, cells separated by "|".
def _rows(html):
    body = html[html.index("Use area breakdown") :]
    table = body[body.index("<table") : body.index("</table>") + 8]
    # The explainer popout's "?" button AND its whole panel body (title, text,
    # help link) sit INSIDE the <th>, so they have to come out before the cell
    # is read or the header reads as a paragraph. Same treatment the 143-01
    # probe gives them.
    table = re.sub(
        r'<span class="explainer-popout".*?</span>\s*</span>', "", table, flags=re.S
    )
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
        ]
        if cells:
            out.append(cells)
    return out


@pytest.fixture
def account_with_three_use_areas():
    """One account, one period, three use areas with distinct supply mixes.

    Deliberately: one surface-only, one groundwater-only, one with both, so a
    figure rendered into the wrong column cannot coincidentally match.

    Returns ``(account, period)``.
    """
    period = ReportingPeriodFactory(
        name="WY 2025-2026",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )
    account = WaterAccountFactory(account_number="TST-ACCT-001", name="Test Holdings")

    # (parcel_number, surface_af, groundwater_af)
    shape = [
        ("TST-APN-001", Decimal("-210.1700"), None),
        ("TST-APN-002", None, Decimal("-48.3300")),
        ("TST-APN-003", Decimal("-95.0500"), Decimal("-12.7100")),
    ]
    for number, surface, groundwater in shape:
        parcel = ParcelFactory(parcel_number=number)
        WaterAccountParcelFactory(
            water_account=account, parcel=parcel, reporting_period=period
        )
        if surface is not None:
            ParcelLedgerFactory(
                parcel=parcel, reporting_period=period,
                source_type="surface_diversion", amount_acre_feet=surface,
                transaction_date=date(2026, 4, 15), effective_date=date(2026, 4, 15),
            )
        if groundwater is not None:
            ParcelLedgerFactory(
                parcel=parcel, reporting_period=period,
                source_type="meter_reading", amount_acre_feet=groundwater,
                transaction_date=date(2026, 5, 15), effective_date=date(2026, 5, 15),
            )
    return account, period


@pytest.fixture
def page(account_with_three_use_areas):
    """The rendered account detail page, and its (account, period)."""
    account, period = account_with_three_use_areas
    client = Client()
    client.force_login(_user())
    response = client.get(
        reverse("accounting:account_detail", args=[account.pk]), {"period": period.pk}
    )
    assert response.status_code == 200
    return response.content.decode(), account, period


# -- The equation the columns are meant to read as ---------------------------


def test_the_leaf_headers_run_in_equation_order(page):
    """R-039. Supplies (Surface, Groundwater, Rain, Total), then use, then Balance.

    A reader must be able to say from the layout WHY the columns are in that
    order (DESIGN.md rule 1). Before this plan they ran Parcel, Consumptive Use,
    Surface, Groundwater, Precip, Supplies, Net -- the answer beside its own
    inputs, and the total three columns away from the parts that make it.
    """
    html, _account, _period = page
    header_cells = [c for row in _rows(html)[:2] for c in row]

    assert header_cells == [
        "Use area",
        "Supplies",
        "Consumptive use",
        "Balance",
        "Surface",
        "Groundwater",
        "Rain",
        "Total",
    ], f"the header no longer reads as the equation: {header_cells}"


def test_the_supplies_group_header_brackets_exactly_four_columns(page):
    """R-039 / DESIGN.md rule 2: structure says which columns sum, not a sentence."""
    html, _account, _period = page

    assert '<th colspan="4" class="th-group-label">Supplies</th>' in html, (
        "the Supplies group header does not span exactly its own four columns, "
        "so nothing shows that Surface + Groundwater + Rain make Total"
    )


def test_there_is_exactly_one_vertical_rule_and_it_is_before_balance(page):
    """DESIGN.md rule 3: one rule, where the kind of number changes.

    Balance is the only derived column on this table -- everything left of it is
    measured water. More than one rule would say the kind changes more than
    once, which is false here.
    """
    html, _account, _period = page
    table = html[html.index("Use area breakdown") :]
    table = table[table.index("<table") : table.index("</table>")]

    header_seps = re.findall(r"<th[^>]*\bcol-sep\b[^>]*>(.*?)</th>", table, re.S)
    assert len(header_seps) == 1, (
        f"expected one ruled header cell, found {len(header_seps)}"
    )
    assert "Balance" in header_seps[0], (
        f"the rule is not before Balance, it is before: {header_seps[0][:60]!r}"
    )


def test_the_unit_is_stated_once_and_never_on_a_column(page):
    """DESIGN.md rule 4. Every numeric column here is acre-feet."""
    html, _account, _period = page

    assert "All figures in acre-feet (AF)." in html
    header_cells = [c for row in _rows(html)[:2] for c in row]
    assert not [c for c in header_cells if "AF" in c or "acre" in c.lower()], (
        f"a column header carries the unit the subtitle already states: {header_cells}"
    )


# -- One name per thing (DESIGN.md rule 6, copy rule 12) ---------------------


def test_the_card_says_rain_and_balance_not_precip_and_net(page):
    """R-037 / rule 6, and the reason this test exists at all.

    `tests/test_water_vocabulary.py` does NOT police these two words -- its
    definitions table has no row for either -- so it stayed green while this
    page said Precip and Net and the dashboard beside it said Rain and Balance.
    This assertion is the gate for that, until the table carries them.
    """
    html, _account, _period = page
    header_cells = [c for row in _rows(html)[:2] for c in row]

    assert "Rain" in header_cells and "Precip" not in header_cells
    assert "Balance" in header_cells
    assert "Net" not in header_cells


def test_the_heading_and_the_column_name_the_same_thing(page):
    """Copy rule 12. The card used to head "Per-Parcel breakdown" over a Parcel
    column, inside a pane whose other card says "Assigned use areas"."""
    html, _account, _period = page

    assert "Use area breakdown" in html
    assert "Per-Parcel breakdown" not in html


# -- The rows, and their order -----------------------------------------------


def test_the_rows_are_ordered_by_use_area_number(page):
    """R-040. The order used to be the day an operator assigned each one."""
    html, _account, _period = page
    numbers = [row[0] for row in _rows(html)[2:] if row[0].startswith("TST-APN-")]

    assert numbers == ["TST-APN-001", "TST-APN-002", "TST-APN-003"], (
        f"the rows are not in use-area-number order: {numbers}"
    )


def test_each_use_area_row_carries_its_own_figures_in_the_right_columns(page):
    """The value test. Literals, in named cells, for the three distinct shapes.

    TST-APN-001 is surface-only, -002 groundwater-only, -003 has both, so a
    figure in the wrong column cannot match by coincidence.
    """
    html, _account, _period = page
    by_number = {row[0]: row for row in _rows(html)[2:] if row[0].startswith("TST-APN-")}

    # cells: use area | surface | groundwater | rain | total | use | balance
    assert by_number["TST-APN-001"][1:5] == ["210.17", "0.00", "0.00", "210.17"]
    assert by_number["TST-APN-002"][1:5] == ["0.00", "48.33", "0.00", "48.33"]
    assert by_number["TST-APN-003"][1:5] == ["95.05", "12.71", "0.00", "107.76"]


# -- The footer --------------------------------------------------------------


def test_the_footer_label_says_what_makes_the_rows_addable(page):
    """DESIGN.md rule 5. "All 3 assigned use areas" -- one period, each once."""
    html, _account, _period = page

    assert '<td class="tfoot-total">All 3 assigned use areas</td>' in html, (
        "the footer does not say what makes its rows addable, which is the "
        "whole condition on a footer existing"
    )


def test_the_rows_add_up_to_the_footer(page):
    """The tripwire, and the one assertion that may compare two rendered numbers.

    This does not re-derive the view's formula: it compares what the SCREEN
    prints in the body against what the SCREEN prints in the footer, which are
    two independent code paths (per-use-area balances, and the account roll-up).
    They are allowed to be equal only because the rows genuinely partition the
    account. If a use area is ever assigned under two periods it will render
    twice and this fails, which is exactly the warning wanted.
    """
    html, _account, _period = page
    rows = _rows(html)
    body = [r for r in rows if r[0].startswith("TST-APN-")]
    footer = [r for r in rows if r[0].startswith("All 3 assigned")][0]

    for column, name in ((1, "surface"), (2, "groundwater"), (3, "rain"), (4, "total")):
        summed = sum(Decimal(r[column].replace(",", "")) for r in body)
        printed = Decimal(footer[column].replace(",", ""))
        assert summed == printed, (
            f"the {name} column's rows print {summed} but its footer prints "
            f"{printed} -- the table and its own total disagree"
        )


def test_the_footer_is_the_panel(page):
    """R-037/R-038's other half: the panel and the table are visibly one thing.

    The footer renders the account roll-up's context values, so the Supplies
    figure in the panel and the Total figure in the footer are the same number
    printed twice. If they ever differ the card is telling a reader two things.
    """
    html, _account, _period = page
    footer = [r for r in _rows(html) if r[0].startswith("All 3 assigned")][0]

    assert footer[4] == "366.26", f"footer total is {footer[4]!r}"
    panel = html[html.index("budget-panel") : html.index("Use area breakdown")]
    assert "366.26" in panel, (
        "the panel's Supplies figure and the table's Total footer are not the "
        "same number, so the card states two different totals"
    )


# -- The panel ---------------------------------------------------------------


def test_balance_is_the_only_lead_figure(page):
    """R-038. Supplies and Consumptive use are its inputs and drop to input size.

    Structural, not a font measurement: `.budget-seg--result` is the class that
    carries the lead size in app.css, and the fault was that NO segment on this
    panel had it, so all three read as equally important.
    """
    html, _account, _period = page
    panel = html[html.index("budget-panel") : html.index("Use area breakdown")]

    assert panel.count("budget-seg--result") == 1, (
        f"expected exactly one lead figure, found "
        f"{panel.count('budget-seg--result')}"
    )
    result_seg = panel[panel.index("budget-seg--result") :]
    assert "Balance" in result_seg[:400], "the lead figure is not Balance"


def test_the_supplies_breakdown_says_it_is_a_breakdown_of_supplies(page):
    """R-037. The three used to sit in a bare foot line saying nothing.

    "by source", not "of which" -- Brent overturned that idiom at the 142-01
    checkpoint and it is not to be reintroduced.
    """
    html, _account, _period = page

    assert "Supplies by source" in html
    assert "of which" not in html
