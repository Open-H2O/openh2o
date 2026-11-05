# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changes to this year's records: the card, its words and its answers.

A finalized water year shows a code computed from its records (``core/fingerprint.py``,
unchanged). The page used to print it as a field in the Water year details card, with the
words Fingerprint, Check, and "Matches" / "Does not match". The approved drawing
(``year-changes-mockup-2026-11-04``) gives it its own card under the top row, in plain
words, and a new set of answers. These tests pin the words and the logic behind them on the
real paths: ``take_fingerprint``, ``check_fingerprint``, the real views through the client,
and ``core.corrections.correct``. Literal sentences are written out here, never read back
from the code under test. The fixtures are the ones ``tests/test_fingerprint_04.py`` uses
(hand-checked district D1, a year finalized through the real view and its code pinned to
Oct 15, 2025).

What a correction explains (the rule these tests pin):

* a differing part is named after "Look at:" only when the corrections since do not
  explain it;
* a correction explains the part of its own kind, and, whatever its kind, Change history and
  every part OpenH2O's calculation writes when it recalculates after a correction (the use
  ledger, calculation results, diversion records, unallocated deliveries, canal losses,
  carry-over, account credits);
* the stated limit: a correction and an unrecorded change in the SAME part read as the
  correction alone.
"""

import copy
import re
from decimal import Decimal as D
from unittest import mock
from html import unescape
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connection
from django.urls import reverse

from accounting.locks import override
from accounting.models import ReportingPeriod, ReportingPeriodEvent

# The fixtures and helpers of the fingerprint tests: one hand-checked district, one pinned code.
from tests.test_fingerprint_04 import (  # noqa: F401  (fixtures are used by name)
    HX,
    PINNED,
    REASON,
    TAKEN,
    _check_url,
    _client,
    _correct_july,
    _day,
    _file_url,
    _finalize,
    _meter_sql,
    _pin,
    _reopen,
    administrator,
    d1,
    filed,
    fp,
    operator,
    viewer,
    year,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _quiet(request, settings):
    """Like the fingerprint tests: no calculation starts on its own. A test that asks for
    ``real_recalculation`` gets the engine instead, to check the explained set against it."""
    settings.ACCESS_CONTROL_ENFORCED = True
    if "real_recalculation" in request.fixturenames:
        yield
        return
    with mock.patch("accounting.engine_run.start_calculation"):
        yield


@pytest.fixture
def real_recalculation():
    return True

HEADING = "Changes to this year's records"
SENTENCE = "Shows whether anything has changed since this code was taken."
CARD_OPEN = '<div class="card-raised page-grid-account-full" id="fingerprint">'

NO_CHANGES = f"No changes found since {TAKEN}."
UNRECORDED = "Changes found with no correction on record."
DISAGREES = "The stored code no longer agrees with its own parts."
LEVELS = "UPDATE measurements_watermeasurement SET value = value + 1"
METERS = "UPDATE measurements_meterreading SET current_value = current_value + 1"

OLD_WORDS = ("fingerprint", "matches")
# Words the copy rules forbid, checked on the card, the answers and the file.
BANNED = re.compile(
    r"audit trail|tamper|evidence|attestation|sworn|certified|verify|proof|\byou\b|\byour\b|\u2014",
    re.I,
)


# -- Reading the page ---------------------------------------------------------------------------


def _visible(html):
    """The words a person reads: tags, scripts, styles, ids and URLs gone, entities decoded."""
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)</(p|div|h\d|li|tr|td|th|form|section|table)>|<br\s*/?>", " ", html)
    text = unescape(re.sub(r"<[^>]+>", "", html)).replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def _detail(client, period):
    response = client.get(reverse("accounting:period_detail", args=[period.pk]))
    assert response.status_code == 200
    return response.content.decode()


def _pressed(client, period):
    """The page Check prints without scripts."""
    response = client.post(_check_url(period))
    assert response.status_code == 200
    return response.content.decode()


def _card(body):
    """The new card's html, from its opening tag to the next card; fails when there is none."""
    assert CARD_OPEN in body, "the water year page has no Changes to this year's records card"
    start = body.index(CARD_OPEN)
    end = body.find('<div class="card-raised', start + len(CARD_OPEN))
    return body[start:] if end == -1 else body[start:end]


