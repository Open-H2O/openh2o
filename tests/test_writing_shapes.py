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

The "district reader" and "California" shapes joined on 2026-10-11 (150.4-01),
after Brent asked for OpenH2O to read nationally and for any reader, not only a
district. Replayed against f4b18da first: templates caught 48 of the recount's
49 district-reader lines and 3 of its 4 generic-California lines (the misses
sit inside ``<script>``); the numbers and every miss are in
.planning/phases/150.4-national-role-neutral-tone-pass/150.4-01-REPLAY.md.

The other three shapes (a phrase posing as a statement, a thing acting like a
person, a slogan) need a reader and are not counted here.

**Kill switch:** ``OPENH2O_WRITING_SHAPES_CHECK=0`` skips this module.
"""
from __future__ import annotations

import importlib.util
import os
import re
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
    "templates/accounting/partials/_needs_attention.html": {"em dash": 1},
    "templates/reporting/partials/_openet_prefill.html": {"em dash": 1},
    "templates/reporting/partials/_report_detail_pane.html": {"em dash": 1, "stand-in": 1, "negation frame": 1},
    "templates/reporting/report_list.html": {"em dash": 1},
    "templates/reporting/report_prefill.html": {"em dash": 2},
    "accounting/ledger_words.py": {"em dash": 1},
    "accounting/views.py": {"em dash": 2, "negation frame": 3},
    "core/models.py": {"em dash": 1, "negation frame": 2},
    "reporting/generators.py": {"em dash": 2, "negation frame": 2},
    "reporting/validators.py": {"em dash": 16, "negation frame": 2},
    "reporting/views.py": {"em dash": 1},
    "DEPLOY.md": {"em dash": 124, "filler": 22, "stand-in": 3, "district reader": 27, "reassurance": 13, "negation frame": 38, "bold verdict": 27},
    "docs/AI-OPERATOR-GUIDE.md": {"filler": 11, "paired heading": 1, "stand-in": 1, "district reader": 40, "California": 1, "reassurance": 8, "negation frame": 22, "bold verdict": 13},
    "docs/DATA-IMPORT.md": {"double hyphen": 8, "filler": 2, "stand-in": 1, "district reader": 5, "negation frame": 11, "bold verdict": 1},
    "docs/DATA-STANDARDS.md": {"em dash": 12, "filler": 1, "stand-in": 1, "district reader": 4, "reassurance": 2, "negation frame": 8, "bold verdict": 1},
    "docs/INSTALL-WITHOUT-DOCKER.md": {"em dash": 41, "filler": 7, "paired heading": 3, "stand-in": 3, "district reader": 7, "reassurance": 4, "negation frame": 13, "bold verdict": 20},
    "docs/ROADMAP.md": {"em dash": 14, "filler": 3, "district reader": 3, "California": 1, "reassurance": 1, "negation frame": 2},
    "docs/water-budget-terms.md": {"filler": 1, "district reader": 2, "negation frame": 6},
    # 2026-10-11: the "district reader" and "California" shapes joined at their
    # counts that day (150.4-01). 150.4-02, 150.1-02 and 150.1-03 lower them.
    "templates/about.html": {"district reader": 1},
    "templates/parcels/partials/_detail_pane.html": {"district reader": 1, "negation frame": 2},
    "templates/reporting/partials/_handoff.html": {"district reader": 1},
    "templates/reporting/partials/_status_section.html": {"district reader": 3},
    "templates/surface/partials/_diversion_import_preview.html": {"California": 1},
    # 2026-10-17: the reassurance, negation-frame and bold-verdict shapes joined
    # at their counts that day (150.1-03, Brent 13:32 PDT). The guides' rewrites lower them.
    "templates/404.html": {"negation frame": 1},
    "templates/accounting/partials/_methodology_preview.html": {"negation frame": 1},
    "templates/drinking/partials/_facility_results.html": {"negation frame": 1},
    "templates/drinking/partials/_onboard_review.html": {"negation frame": 2},
    "templates/partials/_map_card_head.html": {"negation frame": 1},
    "templates/reporting/partials/_report_actions.html": {"negation frame": 1},
    "templates/surface/diversion_import.html": {"negation frame": 1},
    "templates/surface/partials/_detail_pane.html": {"negation frame": 1},
    "templates/surface/partials/_diversion_records.html": {"negation frame": 1},
    "config/views.py": {"negation frame": 2},
    "drinking/views.py": {"negation frame": 1},
    "health/checks.py": {"negation frame": 2},
    "infrastructure/views.py": {"negation frame": 1},
}

_ADVICE = (
    "An em dash or double hyphen becomes a colon, a comma, a full stop or "
    "parentheses. A filler word comes out. A heading in two clauses becomes one "
    "plain question or one plain statement (DESIGN.md copy rule 15). A district "
    "reader names who really acts (\"An administrator can\", \"unless an "
    "administrator changes it\", \"the area you manage water for\"); a general "
    "\"California\" says the general thing (DESIGN.md copy rule 11)."
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


# -- District reader and California (150.4-01) --------------------------------

def test_a_planted_district_reader_is_caught_on_every_surface():
    """The sentences Brent's 2026-10-11 20:36 PDT approval replaced, as they read."""
    template = (
        "<td>A district can reorder those steps or switch any of them off.</td>"
        "<td>75 percent unless the district changes it.</td>"
        "<p>Give the Setup Wizard your district&rsquo;s boundary.</p>"
        '<input placeholder="District name">'
    )
    assert _template(template)["district reader"] == 4
    python = 'HELP = "These agency-wide settings apply to the whole agency."\n'
    assert shapes.count_file("planted.py", python)["district reader"] == 2
    guide = "Ask your agency for an account.\n"
    assert shapes.count_file("planted.md", guide)["district reader"] == 1


