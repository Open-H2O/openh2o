# SPDX-License-Identifier: AGPL-3.0-or-later
"""``core.map_labels.map_label`` — the map-label prefix strip (143-07 Step 0).

Brent's Task 3 ruling approved the overview map card with one change: the map
LABEL drops the platform's own composed identifier, front or back, and leaves
a real deployment's plain name untouched. Six cases, matching the shapes named
when this helper was commissioned.

**One deliberate deviation from the commissioning text, noted here rather than
silently:** the leading-token rule requires the token to carry BOTH a digit
and a hyphen (stated three times, against three examples: `MER-POD-004-DEMO`,
`MER-BPOD-001`, `MER-WR-005-DEMO`, all of which have both). The commissioning
text's own em-dash example then asked for `MER` alone (no digit, no hyphen) to
strip as a leading token too, which contradicts that rule as stated — and
would mean ANY all-caps first word strips, including a real name that happens
to start with one. `test_an_em_dash_name_keeps_a_plain_leading_word` here
follows the rule as stated three times, not the contradicting example, and
`map_label` is built to match. Flagged for Brent/the main session rather than
guessed past.
"""

from core.map_labels import map_label


def test_a_leading_code_token_strips():
    assert (
        map_label("MER-POD-004-DEMO Atwater Canal Headgate")
        == "Atwater Canal Headgate"
    )


def test_a_trailing_parenthetical_strips():
    assert (
        map_label("Halvern Irrigation District (MER-WR-004-DEMO)")
        == "Halvern Irrigation District"
    )


def test_both_patterns_strip_together():
    assert (
        map_label("MER-BPOD-001 El Nido Canal Recharge Intake (MER-BPOD-001)")
        == "El Nido Canal Recharge Intake"
    )


def test_neither_pattern_leaves_a_real_name_untouched():
    assert map_label("Atwater Canal Headgate") == "Atwater Canal Headgate"


def test_a_name_that_is_only_a_code_is_never_emptied():
    """Stripping would leave nothing, so the original is kept instead."""
    assert map_label("MER-WR-005-DEMO") == "MER-WR-005-DEMO"


def test_an_em_dash_name_keeps_a_plain_leading_word():
    """The trailing code still strips; `MER` alone is not a leading token.

    `MER` carries no digit and no hyphen, so it fails the leading-token rule
    on its own terms — the same rule that lets `MER-POD-004-DEMO` strip. A
    bare capitalised word is indistinguishable from a real name's first word
    (an agency's own initials, say), so treating it as software's identifier
    would risk cutting the first word off an ordinary name elsewhere in the
    corpus. Task 5 owns the service-area label's own wording and may still
    call this helper as one step in a longer rewrite.
    """
    assert (
        map_label("MER Surface Service Area — Halvern Irrigation District (MER-WR-004-DEMO)")
        == "MER Surface Service Area — Halvern Irrigation District"
    )