def _answer_p(client, period):
    """``(classes, inner html)`` of Check's answer, asked for the way HTMX asks."""
    response = client.post(_check_url(period), **HX)
    assert response.status_code == 200
    found = re.search(
        r'<p class="([^"]*)" id="fingerprint-answer" role="status"[^>]*>(.*?)</p>',
        response.content.decode(),
        re.S,
    )
    assert found, response.content.decode()
    return found.group(1), found.group(2)


def _answer(client, period):
    return _visible(_answer_p(client, period)[1])


def _warned(inner):
    """The text of every span in the warning colour, in the answer's html."""
    return [_visible(text) for text in re.findall(r'<span class="text-warning">(.*?)</span>', inner, re.S)]


def _count_link(inner):
    """``(href, text)`` of the count's link in the answer's html, or None."""
    found = re.search(r'<a href="([^"]+)"[^>]*>(\d+ corrections?)</a>', inner)
    return (unescape(found.group(1)), found.group(2)) if found else None


def _differing(period):
    """The keys of the parts whose digest now differs from the stored code's."""
    stored = period.fingerprint_parts
    computed = fp().compute(period, stored)
    return [key for key in computed.parts if computed.parts[key]["digest"] != stored["parts"][key]["digest"]]


def _short(digest):
    head = digest[:20].upper()
    return "-".join(head[i : i + 4] for i in range(0, 20, 4))


def _correct_level(d1, administrator):
    """Correct the year's one water level from 5 to 6 through the recorded door."""
    from core.corrections import correct

    with override(REASON):
        correct(d1["level"], user=administrator, reason=REASON, changes={"value": D("6")})


def _sql(statement):
    _meter_sql(sql=statement)


@pytest.fixture
def upgraded(year):
    """WY 2024-2025 finalized with no code, then given one by the upgrade command, pinned to Oct 15, 2025."""
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    call_command("record_fingerprints")
    _pin(year)
    assert year.fingerprint_parts["at_upgrade"] is True
    return year


# -- The card -------------------------------------------------------------------------------------


def test_a_finalized_year_with_a_code_has_its_own_card_under_the_top_row(filed, administrator):
    body = _detail(_client(administrator), filed)
    card = _card(body)
    # Under the top row (Water year details, Allocations by water type), before Calculation.
    assert body.index("Allocations by water type</h2>") < body.index(CARD_OPEN) < body.index("Calculation</h2>")
    text = _visible(card)
    assert text.startswith(f"{HEADING} {SENTENCE}")
    assert "Check for changes" in text and "Download a copy to keep" in text
    assert text.index("Check for changes") < text.index("Download a copy to keep")
    # The card's head row folds, through the one new class.
    assert 'class="row-between year-changes-head"' in card


def test_the_actions_are_as_drawn_and_check_is_still_a_post_form_with_htmx(filed, administrator):
    card = _card(_detail(_client(administrator), filed))
    assert f'<a href="{_file_url(filed)}" class="text-link">Download a copy to keep</a>' in card
    assert f'method="post" action="{_check_url(filed)}"' in card
    assert f'hx-post="{_check_url(filed)}" hx-target="#fingerprint-answer" hx-swap="outerHTML"' in card
    assert '<button type="submit" class="btn-as-link text-link">Check for changes</button>' in card
    assert '<span id="fingerprint-answer"></span>' in card


def test_water_year_details_no_longer_prints_a_code(filed, administrator):
    body = _detail(_client(administrator), filed)
    text = _visible(body)
    details = text[text.index("Water year details") : text.index("Allocations by water type")]
    assert _short(filed.fingerprint) not in details
    assert "Code" not in details and "Check" not in details and "Download" not in details
    assert 'field-label">Fingerprint' not in body
    # The one place the code is printed is the new card.
    assert body.count(_short(filed.fingerprint)) == 1
    assert _short(filed.fingerprint) in _visible(_card(body))


def test_the_card_is_not_on_an_open_year_a_reopened_year_or_a_year_with_no_code(year, administrator):
    client = _client(administrator)
    for body in (_detail(client, year),):
        assert HEADING not in _visible(body) and 'id="fingerprint"' not in body
    _finalize(client, year)
    assert HEADING in _visible(_detail(client, year))
    _reopen(client, year)
    reopened = _detail(client, year)
    assert year.fingerprint and HEADING not in _visible(reopened) and 'id="fingerprint"' not in reopened
    assert "Check for changes" not in _visible(reopened)
    # Finalized, but the code was never taken.
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True, fingerprint="", fingerprint_parts={})
    bare = _detail(client, year)
    assert HEADING not in _visible(bare) and 'id="fingerprint"' not in bare


