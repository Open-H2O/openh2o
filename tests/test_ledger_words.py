# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards for `accounting/ledger_words.py` (143-11, ISS-170).

Two things this module owes a reader, pinned here:

1. `delivery_share_words` composes the Description sentence for a surface
   allocation row correctly — the figure, the return-flow clause, the
   fixed-share tail, and the POD name — with NO database (an unsaved record
   and an unsaved POD are enough; the function only reads attributes and
   calls `consumed_acre_feet()`, which is pure Decimal arithmetic).
2. Every sentence a reader sees scans clean under the two vocabulary gates
   this codebase already runs against templates: `tests/test_domain_vocabulary
   .py::scan` (never define the water) and `core/water_vocabulary.py`'s
   `load_rules` (DESIGN.md's one-name-per-quantity table). A sentence
   written once, here, and read from templates thereafter has to pass both
   the same as any template would.
"""

from decimal import Decimal

import pytest

from accounting.ledger_words import (
    DELIVERY_SHARE_BY_FIXED,
    DELIVERY_SHARE_BY_USE,
    INCIDENTAL_RECHARGE_WORDS,
    LEGACY_INCIDENTAL_RECHARGE_WORDS,
    NO_PUMPING_DERIVED_WORDS,
    PUMPING_ESTIMATE_WORDS,
    delivery_share_words,
)
from surface.models import DiversionRecord, PointOfDiversion

# -- test doubles, unsaved on purpose: delivery_share_words touches no DB ---


def _record(volume, returned, diversion_type="direct_use"):
    return DiversionRecord(
        volume_acre_feet=Decimal(volume),
        returned_af=Decimal(returned),
        diversion_type=diversion_type,
    )


def _pod(name):
    return PointOfDiversion(name=name)


STEVINSON = "MER-POD-006-DEMO Stevinson Diversion Canal Headgate"


class TestDeliveryShareWordsFigureAndVerb:
    def test_figure_is_consumed_acre_feet_two_decimal_thousands_separator(self):
        record = _record("1234.5678", "0")  # consumed == 1234.5678 -> 1,234.57
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert "1,234.57 AF" in sentence
        assert "1234.5678" not in sentence  # never the model's 4dp

    def test_verb_is_delivered_from_for_direct_use(self):
        record = _record("10", "0", diversion_type="direct_use")
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert "delivered from Plain Canal Headgate" in sentence

    def test_verb_is_taken_to_storage_from_for_to_storage(self):
        record = _record("10", "0", diversion_type="to_storage")
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert "taken to storage from Plain Canal Headgate" in sentence


class TestDeliveryShareWordsReturnFlowClause:
    def test_present_for_a_partial_return(self):
        # returned_af (40) strictly between 0 and volume (100).
        record = _record("100", "40")
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert "after 40.00 AF of the 100.00 AF diverted was returned" in sentence

    def test_absent_for_zero_return(self):
        record = _record("100", "0")
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert "returned to the stream" not in sentence

    def test_absent_for_a_full_passthrough(self):
        # returned_af == volume: the hydropower boundary, not a partial return.
        record = _record("100", "100")
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert "returned to the stream" not in sentence


class TestDeliveryShareWordsTail:
    def test_by_use_form_closes_with_the_use_area_tail(self):
        record = _record("10", "0")
        sentence = delivery_share_words(record, _pod("Plain Canal Headgate"))
        assert sentence.endswith(DELIVERY_SHARE_BY_USE)

    def test_fixed_share_form_prints_percentage_and_no_estimated_use_tail(self):
        record = _record("10", "0")
        sentence = delivery_share_words(
            record, _pod("Plain Canal Headgate"), fixed_share=Decimal("0.2000")
        )
        assert f"{DELIVERY_SHARE_BY_FIXED} (20%)" in sentence
        assert sentence.endswith("no estimated use on record for the month")


class TestDeliveryShareWordsPodName:
    def test_a_coded_name_carries_the_name_not_the_token(self):
        record = _record("214.5813", "0")
        sentence = delivery_share_words(record, _pod(STEVINSON))
        assert "Stevinson Diversion Canal Headgate" in sentence
        assert "MER-POD-006-DEMO" not in sentence

    def test_a_plainly_named_pod_is_carried_whole(self):
        record = _record("10", "0")
        sentence = delivery_share_words(record, _pod("Bear Creek Diversion"))
        assert "Bear Creek Diversion" in sentence


# ---------------------------------------------------------------------------
# Guard #4: every sentence this module writes scans clean under both
# vocabulary gates the templates that render it are already held to.
# ---------------------------------------------------------------------------


def _public_word_constants():
    """Every public `*_WORDS` name plus the two `DELIVERY_SHARE_*` constants.

    `LEGACY_INCIDENTAL_RECHARGE_WORDS` is excluded: it is the pre-143-11
    sentence, kept only so a re-run can find and replace an agency's old
    rows (never written by new code), and it measurably FAILS
    `test_domain_vocabulary.py::scan` (two offences: "recharge" and
    "percolation", both in a definitional construction) and is excluded
    from this guard for exactly that reason, not by oversight.
    """
    import accounting.ledger_words as lw

    names = [
        name
        for name in dir(lw)
        if name.isupper()
        and not name.startswith("_")
        and not name.startswith("LEGACY_")
        and isinstance(getattr(lw, name), str)
        and (name.endswith("_WORDS") or name.startswith("DELIVERY_SHARE"))
    ]
    assert set(names) == {
        "DELIVERY_SHARE_BY_FIXED",
        "DELIVERY_SHARE_BY_USE",
        "INCIDENTAL_RECHARGE_WORDS",
        "NO_PUMPING_DERIVED_WORDS",
        "PUMPING_ESTIMATE_WORDS",
    }, names  # a constant added later must be taught to this guard, not skip it
    return names


@pytest.mark.parametrize("name", _public_word_constants())
def test_every_sentence_constant_scans_clean_under_the_domain_gate(name):
    """`tests/test_domain_vocabulary.py::scan` — never define the water."""
    from tests.test_domain_vocabulary import scan

    import accounting.ledger_words as lw

    text = getattr(lw, name)
    offences = scan(text)
    assert offences == [], (name, text, offences)


@pytest.mark.parametrize("name", _public_word_constants())
def test_every_sentence_constant_carries_no_gated_phrase(name):
    """DESIGN.md's vocabulary table (rule 12), read live — no cosmetic copy.

    The scope checked is the one template that renders these sentences.
    """
    from pathlib import Path

    import accounting.ledger_words as lw
    from core.water_vocabulary import load_rules

    location = "templates/accounting/partials/_ledger_list_results.html"
    rules = load_rules(Path(__file__).resolve().parent.parent / "DESIGN.md")
    text = getattr(lw, name)
    hits = [rule for rule in rules if rule.applies_to(location) and rule.pattern.search(text)]
    assert hits == [], (name, text, hits)


def test_incidental_recharge_words_constants_are_distinct():
    """The rename left the old and new sentences DIFFERENT strings — a re-run's
    `Q(startswith=OLD) | Q(startswith=NEW)` delete would silently become a
    no-op filter if they ever collided."""
    assert INCIDENTAL_RECHARGE_WORDS != LEGACY_INCIDENTAL_RECHARGE_WORDS


def test_pumping_words_constants_are_distinct():
    assert PUMPING_ESTIMATE_WORDS != NO_PUMPING_DERIVED_WORDS
