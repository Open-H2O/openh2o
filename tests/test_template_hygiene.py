# SPDX-License-Identifier: AGPL-3.0-or-later
"""The mechanical half of DESIGN.md, enforced.

DESIGN.md writes down house rules for the markup. Most of them are judgement
calls a test cannot hold. A few are not -- they are string-level facts about the
templates, and those are exactly the ones that rot quietly, because the way they
break is by someone copying a neighbouring block that predates the rule. This
file pins that few.

Each guard names the rule it enforces and the defect it prevents. A guard that
cannot say what breaks when it is violated does not belong here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
APP_CSS = ROOT / "static/css/app.css"


def _templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def _offenders(needle):
    """Every ``path:line`` in the templates carrying ``needle``."""
    found = []
    for path in _templates():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if needle in line:
                found.append(f"{path.relative_to(ROOT)}:{number}")
    return found


class TestDeveloperNotesStayOutOfThePage:
    """DESIGN.md rule 10 -- multi-line template comments use ``{% comment %}``.

    An ``<!-- -->`` comment is served to every visitor. The notes in this
    codebase are long, candid, and internal: they cite issue numbers, name the
    people who reported a defect, and quote review sessions verbatim. Phase 105
    found thirty-seven of them shipping on the live site, one of which carried a
    reviewer's name and a direct quotation into the public HTML of every station
    list page. ``{% comment %}`` is stripped by the template engine and costs
    nothing.

    Single-line ``<!-- Toolbar -->`` section markers are deliberately allowed;
    they are structural signposts, not prose, and the rule says multi-line.
    """

    def test_no_template_ships_a_multi_line_html_comment(self):
        offenders = []
        for path in _templates():
            for match in re.finditer(r"<!--.*?-->", path.read_text(), re.S):
                if "\n" in match.group(0):
                    line = path.read_text()[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(TEMPLATES_DIR.parent)}:{line}")
        assert not offenders, (
            "these multi-line comments are served to visitors; wrap them in "
            f"{{% comment %}} instead: {offenders}"
        )

    def test_no_template_ships_a_multi_line_django_comment(self):
        """``{# #}`` cannot span lines, and the overflow becomes body text.

        Worse than the HTML-comment case above, because it is not hidden in the
        source: everything after the first newline renders as visible prose on
        the page. `templates/account/signup.html` shipped that way to
        openh2o.com — a note about the accent palette printed under the "Create
        account" button, in the page, for every visitor. Found 2026-08-05 by
        screenshotting the page rather than reading the template. Multi-line
        needs ``{% comment %}``.
        """
        offenders = []
        for path in _templates():
            text = path.read_text()
            for match in re.finditer(r"\{#.*?#\}", text, re.S):
                if "\n" in match.group(0):
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(TEMPLATES_DIR.parent)}:{line}")
        assert not offenders, (
            "Django's {# #} comment is single-line only — everything after the "
            "first newline renders as visible text on the page. Use "
            f"{{% comment %}}...{{% endcomment %}}: {offenders}"
        )


class TestOneBadgeSystem:
    """There is one badge vocabulary, and it is ``.badge``.

    ``.health-status-badge-{green,yellow,red}`` was a second, parallel system
    for the same semantic — a coloured status chip. Two systems for one thing is
    how a page ends up with two shades of "warning" side by side, and how the
    datasync status pill came to reach for the GREEN class and then inline-style
    a gold over the top of it. The dot that made the old system worth having is
    now the ``.badge-dot`` modifier, which draws it in ``currentColor`` and so
    works for every colour.
    """

    def test_the_retired_health_badge_classes_are_gone(self):
        assert not _offenders("health-status-badge"), (
            "use `.badge .badge-dot .badge-{green,amber,red}` instead: "
            f"{_offenders('health-status-badge')}"
        )


class TestNoPreDeepWaterGold:
    """California Gold moved from ``#E4A317`` to ``#E0A446`` in the Deep-Water
    palette. Rules written before that hold the old value literally, so they did
    not move with it — five templates were still painting the previous gold on
    live pages months later, and one of them was a status pill inline-styled
    over a green badge class.

    ``--color-entity-gold`` in tokens.css keeps ``#E4A317`` deliberately: map
    layer identity is a cartographic decision, exempt from the app palette and
    documented as such. This guard is therefore scoped to the templates and to
    app.css, which is where the leaks were.
    """

    def test_no_template_hardcodes_the_old_gold(self):
        for needle in ("rgba(228,163,23", "rgba(228, 163, 23", "#E4A317"):
            offenders = [o for o in _offenders(needle) if "map" not in o.lower()]
            assert not offenders, (
                f"{needle} is the pre-Deep-Water gold; use var(--color-gold) "
                f"or a `.badge-gold`/`.honesty-note` class: {offenders}"
            )

    def test_app_css_carries_no_literal_old_gold(self):
        # Comments are stripped as BLOCKS, not by line prefix: the note recording
        # why this sweep happened quotes the old value mid-sentence, and a
        # prefix test would read that quotation as a live rule.
        source = re.sub(r"/\*.*?\*/", "", APP_CSS.read_text(), flags=re.S)
        assert "#E4A317" not in source and "228,163,23" not in source


class TestEmptyValuesAreWorded:
    """The em-dash sweep reached the ``default:"—"`` filter sites. Nine more
    were spelled as an ``{% else %}`` branch holding a literal dash, which the
    filter guard in tests/test_placeholders.py cannot see. Same defect, same
    wording, so it gets the same gate."""

    def test_no_template_renders_a_bare_em_dash_as_a_value(self):
        offenders = []
        for path in _templates():
            text = path.read_text()
            stripped = re.sub(
                r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", text, flags=re.S
            )
            if ">—<" in stripped:
                offenders.append(str(path.relative_to(ROOT)))
        assert not offenders, (
            "an empty value needs wording, not a dash — use the `blank` filter "
            f"or a `.value-empty` span: {offenders}"
        )


class TestGroupedTableBracketHeaderIsCentred:
    """Brent's ruling, 2026-09-13 18:24 PDT (143-07 staging checkpoint,
    `/map/zones/2/`'s Available bracket): a grouped table's bracket header
    sits CENTRED over its bracket. It had been moved left at 14:01 the same
    day on his first read (commit ``69978e3``) and ruled back on staging
    ("center the word available and we'll just move on"). Platform-wide on
    ``.data-table--grouped th.th-group-label``; the dashboard's Supplies /
    Groundwater budget headers follow it.
    """

    def test_the_bracket_header_rule_is_centred_not_left(self):
        source = re.sub(r"/\*.*?\*/", "", APP_CSS.read_text(), flags=re.S)
        match = re.search(
            r"\.data-table--grouped th\.th-group-label\s*\{([^}]*)\}", source
        )
        assert match, ".data-table--grouped th.th-group-label has no rule in app.css"
        assert "text-align: center" in match.group(1), (
            "the bracket header is not ruled text-align: center"
        )
        assert "text-align: left" not in match.group(1)


class TestEngineSentenceLivesOnlyInTheEngine:
    """143-11 (ISS-170): the ledger's engine-written sentences live in
    `accounting/ledger_words.py` and are printed unchanged from
    `entry.description`; no template composes or overrides one. Before this
    plan, `_ledger_list_results.html` carried a display-time override that
    hard-coded the zero-row sentence for a `calculated` row at 0.0000 AF
    (`{% if entry.amount_acre_feet == 0 and entry.source_type == "calculated" %}`),
    and the comment above it explained the substitution by naming the old
    engine string, "... (calculation engine)". Both are gone: a template
    that reintroduces either is a template composing the ledger's words
    again instead of printing what the engine stored.
    """

    def test_no_template_hardcodes_the_zero_pumping_sentence_or_names_the_engine(self):
        from accounting.ledger_words import NO_PUMPING_DERIVED_WORDS

        sentence_hits = _offenders(NO_PUMPING_DERIVED_WORDS)
        assert not sentence_hits, (
            "the zero-row sentence is engine output (accounting/ledger_words."
            "NO_PUMPING_DERIVED_WORDS); a template must print entry.description, "
            f"never hardcode it: {sentence_hits}"
        )
        engine_hits = _offenders("calculation engine)")
        assert not engine_hits, (
            "a template names the old engine shorthand instead of printing "
            f"the stored description: {engine_hits}"
        )


# -- Every class a template names is a class something defines (ISS-166) ------

CLASS_SOURCES = (
    ROOT / "static/css/app.css",
    ROOT / "static/css/tokens.css",
    ROOT / "static/css/map-engine.css",
    ROOT / "static/css/input.css",
)

# Prefixes that name a behaviour, not a look: a script finds the element by it,
# and no stylesheet is meant to.
UNDEFINED_CLASS_PREFIXES = (
    "js-",  # script hooks (e.g. js-precip-field, js-precip-method on the methodology step)
    "maplibregl-",  # MapLibre GL's own control classes
    "htmx-",  # HTMX's request-state classes
)

# Every class a template names today that none of CLASS_SOURCES defines, each
# with what it is. Built by running this file's own scan on 2026-10-09 (150-04).
# A class lands here only with a reason; a new undefined class fails the test.
UNDEFINED_CLASS_ALLOWLIST = {
    # Tailwind v4 utilities. static/css/input.css holds only the @tailwind
    # directives, and the built static/css/output.css is not in the repository;
    # each of these five is in the output.css staging served on 2026-10-09.
    "block": "Tailwind utility in output.css",
    "flex": "Tailwind utility in output.css",
    "tabular-nums": "Tailwind utility in output.css",
    "text-center": "Tailwind utility in output.css",
    "w-full": "Tailwind utility in output.css",
    # Script state classes, styled inline beside them.
    "chart-range-btn": "script hook: the range buttons in datasync/partials/_station_detail_pane.html",
    "active-range": "script state: the selected range button, same pane, toggled by its script",
    # The feedback widget styles itself in its own <style> block
    # (templates/partials/_feedback_widget.html), not in a stylesheet.
    "oh2o-fb-attach": "feedback widget, its own <style> block",
    "oh2o-fb-cat": "feedback widget, its own <style> block",
    "oh2o-fb-cats": "feedback widget, its own <style> block",
    "oh2o-fb-head": "feedback widget, its own <style> block",
    "oh2o-fb-hint": "feedback widget, its own <style> block",
    "oh2o-fb-hp": "feedback widget, its own <style> block",
    "oh2o-fb-panel": "feedback widget, its own <style> block",
    "oh2o-fb-send": "feedback widget, its own <style> block",
    "oh2o-fb-sub": "feedback widget, its own <style> block",
    "oh2o-fb-thumbs": "feedback widget, its own <style> block",
    "oh2o-fb-x": "feedback widget, its own <style> block",
    "sel": "feedback widget state: the chosen category, its own <style> block and script",
    # No rule anywhere: these do nothing today. Recorded, not fixed, in 150-04
    # (that plan adds no CSS rule beyond its own block).
    "deep-dive-label": "no rule: partials/_deep_dive.html summary label",
    "help-letter-row": "no rule: help/glossary.html letter divider row",
    "receipt": "no rule: accounting/calculation_run_detail.html card (receipt-short and receipt-table are defined)",
    "search-results-inner": "no rule: partials/_search_results.html list wrapper",
    "mb-lg": "no rule: accounting/dashboard.html; mb-sm and mb-md exist, mb-lg does not",
    "mb-xs": "no rule: geography/partials/_zone_detail_pane.html; mb-sm and mb-md exist, mb-xs does not",
}

_CLASS_ATTR = re.compile(r"""(?<![\w:-])class\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_CLASS_NAME = re.compile(r"^-?[_a-zA-Z][\w-]*$")
_DYNAMIC = "\x00"


def _defined_classes():
    """Every class a selector in CLASS_SOURCES names. Comments go first, as
    blocks, so a class quoted in a note does not count as defined."""
    found = set()
    for path in CLASS_SOURCES:
        source = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
        for prelude in re.findall(r"([^{};]*)\{", source):
            found.update(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", prelude))
    return found


def _template_classes():
    """{class: {template, ...}} for every class named in a ``class="..."``.

    Developer notes are stripped first. A ``{% if %}`` inside the attribute
    contributes the classes it can add; a class built from ``{{ }}`` (e.g.
    ``freshness-dot--{{ item.freshness }}``) is dynamic and is skipped, since
    no static scan can name it.
    """
    uses = {}
    for path in _templates():
        text = path.read_text()
        text = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", text, flags=re.S)
        text = re.sub(r"\{#.*?#\}", "", text)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text = re.sub(r"\{\{.*?\}\}", _DYNAMIC, text, flags=re.S)
        text = re.sub(r"\{%.*?%\}", " ", text, flags=re.S)
        for match in _CLASS_ATTR.finditer(text):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            for token in value.split():
                if _DYNAMIC in token or not _CLASS_NAME.match(token):
                    continue
                uses.setdefault(token, set()).add(str(path.relative_to(ROOT)))
    return uses


class TestEveryTemplateClassIsDefined:
    """ISS-166: four classes (`font-semibold`, `text-primary`, `row-clickable`,
    `form-stack`) were named in eighteen templates and defined nowhere, so each
    did nothing and the page looked as though it did. 150-04 defined the first
    three and removed the fourth. This guard fails on the next one: a class in a
    template's ``class`` attribute must be defined in a stylesheet, carry a
    behaviour prefix, or sit in the allowlist above with its reason.
    """

    def test_no_template_names_an_undefined_class(self):
        defined = _defined_classes()
        offenders = {
            name: sorted(paths)
            for name, paths in _template_classes().items()
            if name not in defined
            and name not in UNDEFINED_CLASS_ALLOWLIST
            and not name.startswith(UNDEFINED_CLASS_PREFIXES)
        }
        assert not offenders, (
            "these classes are named in a template and defined in no stylesheet, "
            "so they do nothing; define them in static/css/app.css, use a class "
            "that exists, or allowlist them with a reason: "
            f"{offenders}"
        )

    def test_the_allowlist_holds_only_live_undefined_classes(self):
        """An entry whose class is now defined, or no longer used, is stale; a
        stale allowlist stops saying what is actually undefined."""
        defined = _defined_classes()
        used = _template_classes()
        stale = sorted(
            name for name in UNDEFINED_CLASS_ALLOWLIST
            if name in defined or name not in used
        )
        assert not stale, f"remove these allowlist entries: {stale}"