# -- At rest -------------------------------------------------------------------------------------------


def test_at_rest_an_ordinary_code_reads_code_and_the_day_it_was_taken(filed, administrator):
    card = _card(_detail(_client(administrator), filed))
    code = _short(filed.fingerprint)
    assert f'Code <span class="text-mono">{code}</span>, taken {TAKEN}' in card
    text = _visible(card)
    assert text.endswith(f"Code {code}, taken {TAKEN}")
    assert "after the year was finalized" not in text and "do not show here" not in text
    assert "First code" not in text and "restated" not in text.lower()


def test_at_rest_a_code_taken_by_the_upgrade_says_it_was_taken_after_the_year_was_finalized(upgraded, administrator):
    card = _card(_detail(_client(administrator), upgraded))
    code = _short(upgraded.fingerprint)
    assert (
        f'Code <span class="text-mono">{code}</span>, taken {TAKEN}, after the year was finalized. '
        '<span class="text-primary">Changes before that date do not show here.</span>'
    ) in card
    assert _visible(card).endswith(
        f"Code {code}, taken {TAKEN}, after the year was finalized. Changes before that date do not show here."
    )


def test_at_rest_a_year_finalized_again_keeps_the_older_code_as_a_quieter_line(filed, administrator):
    client = _client(administrator)
    old = _short(filed.fingerprint)
    _reopen(client, filed)
    _finalize(client, filed)
    new = _short(filed.fingerprint)
    assert new != old or filed.fingerprint_parts["first"]["digest"] == filed.fingerprint
    card = _card(_detail(client, filed))
    text = _visible(card)
    assert f"Code {new}, taken {_day(filed.fingerprint_at)}" in text
    assert f"First code {old}, as filed {TAKEN}." in text
    assert text.index(f"Code {new}") < text.index(f"First code {old}")
    assert f'First code <span class="text-mono">{old}</span>, as filed {TAKEN}.' in card
    assert "restated" not in text.lower() and "after the year was finalized" not in text


def test_at_rest_a_first_code_taken_by_the_upgrade_reads_first_taken(upgraded, administrator):
    client = _client(administrator)
    old = _short(upgraded.fingerprint)
    _reopen(client, upgraded)
    _finalize(client, upgraded)
    text = _visible(_card(_detail(client, upgraded)))
    assert f"First code {old}, first taken {TAKEN}." in text
    # The newest code was taken at a filing, so it carries the ordinary line.
    assert "after the year was finalized" not in text


# -- The old words are gone ----------------------------------------------------------------------------


def test_no_old_word_and_no_banned_word_is_on_screen_in_any_state(d1, filed, administrator):
    """Fingerprint and matches appear in no visible text of the page, the answers or the file.

    The states run one after another on the same year: at rest, ordinary and upgrade-taken,
    restated, a recorded correction, an unrecorded edit, a code that disagrees, a part that
    cannot be read. Ids and URLs are not visible text and are not read.
    """
    client = _client(administrator)

    def look(label):
        page = _detail(client, filed)
        posted = _pressed(client, filed)
        fragment = client.post(_check_url(filed), **HX).content.decode()
        file_text = client.get(_file_url(filed)).content.decode()
        for name, html in (("page", page), ("pressed page", posted), ("answer", fragment), ("file", file_text)):
            low = _visible(html).lower() if name != "file" else file_text.lower()
            for word in OLD_WORDS:
                assert word not in low, (label, name, word)
        for name, html in (("card", _card(posted)), ("answer", fragment)):
            assert not BANNED.search(_visible(html)), (label, name, BANNED.search(_visible(html)))
        assert not BANNED.search(file_text), (label, "file", BANNED.search(file_text))
        assert "text-error" not in _card(posted), label

    look("at rest")
    parts = copy.deepcopy(filed.fingerprint_parts)
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint_parts={**parts, "at_upgrade": True})
    look("taken by the upgrade")
    ReportingPeriod.objects.filter(pk=filed.pk).update(
        fingerprint_parts={**parts, "first": {"digest": "1f0c" + "7" * 60, "at": PINNED.isoformat(), "at_upgrade": False}}
    )
    look("restated")
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint_parts=parts)
    _correct_level(d1, administrator)
    look("a correction")
    _sql(METERS)
    look("a correction and an unrecorded edit")
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint="0" * 64)
    look("a code that disagrees")
    broken = copy.deepcopy(parts)
    broken["columns"]["measurements.RetiredTableEvent"] = ["pgh_id"]
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint_parts=broken)
    look("a part that cannot be read")


