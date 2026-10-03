# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three sentence shapes Brent has rejected on screen, held where they stand today.

``tests/test_literary_sentence.py`` pins the sentences Brent ruled on
2026-09-17 (138 rows). It cannot catch a NEW sentence written in the same shape. This file
catches three of those shapes mechanically, in the words a template shows:

1. **em dash.** Brent's standing rule is zero em dashes in anything a reader
   sees. In the 143.1 rulings, 63 of the 138 struck sentences carried one and 1
   of the 131 settled sentences did (S-1410, still on the setup progress page).
   Counted only between two words of one run of text (see ``EM_DASH``).
2. **narrative verb**, from the 143.1 fault list (``143.1-01-PLAN.md``): "came
   through", "did beneath", "reads well", "sits", "lands here", "has nowhere to
   be". 5 of the 138 struck sentences matched and 0 of the 131 settled ones.
   ⚠ "stands" is on the 143.1 list and is NOT here: measured 2026-10-03, all six
   "stands" hits on screen and in help text were the plain idioms "stands for",
   "stands as" and "the reading stands", and no struck sentence used it.
3. **contrast**, the two-sentence device "X is not Y. It is Z." The one-sentence
   ", not Y" form is deliberately absent, because Brent SETTLED it ("A missing
   step, not a finding:", S-0453). ⚠ This shape matched 0 templates and 0 of the
   269 ruled sentences when it was installed: it is untested here, not proven.

**A ratchet, not a sweep.** ``BASELINE`` holds each template's count on
2026-10-03. A template may not gain a shape; a template that loses one must have
its ceiling lowered. The existing em dashes are NOT fixed here, because the
words on these pages are Brent's to rule (``test_literary_sentence.py``, rule 8
of the house). The ceilings are the to-do list.

**What it reads.** Template source with comments, ``<script>`` and ``<style>``
removed, entities unescaped (``&mdash;`` is an em dash), ``{{ }}`` figures read as a word,
``{% %}`` tags dropped, and the text of the attributes a reader sees
(``title``, ``placeholder``, ``aria-label``, ``alt``) kept. Table headers are
kept, unlike ``template_prose``, because a header is on screen too. On
2026-10-03 an independent reader graded 103 template sentences carrying an em
dash and found all 103 on screen; this module counts 122 dashes in 50
templates, mostly because some sentences carry two, plus label separators in
five templates ("{{ code }} - {{ name }}"), read by hand. Python strings (help_text,
health-check messages) are NOT read: 19 of the 32 Python em-dash hits that
reader graded reach only the Django admin.

**Replayed before installing.** Over the 58 template commits between the 143.1
rulings (2026-09-18) and 2026-10-03, this ratchet would have failed twice: 146-04
added five em dashes to the new drinking-water production pages, and 148-03
added the narrative verb on ``help/methods.html`` that ``BASELINE`` now holds.

**Kill switch:** ``OPENH2O_SCREEN_TEXT_CHECK=0`` skips this module.
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_SCREEN_TEXT_CHECK", "1") == "0",
    reason="OPENH2O_SCREEN_TEXT_CHECK=0",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "templates"

#: Between two words of one run of text. A lone dash in a table cell, or the
#: decoration around "Choose a boundary", is a glyph rather than a sentence, and
#: Phase 105's placeholder guard (``test_placeholders.py``) owns that question.
EM_DASH = re.compile(r"[^\s—][^\S\n]*—[^\S\n]*(?=[^\s—])")
NARRATIVE = re.compile(
    r"\b(?:c(?:ame|omes?) through|did beneath|reads? well|sits"
    r"|land(?:s|ed)? (?:here|there)|nowhere to)\b", re.I)
CONTRAST = re.compile(
    r"\b(?:is|are|was|were)(?: not|n't)\b[^.\n;]{1,80}\.[^\S\n]+"
    r"(?:It|This|That|They)(?:'s| is| was| are|'re)\b")
