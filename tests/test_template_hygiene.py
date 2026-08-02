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