# -- The answers -----------------------------------------------------------------------------------------


def test_no_changes_found(filed, administrator):
    classes, inner = _answer_p(_client(administrator), filed)
    assert classes == "text-primary text-base"
    assert _visible(inner) == NO_CHANGES == "No changes found since Oct 15, 2025."
    assert _warned(inner) == [] and _count_link(inner) is None
    # Without scripts the page prints the same sentence in the card.
    card = _card(_pressed(_client(administrator), filed))
    assert NO_CHANGES in _visible(card)
    assert _visible(card).index(NO_CHANGES) < _visible(card).index(f"Code {_short(filed.fingerprint)}")


def test_a_correction_alone_reads_the_count_and_no_look_at(d1, filed, administrator):
    _correct_level(d1, administrator)
    assert _differing(filed) == ["measurements.WaterMeasurement", "history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == "1 correction since Oct 15, 2025."
    assert _count_link(inner)[1] == "1 correction"
    assert "Look at" not in inner and _warned(inner) == []


def test_several_corrections_read_the_count_in_the_plural(d1, filed, administrator):
    from core.corrections import correct

    with override(REASON):
        correct(d1["level"], user=administrator, reason=REASON, changes={"value": D("6")})
        correct(d1["reads"][2], user=administrator, reason=REASON, changes={"current_value": D("1450")})
    _correct_july(d1, administrator)
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == "3 corrections since Oct 15, 2025."
    assert _count_link(inner)[1] == "3 corrections"
    assert "Look at" not in inner and _warned(inner) == []


def test_a_correction_that_moved_a_figure_reads_as_the_correction_alone(d1, filed, administrator):
    """The suite's fixture stops the recalculation (``start_calculation`` is mocked), so only the use
    ledger, the corrected kind, and Change history differ."""
    _correct_july(d1, administrator)
    assert _differing(filed) == ["parcels.ParcelLedger", "history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == "1 correction since Oct 15, 2025."


def test_changes_with_no_correction_name_the_part_and_the_warning_colour_marks_the_first_sentence(
    filed, administrator
):
    _sql(METERS)
    assert _differing(filed) == ["measurements.MeterReading", "history"]
    classes, inner = _answer_p(_client(administrator), filed)
    assert classes == "text-primary text-base"
    # Change history differs too, and is not named: a direct edit leaves history behind.
    assert _visible(inner) == f"{UNRECORDED} Look at: meter readings."
    assert _warned(inner) == [UNRECORDED]
    assert '<span class="text-warning">' + UNRECORDED + "</span> Look at: meter readings." in inner
    assert _count_link(inner) is None
    assert "text-error" not in inner


def test_several_unrecorded_parts_are_named_in_the_order_of_the_year_without_change_history(
    filed, administrator
):
    _sql(METERS)
    _sql(LEVELS)
    assert _differing(filed) == ["measurements.MeterReading", "measurements.WaterMeasurement", "history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"{UNRECORDED} Look at: meter readings, water levels."


def test_a_correction_and_an_unrecorded_edit_in_a_different_part_read_both(d1, filed, administrator):
    _correct_level(d1, administrator)
    _sql(METERS)
    assert _differing(filed) == ["measurements.MeterReading", "measurements.WaterMeasurement", "history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"1 correction since Oct 15, 2025. {UNRECORDED} Look at: meter readings."
    # The count is not in the warning colour; the unrecorded sentence is, and only it.
    assert _warned(inner) == [UNRECORDED]
    assert _count_link(inner)[1] == "1 correction"


def test_a_ledger_correction_and_an_unrecorded_meter_edit_read_both(d1, filed, administrator):
    _correct_july(d1, administrator)
    _sql(METERS)
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"1 correction since Oct 15, 2025. {UNRECORDED} Look at: meter readings."


def test_the_stated_limit_a_correction_and_an_unrecorded_edit_in_the_same_part_read_as_the_correction_alone(
    d1, filed, administrator
):
    """Pinned as behaviour: the part is explained by the correction, so the edit inside it is not named."""
    _correct_level(d1, administrator)
    _sql(LEVELS)  # an unrecorded edit to the same part (water levels), after the correction
    assert _differing(filed) == ["measurements.WaterMeasurement", "history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == "1 correction since Oct 15, 2025."
    assert "Look at" not in inner and _warned(inner) == []


@pytest.mark.parametrize(
    ("key", "statement", "named"),
    [
        ("parcels.ParcelLedger", "UPDATE parcels_parcelledger SET description = description || ' edited'", "use ledger"),
        ("accounting.CalculationRun", "UPDATE accounting_calculationrun SET gross_et_af = gross_et_af + 1", "calculation results"),
    ],
)
def test_a_correction_that_starts_no_recalculation_explains_only_its_own_part(d1, filed, administrator, key, statement, named):
    """A water level correction recalculates nothing, so a changed ledger or result beside it has no excuse."""
    _correct_level(d1, administrator)
    _sql(statement)
    assert key in _differing(filed)
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"1 correction since Oct 15, 2025. Changes found with no correction on record. Look at: {named}."


def test_every_part_a_recalculation_writes_is_explained_by_a_correction_that_starts_one():
    """Read from the code: seepage moves carry-over and credits (surface/services.py), and the rest from run_month."""
    from accounting.fingerprints import RECALCULATION_PARTS

    assert {
        "parcels.ParcelLedger", "accounting.CalculationRun", "surface.DiversionRecord", "surface.UnallocatedDelivery",
        "surface.CanalMonthLoss", "accounting.WaterCredit", "accounting.WaterCreditDraw",
        "accounting.AllocationCarryover", "accounting.AccountCredit",
    } == RECALCULATION_PARTS


def test_a_real_recalculation_is_explained_by_the_correction_that_caused_it(
    d1, filed, administrator, real_recalculation
):
    """The engine runs for real (nothing is mocked). The ledger correction recalculates July: the use
    ledger and calculation results are rewritten, and FP-A, a use area with no row in the year before,
    gets its first ledger row and result, so the Use areas part gains a row. All of it reads as the
    correction alone; no use area row was edited."""
    from parcels.models import ParcelLedger

    assert not ParcelLedger.objects.filter(parcel__parcel_number="FP-A").exists()
    _correct_july(d1, administrator)
    assert ParcelLedger.objects.filter(parcel__parcel_number="FP-A").exists()
    differing = _differing(filed)
    assert "accounting.CalculationRun" in differing and "parcels.Parcel" in differing
    stored = filed.fingerprint_parts["parts"]["parcels.Parcel"]["rows"]
    assert fp().compute(filed, filed.fingerprint_parts).parts["parcels.Parcel"]["rows"] == stored + 1
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == "1 correction since Oct 15, 2025."


def test_an_edit_to_a_use_area_is_named_beside_a_correction_of_another_kind(d1, filed, administrator):
    """The Use areas part is explained by a recalculation only when it gained rows; a changed column
    with the same rows is an edit to a use area and is named."""
    from parcels.models import Parcel

    _correct_level(d1, administrator)
    with override("a test of the recorded door"):
        Parcel.objects.filter(pk=d1["F2"].pk).update(change_reason="edited without a correction")
    assert _differing(filed) == ["measurements.WaterMeasurement", "parcels.Parcel", "history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"1 correction since Oct 15, 2025. {UNRECORDED} Look at: use areas."


def test_a_part_the_calculation_does_not_write_is_named_even_with_a_correction(d1, filed, administrator):
    _correct_level(d1, administrator)
    _sql("UPDATE accounting_allocationplan SET notes = 'edited'")
    assert "accounting.AllocationPlan" in _differing(filed)
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"1 correction since Oct 15, 2025. {UNRECORDED} Look at: allocations."


def test_change_history_is_named_when_it_is_the_only_part_that_differs(filed, administrator):
    # Two edits that cancel leave the records as they were and two entries in Change history.
    _sql(METERS)
    _sql("UPDATE measurements_meterreading SET current_value = current_value - 1")
    assert _differing(filed) == ["history"]
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == f"{UNRECORDED} Look at: change history."
    assert _warned(inner) == [UNRECORDED]


def test_a_code_that_disagrees_with_its_own_parts_is_the_warning_alone(filed, administrator):
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint="0" * 64)
    classes, inner = _answer_p(_client(administrator), filed)
    assert classes == "text-primary text-base"
    assert _visible(inner) == DISAGREES
    assert _warned(inner) == [DISAGREES]
    assert _count_link(inner) is None


def test_a_part_that_cannot_be_read_is_appended_with_todays_sentence_where_it_applies(filed, administrator):
    stored = copy.deepcopy(filed.fingerprint_parts)
    stored["columns"]["measurements.RetiredTableEvent"] = ["pgh_id"]
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint="0" * 64, fingerprint_parts=stored)
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == (
        f"{DISAGREES} OpenH2O can no longer read the change history, because a later version removed "
        "what it was computed from."
    )
    assert _warned(inner) == [DISAGREES]
    # And beside an unrecorded edit.
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint=filed.fingerprint)
    _sql(METERS)
    _, inner = _answer_p(_client(administrator), filed)
    assert _visible(inner) == (
        f"{UNRECORDED} Look at: meter readings. OpenH2O can no longer read the change history, because a "
        "later version removed what it was computed from."
    )
    assert _warned(inner) == [UNRECORDED]


# -- The count's link ---------------------------------------------------------------------------------------


def test_the_count_links_to_the_figures_as_filed_card_when_it_lists_a_correction(d1, filed, administrator):
    _correct_july(d1, administrator)
    client = _client(administrator)
    _, inner = _answer_p(client, filed)
    assert _count_link(inner) == ("#figures-as-filed", "1 correction")
    assert '<a href="#figures-as-filed" class="prose-link">1 correction</a> since Oct 15, 2025.' in inner
    # The place it lands is on the page that prints the answer.
    assert 'id="figures-as-filed"' in _pressed(client, filed)


def test_the_count_links_to_change_history_from_the_day_the_code_was_taken_otherwise(d1, filed, administrator):
    _correct_level(d1, administrator)  # a water level feeds no use area's figure, so the card lists nothing
    client = _client(administrator)
    _, inner = _answer_p(client, filed)
    href, text = _count_link(inner)
    assert text == "1 correction"
    assert href == reverse("change_history") + "?from=2025-10-15" == "/changes/?from=2025-10-15"
    # It always lands somewhere.
    assert client.get(href).status_code == 200


def test_several_corrections_link_to_the_card_when_it_lists_at_least_one(d1, filed, administrator):
    _correct_level(d1, administrator)
    _correct_july(d1, administrator)
    _, inner = _answer_p(_client(administrator), filed)
    assert _count_link(inner) == ("#figures-as-filed", "2 corrections")


# -- A code taken before this change ----------------------------------------------------------------------------


def test_the_part_names_still_feed_the_code_unchanged():
    """Renaming a part would flip every stored code to "disagrees". This digest was computed on the base
    commit (4c41acdf) from the 23 parts in their order, each given the digest of its position."""
    parts = {key: {"digest": f"{index:064x}"} for index, key in enumerate(fp().PART_KEYS)}
    assert len(parts) == 23
    assert fp().whole_digest(parts) == "9ec624555332b151e7d7491a610b0afa8a4881478cd507b9f0a304bdf95d510c"


def test_a_code_taken_before_this_change_still_answers_no_changes_found(year, administrator):
    """The code is taken the way the old release took it (``take_fingerprint``), no record is changed, and the
    new words answer it."""
    from accounting import fingerprints

    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    year.refresh_from_db()
    fingerprints.take_fingerprint(year)
    year.save(update_fields=fingerprints.FINGERPRINT_FIELDS)
    _pin(year)
    assert fingerprints.check_fingerprint(year).state == "matches"
    assert _answer(_client(administrator), year) == NO_CHANGES


# -- The downloaded file -------------------------------------------------------------------------------------------


def test_the_file_is_named_changes_code_and_reads_in_the_new_words(filed, administrator):
    response = _client(administrator).get(_file_url(filed))
    assert response["Content-Disposition"] == 'attachment; filename="changes-code-wy-2024-2025.txt"'
    text = response.content.decode()
    lines = text.splitlines()
    assert lines[1] == "Changes to this year's records: water year WY 2024-2025"
    assert lines[2] == "(Oct 1, 2024 to Sep 30, 2025)"
    assert f"Code        {_short(filed.fingerprint)}" in lines
    assert f"Full code   {filed.fingerprint.upper()}" in lines
    assert f"Taken       {TAKEN}, when the year was finalized" in lines
    assert "What the code covers" in lines
    assert max(len(line) for line in lines) <= 76
    low = text.lower()
    for word in OLD_WORDS:
        assert word not in low
    assert not BANNED.search(text)
    flat = text.replace("\n", " ")
    assert "Press Check for changes. OpenH2O recomputes the code from the records now." in re.sub(r"\s+", " ", flat)
    assert "does not show that the records were right" in re.sub(r"\s+", " ", flat)


def test_the_file_of_a_code_taken_by_the_upgrade_carries_the_two_added_lines(upgraded, administrator):
    text = _client(administrator).get(_file_url(upgraded)).content.decode()
    assert (
        f"Taken       {TAKEN}, when OpenH2O began keeping these codes\n"
        "            and after the year was finalized. Changes before that date do\n"
        "            not show in this check.\n"
    ) in text
    assert "Finalized   date not on record\n" in text
    assert max(len(line) for line in text.splitlines()) <= 76
    assert "fingerprint" not in text.lower()


def test_the_file_of_a_year_finalized_again_keeps_the_first_code_in_the_same_columns(filed, administrator):
    client = _client(administrator)
    old_full = filed.fingerprint.upper()
    old = _short(filed.fingerprint)
    _reopen(client, filed)
    _finalize(client, filed)
    text = client.get(_file_url(filed)).content.decode()
    assert f"Taken       {_day(filed.fingerprint_at)}, when the year was finalized again\n" in text
    # The label column is 12 wide, as the four header rows are.
    assert f"As filed    {old}, taken {TAKEN}\n" in text
    assert f"As filed    {old_full}\n" in text
    assert "fingerprint" not in text.lower()


# -- Who may press it, and what it writes ----------------------------------------------------------------------------


def test_a_viewer_reads_the_card_downloads_and_presses_check_for_changes(filed, viewer):
    client = _client(viewer)
    page = _detail(client, filed)
    text = _visible(_card(page))
    assert text.startswith(HEADING) and "Check for changes" in text and "Download a copy to keep" in text
    assert client.get(_file_url(filed)).status_code == 200
    assert _answer(client, filed) == NO_CHANGES
    assert NO_CHANGES in _visible(_card(_pressed(client, filed)))


def test_check_for_changes_writes_no_record_even_when_it_finds_changes(d1, filed, administrator):
    _correct_level(d1, administrator)
    _sql(METERS)
    before = (ReportingPeriodEvent.objects.count(), ReportingPeriod.objects.values_list(
        "fingerprint", "fingerprint_at", "fingerprint_parts").get(pk=filed.pk))
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pghistory_context")
        contexts = cursor.fetchone()[0]
    client = _client(administrator)
    assert "Look at: meter readings" in _answer(client, filed)
    _pressed(client, filed)
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pghistory_context")
        assert cursor.fetchone()[0] == contexts
    after = (ReportingPeriodEvent.objects.count(), ReportingPeriod.objects.values_list(
        "fingerprint", "fingerprint_at", "fingerprint_parts").get(pk=filed.pk))
    assert after == before


# -- The one new rule in app.css ---------------------------------------------------------------------------------------------


def test_the_head_row_class_and_the_warning_colour_have_rules_made_of_tokens():
    css = (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text()
    head = re.search(r"\.year-changes-head\s*\{([^}]*)\}", css)
    assert head, "app.css has no rule for .year-changes-head"
    assert "flex-wrap: wrap" in head.group(1)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\d\s*px\b|rgb\(", head.group(1)), head.group(1)
    warning = re.search(r"\.text-warning\s*\{([^}]*)\}", css)
    assert warning, "app.css has no rule for .text-warning"
    rule = re.sub(r"/\*.*?\*/", "", warning.group(1), flags=re.S)  # comments aside
    assert re.fullmatch(r"\s*color:\s*var\(--color-warning\);\s*", rule), rule