SHAPES = {"em dash": EM_DASH, "narrative verb": NARRATIVE, "contrast": CONTRAST}

_NOT_COPY = (
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<script.*?</script>", re.S),
    re.compile(r"<style.*?</style>", re.S),
)
_SEEN_ATTR = re.compile(r"""\b(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)\"""")
#: Tags that sit inside a sentence. Every other tag ends a run of text, so two
#: table cells, two list items or two options never read as one sentence.
_INLINE = re.compile(
    r"</?(?:a|abbr|b|bdi|cite|code|data|dfn|em|i|kbd|mark|q|s|small|span|strong"
    r"|sub|sup|time|u|var|wbr)\b[^>]*>", re.I)
#: An alternative arm: "Present{% elif %}Absent{% else %}-" is three runs, never
#: one sentence. An ``{% if %}`` that adds a suffix ("CA-001{% if %} - Well 3")
#: stays inside its run, because on screen it is one label.
_BRANCH = re.compile(r"\{%\s*(?:elif|else|empty)\b.*?%\}", re.S)


def visible(source: str) -> str:
    """The words a template can put on screen, one run of text per line."""
    for pattern in _NOT_COPY:
        source = pattern.sub(" ", source)
    source = " ".join(source.split())  # a line break in the source is not one on screen
    source = re.sub(r"\{\{.*?\}\}", " X ", source, flags=re.S)  # a figure is a word
    source = _BRANCH.sub("\n", source)
    source = re.sub(r"\{%.*?%\}", " ", source, flags=re.S)
    source = _SEEN_ATTR.sub(lambda m: ">\n" + m.group(1) + "\n<", source)
    source = _INLINE.sub(" ", source)
    source = re.sub(r"<[^>]+>", "\n", source)
    runs = (" ".join(html.unescape(run).split()) for run in source.split("\n"))
    return "\n".join(run for run in runs if run)


def counts(text: str) -> dict:
    return {shape: len(pattern.findall(text)) for shape, pattern in SHAPES.items()}


def measured() -> dict:
    """{shape: {template: count}} for every template carrying the shape."""
    out = {shape: {} for shape in SHAPES}
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = str(path.relative_to(REPO_ROOT))
        for shape, n in counts(visible(path.read_text())).items():
            if n:
                out[shape][rel] = n
    return out


#: Ceilings on 2026-10-03: 122 em dashes in 50 templates, one narrative verb.
#: Lower one when a template loses a shape; never raise one. ⚠ The one narrative
#: verb ("a field with no such zone has nowhere to credit it", help/methods.html)
#: arrived with the 148-03 page Brent passed at its checkpoint; it is his to rule.
BASELINE: dict = {
    "em dash": {
        "templates/about.html": 10,
        "templates/about_demonstration_data.html": 3,
        "templates/accounting/dashboard.html": 1,
        "templates/accounting/methodology_settings.html": 2,
        "templates/accounting/partials/_methodology_preview.html": 1,
        "templates/accounting/partials/_needs_attention.html": 1,
        "templates/allauth/layouts/base.html": 1,
        "templates/base.html": 1,
        "templates/base_auth.html": 1,
        "templates/core/user_form.html": 1,
        "templates/datasync/monitoring_dashboard.html": 1,
        "templates/datasync/partials/_monitoring_content.html": 2,
        "templates/datasync/station_add.html": 1,
        "templates/drinking/facilities.html": 1,
        "templates/drinking/facility_detail.html": 2,
        "templates/drinking/import.html": 1,
        "templates/drinking/onboard.html": 1,
        "templates/drinking/onboard_points.html": 2,
        "templates/drinking/overview.html": 4,
        "templates/drinking/partials/_empty_drinking.html": 1,
        "templates/drinking/partials/_import_preview.html": 4,
        "templates/drinking/partials/_onboard_points_form.html": 1,
        "templates/drinking/partials/_onboard_points_listed.html": 3,
        "templates/drinking/partials/_onboard_result.html": 2,
        "templates/drinking/partials/_onboard_review.html": 4,
        "templates/drinking/partials/_production_import_preview.html": 2,
        "templates/drinking/partials/_result_results.html": 1,
        "templates/drinking/partials/_sampling_point_results.html": 1,
        "templates/drinking/production.html": 2,
        "templates/drinking/production_form.html": 1,
        "templates/drinking/result_detail.html": 4,
        "templates/drinking/sampling_point_detail.html": 1,
        "templates/help/budgets_allocations.html": 7,
        "templates/help/getting_started.html": 6,
        "templates/help/settings_explained.html": 8,
        "templates/help/surface_deliveries.html": 7,
        "templates/help/water_balances.html": 4,
        "templates/infrastructure/partials/_import_mapping.html": 2,
        "templates/infrastructure/partials/_import_result.html": 1,
        "templates/partials/_demo_marker.html": 1,
        "templates/partials/_header.html": 1,
        "templates/reporting/partials/_handoff.html": 2,
        "templates/reporting/partials/_openet_prefill.html": 4,
        "templates/reporting/partials/_status_section.html": 2,
        "templates/reporting/report_list.html": 1,
        "templates/reporting/report_prefill.html": 2,
        "templates/setup/partials/_progress.html": 5,
        "templates/setup/partials/_station_review.html": 1,
        "templates/setup/partials/_step_result.html": 1,
        "templates/surface/partials/_detail_pane.html": 3,
    },
    "narrative verb": {
        "templates/help/methods.html": 1,
    },
    "contrast": {},
}


