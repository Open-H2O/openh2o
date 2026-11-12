# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the month's calculation page shows OpenET's crop ET (the drawing Brent approved).

Everything sits inside the page's own Crop ET figure, never in a card of its own:

* the recorded figure is the figure's value, and one caption says where it came from and
  when it was fetched;
* a newer figure, an earlier figure an acceptance replaced, and a ledger entry that differs
  are the figure's own breakdown rows;
* the action is the site's three-dot menu, whose item opens the site's correction row
  (Reason, Accept, Cancel); the menu follows who may correct records, as everywhere else;
* a month with nothing to estimate carries the same block inside its one card.

The worked example is the 100-acre corn field of ``test_openet_recorded_figure``: July 2025
fetched at 30.00 AF on Aug 6, 2025, and OpenET's newer 40.00 AF fetched Sep 28, 2025.
"""

import re

import pytest
from django.urls import reverse

from parcels.models import ParcelLedger
from tests import ledger_districts as ld
from tests.test_openet_recorded_figure import (  # noqa: F401  (fixtures)
    AUG_6,
    FIRST,
    JULY,
    REASON,
    _accept,
    _client,
    _corn_field,
    _enforced,
    _fetch,
    _fetched_twice,
    _finalize,
    _sync,
    _words,
    boss,
    operator,
    viewer,
)

pytestmark = pytest.mark.django_db


def _html(user, parcel, **query):
    url = reverse("accounting:calculation_run_detail", args=[parcel.pk, JULY])
    return _words(_client(user).get(url, query))


def _segment(page):
    """The element that carries id="crop-et", from its opening tag to the next equation operator or card end."""
    start = page.index('id="crop-et"')
    opening = page.rindex("<", 0, start)
    return page[opening:]


# ---------------------------------------------------------------- one place on the page


def test_the_crop_et_figure_carries_the_anchor_and_there_is_no_second_card(operator):
    field = _corn_field()
    _fetched_twice(field)

    page = _html(operator, field)

    assert page.count('id="crop-et"') == 1
    assert re.search(r'<div class="budget-seg" id="crop-et">\s*<div class="budget-seg-label">Crop ET</div>', page)
    assert "Crop ET for" not in page
    assert "OpenET now reports" not in page
    assert "This month uses the recorded" not in page


def test_one_caption_says_the_source_and_the_fetch_day(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])

    page = _html(operator, field)

    assert '<div class="budget-seg-caption">OpenET satellite estimate, fetched Aug 6, 2025, provisional</div>' in page
    assert page.count('class="budget-seg-caption">OpenET') == 1


def test_a_newer_figure_is_a_row_of_the_crop_et_figure(operator):
    field = _corn_field()
    _fetched_twice(field)

    segment = _segment(_html(operator, field))

    assert re.search(
        r"<span>Newer figure<span class=\"budget-breakdown-note\">fetched Sep 28, 2025, not used</span></span>\s*<b>40\.00</b>",
        segment,
    )


# ---------------------------------------------------------------- the menu follows who may correct


def test_a_writer_gets_the_menu_with_accept_newer_figure(operator):
    field = _corn_field()
    _fetched_twice(field)

    segment = _segment(_html(operator, field))

    assert 'class="row-actions-btn"' in segment
    assert ">Accept newer figure</button>" in segment
    assert 'name="reason"' not in segment


def test_a_viewer_sees_the_row_and_no_menu(viewer):
    field = _corn_field()
    _fetched_twice(field)

    page = _html(viewer, field)

    assert "Newer figure" in page
    assert "row-actions-btn" not in page
    assert "Accept newer figure" not in page


def test_in_a_finalized_year_an_operator_gets_no_menu_and_no_sentence(operator):
    field = _corn_field()
    _fetched_twice(field)
    _finalize()

    page = _html(operator, field)

    assert "Newer figure" in page
    assert "Accept newer figure" not in page
    assert "is finalized" not in page


def test_in_a_finalized_year_an_administrator_gets_the_menu(boss):
    field = _corn_field()
    _fetched_twice(field)
    _finalize()

    assert "Accept newer figure" in _html(boss, field)


# ---------------------------------------------------------------- the correction row


def test_the_menu_item_opens_the_correction_row_in_the_crop_et_figure(operator):
    field = _corn_field()
    _fetched_twice(field)

    segment = _segment(_html(operator, field, open="accept"))
    accept = reverse("accounting:crop_et_accept", args=[field.pk, JULY])

    assert 'class="record-correct-form"' in segment
    assert f'action="{accept}"' in segment
    assert '<input type="hidden" name="action" value="accept">' in segment
    assert 'name="reason"' in segment and 'required' in segment
    assert '<button type="submit" class="btn-primary btn-sm">Accept</button>' in segment
    assert ">Cancel</button>" in segment
    assert 'class="row-actions-btn"' not in segment


def test_a_viewer_cannot_open_the_correction_row(viewer):
    field = _corn_field()
    _fetched_twice(field)

    assert 'name="reason"' not in _html(viewer, field, open="accept")


def test_the_item_fetches_the_page_into_the_crop_et_figure(operator):
    field = _corn_field()
    _fetched_twice(field)

    segment = _segment(_html(operator, field))

    assert 'hx-target="#crop-et"' in segment
    assert 'hx-select="#crop-et"' in segment
    assert 'hx-swap="outerHTML"' in segment
    assert "?open=accept" in segment


# ---------------------------------------------------------------- after an acceptance


def test_after_accepting_the_earlier_figure_is_struck_with_who_when_and_why(operator):
    field = _corn_field()
    _fetched_twice(field)
    _accept(operator, field)

    segment = _segment(_html(operator, field))

    assert '<div class="budget-seg-caption">OpenET satellite estimate, fetched Sep 28, 2025, provisional</div>' in segment
    assert re.search(
        r"<span>Earlier figure<span class=\"budget-breakdown-note\">fetched Aug 6, 2025</span></span>\s*"
        r"<b class=\"record-void-text\">30\.00</b>",
        segment,
    )
    assert re.search(
        r'<div class="record-void-note">Replaced [A-Z][a-z]{2} \d{1,2}, \d{4} by J\. Lopez: '
        + re.escape(REASON) + r"\.</div>",
        segment,
    )
    assert "Newer figure" not in segment


# ---------------------------------------------------------------- the ledger entry that differs


def test_a_ledger_entry_that_differs_is_a_row_with_its_own_menu_item(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _sync()
    ld.run_months([JULY])
    ParcelLedger.objects.filter(parcel=field, source_type="et_estimate", effective_date__month=7).update(
        amount_acre_feet=-35
    )

    segment = _segment(_html(operator, field))

    assert re.search(
        r"<span>Ledger entry<span class=\"budget-breakdown-note\">differs from the recorded figure</span></span>\s*<b>35\.00</b>",
        segment,
    )
    assert ">Bring to the recorded figure</button>" in segment
    opened = _segment(_html(operator, field, open="entry"))
    assert '<input type="hidden" name="action" value="entry">' in opened


# ---------------------------------------------------------------- a month with nothing to estimate


def test_the_short_page_carries_the_same_block_inside_its_one_card(operator):
    field = _corn_field(number="F9", well=False)
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    _fetch(field, {**FIRST, JULY: 121.92}, AUG_6.replace(month=9, day=28))

    page = _html(operator, field)

    assert "No groundwater extraction estimated for July 2025" in page
    card = page[page.index("receipt-short"):]
    assert re.search(r'<div class="budget-seg" id="crop-et">\s*<div class="budget-seg-label">Crop ET</div>', card)
    assert re.search(r'<div class="budget-seg-value">30\.00<span class="budget-seg-unit">AF</span></div>', card)
    assert "Newer figure" in card
    assert page.count("receipt-headline") == 1
