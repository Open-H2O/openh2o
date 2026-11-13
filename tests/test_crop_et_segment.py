# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the month's calculation page shows OpenET's crop ET (the drawing and words Brent approved).

* The recorded figure is the Crop ET figure's value. One caption says where it came from and
  the day it was received, and a pill says Provisional or Final (the site's ``.kind-pill``).
* A newer figure OpenET sends sits in a band of its own: on the receipt across the top of the
  panel, on the short page under the Crop ET figure. The band carries the newer figure (its
  label, value, received day and pill) beside three sentences that say which figure the month
  is calculated from and what accepting does, and a visible button, never the three-dot menu.
* The button opens the site's correction row (Reason, Accept, Cancel) on one line.
* A ledger entry that differs from the recorded figure gets a band of sentences and a button.
* An earlier figure an acceptance replaced stays a struck row of the Crop ET figure, with the
  site's line under a replaced record.

The worked example is the 100-acre corn field of ``test_openet_recorded_figure``: July 2025
received at 30.00 AF on Aug 6, 2025, and OpenET's newer 40.00 AF received Sep 28, 2025.
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

NEWER_WORDS = (
    "OpenET now reports a different figure for this month. OpenH2O calculates the month from the "
    "recorded 30.00 AF until a person accepts the newer figure. Accepting it replaces the recorded "
    "figure and recalculates the month at once."
)


def _html(user, parcel, **query):
    url = reverse("accounting:calculation_run_detail", args=[parcel.pk, JULY])
    return _words(_client(user).get(url, query))


def _element(page, element_id):
    """The element with ``id``, from its opening tag to the end of the page."""
    start = page.index(f'id="{element_id}"')
    return page[page.rindex("<", 0, start):]


def _band(page, element_id="crop-et-newer"):
    """The band's markup up to the first equation row or the card's end."""
    band = _element(page, element_id)
    for stop in ('<div class="budget-panel-row">', "</main>"):
        if stop in band:
            band = band[: band.index(stop)]
    return band


# ---------------------------------------------------------------- the recorded figure


def test_the_crop_et_figure_carries_the_anchor_and_there_is_no_second_card(operator):
    field = _corn_field()
    _fetched_twice(field)

    page = _html(operator, field)

    assert page.count('id="crop-et"') == 1
    assert re.search(r'<div class="budget-seg" id="crop-et">\s*<div class="budget-seg-label">Crop ET</div>', page)
    assert "Crop ET for" not in page


def test_one_caption_says_the_source_and_the_received_day_and_a_pill_says_provisional(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])

    segment = _element(_html(operator, field), "crop-et")

    assert re.search(
        r'<div class="budget-seg-caption crop-et-caption"><span>OpenET satellite estimate, received Aug 6, 2025</span>\s*'
        r'<span class="kind-pill kind-pill--provisional">Provisional</span></div>',
        segment,
    )
    assert ", provisional" not in segment


# ---------------------------------------------------------------- the newer figure's band


def test_the_newer_figure_sits_in_its_own_band_above_the_receipts_rows(operator):
    field = _corn_field()
    _fetched_twice(field)

    page = _html(operator, field)
    band = _band(page)

    assert page.index('id="crop-et-newer"') < page.index('<div class="budget-panel-row">')
    assert '<div class="budget-seg-label">Newer crop ET from OpenET</div>' in band
    assert re.search(r'<div class="budget-seg-value">40\.00<span class="budget-seg-unit">AF</span></div>', band)
    assert re.search(
        r"<span>received Sep 28, 2025</span>\s*<span class=\"kind-pill kind-pill--provisional\">Provisional</span>",
        band,
    )
    assert NEWER_WORDS in band
    assert "Newer figure<span" not in page
    assert "not used" not in page


def test_a_writer_gets_a_visible_button_and_no_three_dot_menu(operator):
    field = _corn_field()
    _fetched_twice(field)

    page = _html(operator, field)
    band = _band(page)

    assert ">Accept the newer figure</button>" in band
    assert 'hx-target="#crop-et-newer"' in band and 'hx-select="#crop-et-newer"' in band
    assert "?open=accept" in band
    assert "row-actions-btn" not in page
    assert 'name="reason"' not in band