def test_the_approved_replacements_carry_no_district_reader():
    approved = (
        "<td>An administrator can reorder those steps or switch any of them off.</td>"
        "<td>75 percent unless an administrator changes it.</td>"
        "<td>An administrator or operator sets an allocation ceiling on Allocations.</td>"
        "<p>Give the Setup Wizard the boundary of the area you manage water for.</p>"
        "<p>OpenH2O is for anyone who keeps water records, anywhere in the United States: "
        "engineers and managers at water agencies and districts, growers, ditch tenders "
        "and drinking-water system operators.</p>"
    )
    assert _template(approved)["district reader"] == 0


def test_a_district_or_agency_in_the_water_world_is_not_a_reader():
    entity = (
        "<p>The regulating agency was recorded from the file.</p>"
        "<p>State classification and regulating agency. OpenH2O fills a blank regulating agency from the Regulating Agency column of an imported lab file.</p>"
        "<p>not for the agency that regulates it.</p>"
        "<p>Pick an area, such as the land an irrigation district serves.</p>"
        "<p>the local agency responsible for managing groundwater under SGMA.</p>"
    )
    assert _template(entity)["district reader"] == 0


def test_a_planted_generic_california_is_caught_on_every_surface():
    assert _template("<p>Decimal degrees inside California.</p>")["California"] == 1
    python = 'MESSAGE = "outside the expected California range."\n'
    assert shapes.count_file("planted.py", python)["California"] == 1
    guide = "a platform a California water agency can stand up\n"
    assert shapes.count_file("planted.md", guide)["California"] == 1


def test_a_california_proper_name_is_not_counted():
    names = (
        "<p>California Data Exchange Center, real-time data.</p>"
        "<p>the California law requiring groundwater management.</p>"
        "<p>ELAP is California's Environmental Laboratory Accreditation Program.</p>"
    )
    assert _template(names)["California"] == 0


def _every_text_read():
    texts = []
    for files in shapes.surfaces().values():
        for rel in files:
            source = (REPO_ROOT / rel).read_text()
            if rel.endswith(".html"):
                texts.extend(shapes.template_text(source)[0])
            elif rel.endswith(".py"):
                texts.extend(shapes.python_strings(source))
            else:
                texts.extend(shapes.guide_text(source)[0])
    return "\n".join(texts)


def test_every_kept_name_and_phrase_is_still_used():
    """A kept name no page uses any more would let a generic one through later."""
    text = _every_text_read()
    stale = [
        name for name, _ in shapes.CALIFORNIA_NAMES + shapes.DISTRICT_ENTITY
        if not re.search(name, text, re.I)
    ]
    assert not stale, (
        "these kept names match nothing the scanner reads; take them out of "
        "CALIFORNIA_NAMES or DISTRICT_ENTITY in scripts/writing_shapes.py: "
        + "; ".join(stale)
    )


# -- The three shapes added on 2026-10-17 (Brent: "the AI Slop langugae") ------

def test_brents_struck_readme_line_is_caught():
    struck = "**A new installation holds none of your records.** It starts empty.\n"
    counts = shapes.count_file("docs/planted.md", struck)
    assert counts["bold verdict"] == 1
    assert counts["negation frame"] == 1


def test_a_planted_reassurance_is_caught():
    assert _template("<p>The refusal to start is deliberate.</p>")["reassurance"] == 1


def test_a_planted_negation_frame_is_caught():
    assert _template("<p>The site sends mail through a provider instead of its own server.</p>")[
        "negation frame"] == 1


def test_an_approved_sentence_is_not_a_bold_verdict():
    approved = "The demonstration uses a real California basin.\n"
    assert shapes.count_file("docs/planted.md", approved)["bold verdict"] == 0
