# SPDX-License-Identifier: AGPL-3.0-or-later
"""The struck sentence shapes a machine can see may only go down.

Brent ruled on 2026-10-09 at 18:45 PDT that the shapes he has struck are to be
fixed everywhere. DESIGN.md copy rule 15 names seven. ``scripts/writing_shapes.py``
counts the four a pattern can find: an em dash or a double hyphen between two
words, the filler words (actually, genuinely, really, simply), a heading made
of two clauses joined by ", and what", and a heading ending in ", by what". It
reads every template (including the words passed into included partials), the
Python files whose strings reach a screen, and the public guides.

``BASELINE`` holds each file's count on 2026-10-09. A file may not gain a
shape. A file that loses one must have its entry lowered in the same commit,
so the table always states the truth. The counts are the to-do list for the
rest of the writing work, and they reach zero when it is done.

Before it was installed the scanner was run against the history: the About
page at the commit before d247786 counts no paired heading, and at d247786 it
counts three ("What OpenH2O is, and who it is for"; "What it owes to the
Groundwater Accounting Platform, and what is its own"; "Who made it, and where
the code is"), the headings that started this work. The stand-in shape ("that platform",
"both are") was replayed the same way on 2026-10-10: About counts 0 at
3cbe34c, 2 at 017c89d and at fbe4f47 (the two versions Brent struck for it)
and 0 after his sentence went in.

The other three shapes (a phrase posing as a statement, a thing acting like a
person, a slogan) need a reader and are not counted here.

**Kill switch:** ``OPENH2O_WRITING_SHAPES_CHECK=0`` skips this module.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_WRITING_SHAPES_CHECK", "1") == "0",
    reason="OPENH2O_WRITING_SHAPES_CHECK=0",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "writing_shapes.py"


def _load():
    if not SCRIPT.exists():
        pytest.fail(f"{SCRIPT} is missing; update SCRIPT if it moved.")
    spec = importlib.util.spec_from_file_location("writing_shapes_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shapes = _load()

#: Counts on 2026-10-09, measured on the working tree at the start of the
#: writing work. Lower an entry when its file loses a shape; never raise one.
#: Later the same evening About, the help pages, the footer and the Admin mode
#: button took the wording Brent approved at 20:29 PDT, and their six entries
#: came off. 2026-10-10: the "stand-in" shape joined at its counts that day.
BASELINE: dict = {
    "templates/drinking/partials/_onboard_result.html": {"stand-in": 1},
    "templates/drinking/partials/_empty_drinking.html": {"stand-in": 1},
    "templates/accounting/partials/_account_balances.html": {"em dash": 1},
    "templates/accounting/partials/_needs_attention.html": {"em dash": 1},
    "templates/allauth/layouts/base.html": {"em dash": 1},
    "templates/base_auth.html": {"em dash": 1},
    "templates/core/user_form.html": {"em dash": 1},
    "templates/datasync/station_add.html": {"em dash": 1},
    "templates/drinking/overview.html": {"em dash": 4},
    "templates/drinking/production.html": {"em dash": 1},
    "templates/partials/_demo_marker.html": {"em dash": 1},
    "templates/reporting/partials/_openet_prefill.html": {"em dash": 1},
    "templates/reporting/partials/_report_detail_pane.html": {"em dash": 1, "stand-in": 1},
    "templates/reporting/report_list.html": {"em dash": 1},
    "templates/reporting/report_prefill.html": {"em dash": 2},
    "templates/wells/partials/_detail_pane.html": {"double hyphen": 1},
    "accounting/ledger_words.py": {"em dash": 1},
    "accounting/views.py": {"em dash": 2},
    "core/models.py": {"em dash": 1},
    "datasync/freshness.py": {"em dash": 8},
    "drinking/glossary.py": {"em dash": 1},
    "drinking/ps_codes.py": {"em dash": 1},
    "drinking/views.py": {"em dash": 2, "double hyphen": 2},
    "health/checks.py": {"em dash": 4},
    "infrastructure/views.py": {"em dash": 1},
    "reporting/generators.py": {"em dash": 2},
    "reporting/validators.py": {"em dash": 17},
    "reporting/views.py": {"em dash": 1},
    "setup/boundaries.py": {"em dash": 3},
    "surface/views.py": {"double hyphen": 3},
    "CONTRIBUTING.md": {"em dash": 10},
    "DEPLOY.md": {"em dash": 124, "filler": 22, "stand-in": 3},
    "MAINTAINER.md": {"em dash": 10},
    "README.md": {"em dash": 49, "filler": 3, "stand-in": 4},
    "SECURITY.md": {"em dash": 3},
    "docs/AI-OPERATOR-GUIDE.md": {"filler": 11, "paired heading": 1, "stand-in": 1},
    "docs/DATA-IMPORT.md": {"double hyphen": 8, "filler": 2, "stand-in": 1},
    "docs/DATA-STANDARDS.md": {"em dash": 13, "filler": 1, "stand-in": 1},
    "docs/INSTALL-WITHOUT-DOCKER.md": {"em dash": 41, "filler": 7, "paired heading": 3, "stand-in": 3},
    "docs/README.md": {"em dash": 4},
    "docs/ROADMAP.md": {"em dash": 14, "filler": 3},
    "docs/earth-engine-tier-setup.md": {"em dash": 3, "filler": 5},
    "docs/water-budget-terms.md": {"filler": 2},
}

_ADVICE = (
    "An em dash or double hyphen becomes a colon, a comma, a full stop or "
    "parentheses. A filler word comes out. A heading in two clauses becomes one "
    "plain question or one plain statement (DESIGN.md copy rule 15)."
)


def test_no_file_gains_a_shape():
    gained = [
        f"{rel} {shape}: {BASELINE.get(rel, {}).get(shape, 0)} -> {n}"
        for rel, counts in shapes.measured().items()
        for shape, n in counts.items()
        if n > BASELINE.get(rel, {}).get(shape, 0)
    ]
    assert not gained, (
        "these files gained a sentence shape Brent has struck. " + _ADVICE
        + " Never raise BASELINE to pass: " + "; ".join(gained)
    )


def test_every_baseline_is_tight():
    """A count with slack would let a shape come back where one was removed."""
    now = shapes.measured()
    slack = [
        f"{rel} {shape}: baseline {ceiling}, now {now.get(rel, {}).get(shape, 0)}"
        for rel, counts in BASELINE.items()
        for shape, ceiling in counts.items()
        if now.get(rel, {}).get(shape, 0) < ceiling
    ]
    assert not slack, (
        "these files lost a shape. Lower (or delete) their BASELINE entry to "
        "the new count: " + "; ".join(slack)
    )


def test_every_baseline_file_is_still_read():
    """An entry for a file the scanner no longer reads would never fail."""
    read = {rel for files in shapes.surfaces().values() for rel in files}
    missing = sorted(set(BASELINE) - read)
    assert not missing, f"BASELINE names files the scanner does not read: {missing}"


# -- The controls ------------------------------------------------------------

def _template(source: str) -> dict:
    return shapes.count_file("templates/planted.html", source)


def test_a_planted_paired_heading_is_caught():
    assert _template("<h2>What X is, and what Y is</h2>")["paired heading"] == 1


def test_a_planted_trailing_heading_is_caught():
    assert _template("<h3>How the month ends, by what the field has</h3>")["trailing heading"] == 1


def test_a_page_title_block_is_read_as_a_heading():
    source = "{% block page_title %}Who made it, and where the code is{% endblock %}"
    assert _template(source)["paired heading"] == 1


def test_the_three_about_headings_that_started_this_work_are_caught():
    source = (
        "<h2>What OpenH2O is, and who it is for</h2>"
        "<h2>What it owes to the Groundwater Accounting Platform, and what is its own</h2>"
        "<h2>Who made it, and where the code is</h2>"
    )
    assert _template(source)["paired heading"] == 3


def test_a_planted_em_dash_is_caught_on_every_surface():
    assert _template("<p>Readings are flagged &mdash; check the meter.</p>")["em dash"] == 1
    python = 'MESSAGE = "No rows to import — upload the file again."\n'
    assert shapes.count_file("planted.py", python)["em dash"] == 1
    guide = "The setting is read once\n— at start-up — and kept.\n"
    assert shapes.count_file("planted.md", guide)["em dash"] == 2


def test_a_stand_in_for_a_name_is_caught():
    """The two lines Brent struck on About on 2026-10-10, as they read."""
    source = (
        "<p>OpenH2O was written from scratch in Python and does not use any of "
        "that platform's code.</p>"
        "<td>Both are released under the GNU Affero General Public License.</td>"
    )
    assert _template(source)["stand-in"] == 2


def test_a_planted_double_hyphen_and_filler_word_are_caught():
    counts = _template("<p>It is simply the total -- nothing more.</p>")
    assert (counts["double hyphen"], counts["filler"]) == (1, 1)


def test_the_words_passed_into_an_included_partial_are_read():
    source = '{% include "partials/_explainer_popout.html" with text="The total — as stored." %}'
    assert _template(source)["em dash"] == 1


def test_text_no_reader_sees_stays_silent():
    template = (
        "{# What came through the meter — a comment, really #}"
        "{% comment %}it simply sits here — not copy{% endcomment %}"
        "<!-- — --><script>var a = 'x — y';</script><style>/* — */</style>"
        '{{ value|default:"—" }}<td>—</td>'
        "<p>This page says what it is, and who it is for.</p>"
    )
    assert set(_template(template).values()) == {0}
    python = (
        '"""A docstring — not on a screen, really."""\n'
        'logger.info("synced — %s rows", n)\n'
    )
    assert set(shapes.count_file("planted.py", python).values()) == {0}
    guide = "```\nmake up  # really — a shell comment\n```\n| Code | Unit |\n|---|---|\n| x | — |\n"
    assert set(shapes.count_file("planted.md", guide).values()) == {0}