def test_a_viewer_reads_the_band_and_gets_no_button(viewer):
    field = _corn_field()
    _fetched_twice(field)

    page = _html(viewer, field)

    assert NEWER_WORDS in page
    assert "Accept the newer figure" not in page


def test_in_a_finalized_year_an_operator_gets_no_button_and_no_sentence(operator):
    field = _corn_field()
    _fetched_twice(field)
    _finalize()

    page = _html(operator, field)

    assert NEWER_WORDS in page
    assert "Accept the newer figure" not in page
    assert "is finalized" not in page


def test_in_a_finalized_year_an_administrator_gets_the_button(boss):
    field = _corn_field()
    _fetched_twice(field)
    _finalize()

    assert ">Accept the newer figure</button>" in _html(boss, field)


# ---------------------------------------------------------------- the correction row


def test_the_button_opens_the_correction_row_on_one_line_in_the_band(operator):
    field = _corn_field()
    _fetched_twice(field)

    band = _band(_html(operator, field, open="accept"))
    accept = reverse("accounting:crop_et_accept", args=[field.pk, JULY])

    assert 'class="record-correct-form record-correct-form--line"' in band
    assert f'action="{accept}"' in band
    assert '<input type="hidden" name="action" value="accept">' in band
    assert 'name="reason"' in band and "required" in band
    assert '<button type="submit" class="btn-primary btn-sm">Accept</button>' in band
    assert ">Cancel</button>" in band
    assert "Accept the newer figure</button>" not in band
    assert NEWER_WORDS in band


def test_a_viewer_cannot_open_the_correction_row(viewer):
    field = _corn_field()
    _fetched_twice(field)

    assert 'name="reason"' not in _html(viewer, field, open="accept")


# ---------------------------------------------------------------- after an acceptance


def test_after_accepting_the_earlier_figure_is_struck_with_who_when_and_why(operator):
    field = _corn_field()
    _fetched_twice(field)
    _accept(operator, field)

    page = _html(operator, field)
    segment = _element(page, "crop-et")

    assert "<span>OpenET satellite estimate, received Sep 28, 2025</span>" in segment
    assert re.search(
        r"<span>Earlier figure<span class=\"budget-breakdown-note\">received Aug 6, 2025</span></span>\s*"
        r"<b class=\"record-void-text\">30\.00</b>",
        segment,
    )
    assert re.search(
        r'<div class="record-void-note">Replaced [A-Z][a-z]{2} \d{1,2}, \d{4} by J\. Lopez: '
        + re.escape(REASON) + r"\.</div>",
        segment,
    )
    assert 'id="crop-et-newer"' not in page


# ---------------------------------------------------------------- the ledger entry that differs


def test_a_ledger_entry_that_differs_gets_its_sentences_and_a_correct_button(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _sync()
    ld.run_months([JULY])
    ParcelLedger.objects.filter(parcel=field, source_type="et_estimate", effective_date__month=7).update(
        amount_acre_feet=-35
    )

    band = _band(_html(operator, field), "crop-et-entry")

    assert (
        "The ledger's ET estimate entry for this month reads 35.00 AF. OpenH2O calculates the month "
        "from the recorded 30.00 AF. Correcting the entry to 30.00 AF recalculates the month."
    ) in band
    assert ">Correct the entry to 30.00 AF</button>" in band
    assert "Bring to the recorded figure" not in band
    opened = _band(_html(operator, field, open="entry"), "crop-et-entry")
    assert '<input type="hidden" name="action" value="entry">' in opened


# ---------------------------------------------------------------- a month with nothing to estimate


def test_the_short_page_carries_the_figure_and_the_band_inside_its_one_card(operator):
    field = _corn_field(number="F9", well=False)
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    _fetch(field, {**FIRST, JULY: 121.92}, AUG_6.replace(month=9, day=28))

    page = _html(operator, field)

    assert "No groundwater extraction estimated for July 2025" in page
    card = page[page.index("receipt-short"):]
    assert re.search(r'<div class="budget-seg" id="crop-et">\s*<div class="budget-seg-label">Crop ET</div>', card)
    assert re.search(r'<div class="budget-seg-value">30\.00<span class="budget-seg-unit">AF</span></div>', card)
    assert card.index('id="crop-et"') < card.index('id="crop-et-newer"')
    assert NEWER_WORDS in card
    assert page.count("receipt-headline") == 1