def test_no_template_gains_a_shape():
    now = measured()
    gained = [
        f"{rel} {shape}: {BASELINE[shape].get(rel, 0)} -> {n}"
        for shape in SHAPES for rel, n in now[shape].items()
        if n > BASELINE[shape].get(rel, 0)
    ]
    assert not gained, (
        "these templates gained a shape Brent has rejected on screen. An em dash "
        "becomes a colon, a comma, a full stop or parentheses; a narrative verb "
        "becomes the plain verb or the noun phrase that names the thing; 'X is "
        "not Y. It is Z.' becomes the statement of Z. Never raise BASELINE to "
        "pass: " + "; ".join(gained)
    )


def test_every_ceiling_is_tight():
    """A ratchet with slack lets a shape come back where one was removed."""
    now = measured()
    slack = [
        f"{rel} {shape}: ceiling {ceiling}, now {now[shape].get(rel, 0)}"
        for shape in SHAPES for rel, ceiling in BASELINE[shape].items()
        if now[shape].get(rel, 0) < ceiling
    ]
    assert not slack, (
        "these templates lost a shape. Lower (or delete) their BASELINE entry "
        "to the new count: " + "; ".join(slack)
    )


# -- The controls ------------------------------------------------------------

def test_each_shape_is_caught_when_planted():
    planted = (
        '<p class="text-secondary">Readings are flagged &mdash; check the meter.</p>'
        '<p title="What came through the meter">x</p>'
        "<p>The residual is not spare water. It is a gap in the records.</p>"
    )
    assert counts(visible(planted)) == {"em dash": 1, "narrative verb": 1, "contrast": 1}


def test_settled_wording_and_non_copy_stay_silent():
    """Brent's own settled shapes, and text no reader sees, must not fire."""
    silent = (
        "{# What came through the meter — a comment #}"
        "{% comment %}it sits here — not copy{% endcomment %}"
        "<!-- — --><script>var a = 'x — y';</script><style>/* — */</style>"
        '{{ value|default:"—" }}'
        "<p>A missing step, not a finding: water may still have been consumed.</p>"
        "<p>ET is estimated crop water use, not metered pumping or diversion.</p>"
        "<p>Which real thing this account stands for.</p>"
    )
    assert counts(visible(silent)) == {"em dash": 0, "narrative verb": 0, "contrast": 0}
