# SPDX-License-Identifier: AGPL-3.0-or-later
"""The map palette is declared twice. This makes the second copy honest.

``static/css/tokens.css`` names the map's entity colours and ``OH2O.colors`` in
``static/js/map-core.js`` holds the values MapLibre actually paints with. No CSS
rule reads ``var(--color-entity-*)``; every consumer is the JavaScript. The token
block is therefore a *written promise* about what the JS holds, and until
2026-08-26 nothing checked it -- ``templates/base.html`` claimed the tokens were
"the authority" while covering 5 of the JS object's 11 keys, and one of the six
uncovered keys (``green``) had drifted to within three points of ``--color-supply``
with no record of why.

Each guard names the rule it enforces and the defect it prevents. A guard that
cannot say what breaks when it is violated does not belong here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = ROOT / "static/css/tokens.css"
MAP_CORE_JS = ROOT / "static/js/map-core.js"

# --color-entity-hydro-casing  ->  hydroCasing
_TOKEN_DECL = re.compile(r"--color-entity-([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;")
_JS_PAIR = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*:\s*'(#[0-9a-fA-F]{3,8})'")


def _strip_css_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _kebab_to_camel(name):
    head, *rest = name.split("-")
    return head + "".join(part.capitalize() for part in rest)


def _tokens():
    """``{camelCaseName: value}`` for every ``--color-entity-*`` in tokens.css.

    Comments are stripped as BLOCKS before matching. The block carries prose
    naming other colours (``#55B678``) and a line-prefix filter would read those
    quotations as live declarations -- the same trap
    ``test_template_hygiene.py`` documents for the old gold.
    """
    source = _strip_css_comments(TOKENS_CSS.read_text())
    return {
        _kebab_to_camel(name): value
        for name, value in _TOKEN_DECL.findall(source)
    }


def _js_palette():
    """``{key: value}`` for the ``OH2O.colors`` object literal in map-core.js.

    Scoped to the object's own braces rather than the whole file, so an unrelated
    hex literal elsewhere in the toolkit cannot join the palette by accident.
    """
    source = MAP_CORE_JS.read_text()
    start = source.index("OH2O.colors")
    end = source.index("};", start)
    body = re.sub(r"//[^\n]*", "", source[start:end])
    return dict(_JS_PAIR.findall(body))


class TestTheMapPaletteHasOneSourceOfTruth:
    """``tokens.css`` and ``map-core.js`` name the same colours with the same values.

    The defect this prevents is silent divergence between a palette everyone
    reads and a palette the browser paints. It has already happened twice here:
    ``templates/base.html`` once declared a third copy that had quietly become
    the shorter of two and carried the pre-Deep-Water gold, and the token block
    itself covered only 5 of 11 keys while calling itself the authority. Both
    times the wrong copy was the one that *looked* canonical.
    """

    def test_both_files_declare_the_same_colour_names(self):
        tokens = set(_tokens())
        js = set(_js_palette())
        assert tokens == js, (
            "static/css/tokens.css and static/js/map-core.js disagree about "
            "WHICH colours the map palette has.\n"
            f"  only in tokens.css (--color-entity-*): {sorted(tokens - js) or 'none'}\n"
            f"  only in map-core.js (OH2O.colors):     {sorted(js - tokens) or 'none'}\n"
            "Every OH2O.colors key needs a --color-entity-* token and vice versa."
        )

    def test_both_files_agree_on_every_colour_value(self):
        tokens = _tokens()
        js = _js_palette()
        mismatched = [
            (key, tokens[key], js[key])
            for key in sorted(set(tokens) & set(js))
            if tokens[key].lower() != js[key].lower()
        ]
        assert not mismatched, "\n".join(
            [
                "static/css/tokens.css and static/js/map-core.js disagree about "
                "the VALUE of a map colour. Change both or neither:"
            ]
            + [
                f"  {key}: tokens.css says {token_value}, "
                f"map-core.js says {js_value}"
                for key, token_value, js_value in mismatched
            ]
        )

    def test_the_palette_is_not_empty(self):
        """Both readers must actually find something.

        Without this, a regex that stopped matching -- a reformatted token block,
        a rewritten object literal -- would make the two guards above compare an
        empty set against an empty set and pass while checking nothing. That
        vacuous-check failure mode is exactly what Phase 120 spent a phase
        removing from this project's instruments.
        """
        tokens = _tokens()
        js = _js_palette()
        assert len(tokens) >= 11, (
            f"only {len(tokens)} --color-entity-* tokens parsed out of "
            f"{TOKENS_CSS.relative_to(ROOT)}; the reader is broken, not the palette"
        )
        assert len(js) >= 11, (
            f"only {len(js)} OH2O.colors keys parsed out of "
            f"{MAP_CORE_JS.relative_to(ROOT)}; the reader is broken, not the palette"
        )


class TestNoFourthCopyOfTheGoldLiteral:
    """``map-engine.js`` may not re-declare a palette colour as a literal.

    ``map-engine.js:329`` carried ``var GOLD = (OH2O.colors && OH2O.colors.gold)
    || '#E4A317';`` -- a third copy of the value, reachable only if map-core.js
    had failed to load. It could not: ``templates/geography/map.html`` is the one
    template that loads the engine, and it loads map-core.js at line 134 inside
    the same ``{% block map_scripts %}``, 370 lines above the engine at 504. Both
    are plain synchronous ``<script src>`` tags, so classic script ordering
    guarantees the palette exists. The fallback was removed 2026-08-26; this
    guard stops it, or another like it, coming back.
    """

    def test_map_engine_takes_its_colours_from_the_palette(self):
        source = re.sub(r"//[^\n]*", "", (ROOT / "static/js/map-engine.js").read_text())
        literals = re.findall(r"#[0-9a-fA-F]{6}", source)
        palette = {value.lower() for value in _js_palette().values()}
        offenders = sorted({lit for lit in literals if lit.lower() in palette})
        assert not offenders, (
            "static/js/map-engine.js hardcodes a colour that is already in the "
            f"map palette: {offenders}. Read it from OH2O.colors instead -- "
            "map-core.js is guaranteed loaded first on the only page that loads "
            "the engine."
        )
