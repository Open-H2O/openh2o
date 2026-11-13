# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Crop ET block's rules and words that Brent approved on 2026-11-12 (the drawing and the rows).

* Provisional and Final: a figure OpenET sent within 120 days of the month's end is
  Provisional; one sent later is Final; a figure whose received day is unknown carries no
  mark; a Provisional or unmarked figure becomes Final when OpenET sends the same figure
  after the 120 days.
* A newer figure counts only when it differs from the recorded one to the hundredth of an
  acre-foot, on the page, for Accept and in the sync command's list.
* A month OpenET was asked about and sent no crop ET for has a page that says so, with the
  month's ledger entries; a month never asked about stays Not found.
* The Methods page's section, the received day's field label and the Effective precipitation
  caption carry the approved words, and no month page or that section says "fetch".
"""

import datetime as dt
import re
from decimal import Decimal as D

import pytest
from django.apps import apps
from django.urls import reverse

from datasync import crop_et
from tests import ledger_districts as ld
from tests.test_openet_recorded_figure import (  # noqa: F401  (fixtures)
    AUG_6,
    FIRST,
    JULY,
    _client,
    _corn_field,
    _enforced,
    _fetch,
    _fetched_twice,
    _hand_cache,
    _words,
    operator,
)

pytestmark = pytest.mark.django_db

NOV_29 = dt.date(2025, 11, 29)  # 121 days after July 31
DEC_15 = dt.date(2025, 12, 15)


def _page(user, parcel, month=JULY):
    return _client(user).get(reverse("accounting:calculation_run_detail", args=[parcel.pk, month]))


def _main(response):
    text = _words(response)
    return text[text.index("<main"): text.index("</main>")]


def _caption(response):
    main = _main(response)
    start = main.index('id="crop-et"')
    return main[start: main.index("</div>", main.index("budget-seg-caption", start)) + 6]


def _record(parcel, month=JULY):
    return crop_et.current_record(parcel, month)


# ---------------------------------------------------------------- Provisional and Final


def test_a_figure_received_more_than_120_days_after_the_month_is_final(operator):
    field = _corn_field()
    _fetch(field, FIRST, NOV_29, end="2025-07-31")
    ld.run_months([JULY])

    caption = _caption(_page(operator, field))

    assert "received Nov 29, 2025" in caption
    assert '<span class="kind-pill kind-pill--final">Final</span>' in caption
    assert "Provisional" not in caption


def test_a_figure_with_no_received_day_carries_no_pill(operator):
    field = _corn_field()
    ld.add_et(field, FIRST)
    ld.run_months([JULY])

    caption = _caption(_page(operator, field))

    assert "<span>OpenET satellite estimate, date received not recorded</span>" in caption
    assert "kind-pill" not in caption


def test_a_provisional_figure_becomes_final_when_openet_sends_the_same_figure_after_120_days(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    _fetch(field, FIRST, DEC_15)

    response = _page(operator, field)
    caption = _caption(response)

    assert "received Aug 6, 2025" in caption
    assert '<span class="kind-pill kind-pill--final">Final</span>' in caption
    assert 'id="crop-et-newer"' not in _main(response)


def test_an_unmarked_figure_becomes_final_when_openet_sends_the_same_figure_after_120_days(operator):
    field = _corn_field()
    ld.add_et(field, FIRST)
    ld.run_months([JULY])
    _fetch(field, FIRST, DEC_15)

    caption = _caption(_page(operator, field))

    assert "date received not recorded" in caption
    assert '<span class="kind-pill kind-pill--final">Final</span>' in caption


def test_the_same_figure_received_again_within_120_days_leaves_it_provisional(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    _fetch(field, FIRST, dt.date(2025, 9, 28))

    assert '<span class="kind-pill kind-pill--provisional">Provisional</span>' in _caption(_page(operator, field))


# ---------------------------------------------------------------- a difference the page cannot show


def test_a_newer_figure_that_prints_the_same_acre_feet_is_not_a_newer_figure(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    _fetch(field, {**FIRST, JULY: 91.4529}, dt.date(2025, 9, 28))  # 0.0129 mm: 30.00 AF either way

    assert crop_et.newer_figure(_record(field)) is None
    assert crop_et.differing_lines([field], [JULY]) == []
    assert 'id="crop-et-newer"' not in _main(_page(operator, field))


def test_a_newer_figure_a_hundredth_of_an_acre_foot_away_is_shown(operator):
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    _fetch(field, {**FIRST, JULY: 91.48}, dt.date(2025, 9, 28))  # 30.01 AF

    assert crop_et.newer_figure(_record(field)) is not None
    assert 'id="crop-et-newer"' in _main(_page(operator, field))


# ---------------------------------------------------------------- a month OpenET sent nothing for


def _no_figure_field(well=True):
    field = _corn_field(number="F7", well=well)
    _hand_cache(field, {"2025-08": 15.24, "2025-09": 15.24}, "2025-07-01", "2025-09-30")
    return field


def test_a_month_openet_sent_no_crop_et_for_has_a_page_that_says_so(operator):
    field = _no_figure_field()
    ld.ledger(field, dt.date(2025, 7, 15), -4.8, "surface_diversion", "SW")

    response = _page(operator, field)
    main = _main(response)

    assert response.status_code == 200
    assert '<h2 class="receipt-headline">No crop ET from OpenET for July 2025</h2>' in main
    assert (
        "OpenH2O calculates a month from its crop ET. It has not calculated this month. "
        "The month's ledger entries are below."
    ) in main
    assert re.search(r'<div class="budget-seg-label">Surface water delivered</div>\s*<div class="budget-seg-value"><span[^>]*>4\.80', main)
    assert re.search(r'<span class="kind-pill kind-pill--unknown">Unknown</span>', main)
    assert 'id="crop-et"' not in main


def test_a_metered_month_with_no_crop_et_shows_its_meter_reading_with_its_pill(operator):
    field = _no_figure_field()
    ld.ledger(field, dt.date(2025, 7, 20), -5.07, "meter_reading", "GW")

    main = _main(_page(operator, field))

    assert re.search(r'<div class="budget-seg-label">Groundwater extraction</div>\s*<div class="budget-seg-value"><span[^>]*>5\.07', main)
    assert '<span class="kind-pill kind-pill--metered">Metered</span>' in main


def test_a_month_with_no_crop_et_and_no_ledger_entry_says_only_what_is_true(operator):
    field = _no_figure_field(well=False)

    main = _main(_page(operator, field))

    assert "It has not calculated this month." in main
    assert "ledger entries are below" not in main


def test_a_month_openet_was_never_asked_about_stays_not_found(operator):
    field = _no_figure_field()

    assert _page(operator, field, month="2025-06").status_code == 404


# ---------------------------------------------------------------- words elsewhere


METHODS_SENTENCES = [
    "OpenH2O records the first crop ET figure OpenET sends for each use area and month.",
    "A recorded figure is Provisional when OpenET sent it within 120 days of the month’s end.",
    "OpenH2O leaves a figure unmarked if the day it was received is unknown.",
    "A Provisional or unmarked figure becomes Final when OpenET sends the same figure after the 120 days.",
    "OpenH2O treats figures that match to the hundredth of an acre-foot as the same.",
    "The OpenET sync command lists every month with a different figure.",
    "Acceptance takes a reason of 10 to 500 characters.",
    "A person who can correct records may correct the entry with a reason.",
    "These months read “date received not recorded” on the calculation page.",
    "A new gridMET figure for a month changes that month’s next calculation.",
]


def test_the_methods_section_carries_the_approved_sentences_and_no_fetch(operator):
    text = _words(_client(operator).get(reverse("methods")))
    section = text[text.index('id="openet-figure"'):]
    section = section[: section.index("</table>")]

    for sentence in METHODS_SENTENCES:
        assert sentence in section, sentence
    assert ">Provisional and Final</td>" in section  # the page prints curly apostrophes (&rsquo;)
    assert "fetch" not in section.lower()


def test_the_received_day_is_labelled_date_received():
    field = apps.get_model("datasync", "CropETFigure")._meta.get_field("fetched_on")

    assert field.verbose_name == "date received"


def test_the_effective_precipitation_caption_says_it_is_estimated_from_gridmet_rainfall(operator):
    field = _corn_field()
    _fetched_twice(field)

    main = _main(_page(operator, field))

    assert '<div class="budget-seg-caption">estimated from gridMET rainfall</div>' in main
    assert '<div class="budget-seg-caption">gridMET rainfall</div>' not in main


def test_no_month_page_says_fetch(operator):
    field = _corn_field()
    _fetched_twice(field)
    short = _corn_field(number="F9", lon=-120.39, well=False)
    _fetch(short, FIRST, AUG_6)
    ld.run_months([JULY])

    for parcel in (field, short):
        assert not re.search(r"fetch", _main(_page(operator, parcel)), re.I)
    assert not re.search(r"fetch", _main(_page(operator, field)) + _main(_client(operator).get(
        reverse("accounting:calculation_run_detail", args=[field.pk, JULY]), {"open": "accept"})), re.I)


def test_no_figure_month_rounds_like_the_ledger(operator):
    field = _no_figure_field()
    ld.ledger(field, dt.date(2025, 7, 15), D("-3.2956"), "surface_diversion", "SW")

    assert re.search(r"Surface water delivered</div>\s*<div class=\"budget-seg-value\"><span[^>]*>3\.30", _main(_page(operator, field)))
