# SPDX-License-Identifier: AGPL-3.0-or-later
"""A station's freshness has one set of three colours, named once.

Up to date, Slightly behind and Dormant were painted from three separate
definitions that did not agree: the row dots in ``app.css`` (Tailwind-default
green, amber and grey), the map's ``FRESH_META`` (the platform's own supply
and warning with an older grey), and the map card's key (tokens). One page
therefore showed a row dot and a map key in different colours for the same
state. ``tokens.css`` now names the three; every consumer reads them.
Modelled on ``test_map_palette_single_source.py``.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = ROOT / "static/css/tokens.css"
APP_CSS = ROOT / "static/css/app.css"
FRESHNESS_MAP = ROOT / "templates/datasync/partials/_freshness_map.html"

# The six values the three old definitions used between them.
OLD_LITERALS = ("#22c55e", "#f59e0b", "#9ca3af", "#55b678", "#fbbf24", "#8899aa")
# The first three are the old row-dot colours; the rest are token values that
# must now be spelled only in tokens.css (and the colour palette that owns them).
ROW_DOT_LITERALS = ("#22c55e", "#f59e0b", "#9ca3af", "#8899aa")

EXPECTED = {
    "--color-fresh": "#55b678",
    "--color-stale": "#fbbf24",
    "--color-dormant": "#8fa3ae",
}
STATES = {"fresh": "--color-fresh", "stale": "--color-stale", "dead": "--color-dormant"}


def _strip_css_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _declarations():
    source = _strip_css_comments(TOKENS_CSS.read_text())
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", source))


def _resolve(name, seen=()):
    value = _declarations()[name].strip()
    match = re.fullmatch(r"var\((--[a-z0-9-]+)\)", value)
    if match:
        assert match.group(1) not in seen, "token cycle"
        return _resolve(match.group(1), seen + (name,))
    return value.lower()


class TestTheThreeTokensExist:
    def test_each_token_is_declared(self):
        declared = _declarations()
        for name in EXPECTED:
            assert name in declared, name

    def test_each_token_resolves_to_its_value(self):
        for name, value in EXPECTED.items():
            assert _resolve(name) == value, name


class TestTheRowDotsReadTheTokens:
    def _rules(self):
        css = _strip_css_comments(APP_CSS.read_text())
        return dict(re.findall(r"\.freshness-dot--(fresh|stale|dead)\s*\{([^}]*)\}", css))

    def test_each_dot_rule_uses_its_token_and_no_hex(self):
        rules = self._rules()
        assert set(rules) == set(STATES)
        for state, token in STATES.items():
            body = rules[state]
            assert f"var({token})" in body, state
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), state


class TestTheMapReadsTheTokens:
    def test_fresh_meta_holds_no_colour_literal_of_its_own(self):
        source = FRESHNESS_MAP.read_text()
        start = source.index("var FRESH_META")
        block = source[start : source.index("};", start)]
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block)
        for token in STATES.values():
            assert token in block, token


class TestNothingElsePaintsAFreshnessLiteral:
    """No template, stylesheet or script spells a freshness colour by hand."""

    def _files(self):
        for folder, patterns in (
            ("templates", ("*.html",)),
            ("static/css", ("*.css",)),
            ("static/js", ("*.js",)),
        ):
            for pattern in patterns:
                for path in (ROOT / folder).rglob(pattern):
                    if ".min." in path.name or path.name.startswith("tailwind"):
                        continue
                    yield path

    def test_the_old_row_dot_and_dormant_literals_are_gone_from_freshness_code(self):
        offenders = []
        for path in self._files():
            if path == TOKENS_CSS:
                continue
            text = path.read_text()
            if path.suffix == ".css":
                text = _strip_css_comments(text)
            for number, line in enumerate(text.splitlines(), 1):
                low = line.lower()
                if "fresh" in low or "spark" in low:
                    for lit in OLD_LITERALS:
                        if lit in low:
                            offenders.append(f"{path.relative_to(ROOT)}:{number}: {lit}")
        assert offenders == []

    def test_the_station_templates_name_no_row_dot_colour_at_all(self):
        offenders = []
        for rel in (
            "templates/datasync/partials/_station_list_results.html",
            "templates/datasync/partials/_monitoring_content.html",
            "templates/datasync/partials/_station_detail_pane.html",
            "templates/datasync/partials/_freshness_map.html",
        ):
            text = re.sub(r"\{% comment %\}.*?\{% endcomment %\}", "", (ROOT / rel).read_text(), flags=re.S)
            for lit in OLD_LITERALS:
                if lit in text.lower():
                    offenders.append(f"{rel}: {lit}")
        assert offenders == []
