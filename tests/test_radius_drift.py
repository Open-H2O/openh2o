# SPDX-License-Identifier: AGPL-3.0-or-later
"""The squared surface, held against drift (ISS-149).

Phase 138 took every corner in the platform down to one flat 2px scale and put
the decision in five tokens. The way that comes undone is not a rewrite: it is
one person copying a neighbouring block that predates the sweep, or pasting a
snippet from a library's docs, and writing ``border-radius: 8px`` again. Nothing
about the page looks broken when that happens, so nothing catches it. This file
does.

Three guards:

  1. No literal radius anywhere. Every corner reads one of the five tokens.
  2. The circles are still circles. ``50%`` is not a radius on a scale and a
     sweep must never flatten one -- that is the exact failure ISS-149 warned
     about when it was filed.
  3. DESIGN.md's Border Radius section still states the values ``tokens.css``
     actually holds. That section had ALREADY drifted before Phase 138 touched
     anything: it claimed Large was 12px while the token said 14px, and named no
     extra-large at all. A document that describes a design system it no longer
     matches is worse than no document, because it is quoted with confidence.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = ROOT / "static/css/tokens.css"
DESIGN_MD = ROOT / "DESIGN.md"

SWEPT = [
    ROOT / "static/css/app.css",
    ROOT / "static/css/map-engine.css",
] + sorted((ROOT / "templates").rglob("*.html"))

RADIUS = re.compile(r"border-radius\s*:\s*([^;}\"']+)")

# The two squares that are square ON PURPOSE, each with the reason it is not a
# token read. Any THIRD entry wanting to join this list is a design decision and
# belongs in DESIGN.md before it belongs here.
DELIBERATE_ZEROS = {
    # An input nested inside an already-bordered wrapper: a second corner inside
    # the first one reads as a seam.
    "static/css/app.css",
    # MapLibre's own scale bar, which is a ruler and must meet the map edge flush.
    "static/css/map-engine.css",
}


def _declarations():
    """Every ``border-radius`` in the swept files as (relpath, line, value)."""
    for path in SWEPT:
        try:
            text = path.read_text()
        except UnicodeDecodeError:  # pragma: no cover - no such file today
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in RADIUS.finditer(line):
                yield str(path.relative_to(ROOT)), number, match.group(1).strip()


def _is_zero(value):
    return value.replace("!important", "").strip() in {"0", "0px"}


class TestEveryCornerReadsAToken:
    """Guard 1 -- no literal radius survives anywhere in the swept files."""

    def test_no_hardcoded_radius(self):
        offenders = []
        for rel, number, value in _declarations():
            if "50%" in value:
                continue  # guard 2's business
            if _is_zero(value):
                assert rel in DELIBERATE_ZEROS, (
                    f"{rel}:{number} sets border-radius: 0 outside the two files "
                    "allowed a deliberate square. Read a token instead."
                )
                continue
            if "var(--radius-" not in value:
                offenders.append(f"{rel}:{number}  border-radius: {value}")
        assert not offenders, (
            "A corner is written as a literal instead of reading a radius token.\n"
            "DESIGN.md: every corner reads one of the five tokens in tokens.css, "
            "so the whole surface moves from one place.\n  " + "\n  ".join(offenders)
        )

    def test_a_token_read_carries_no_fallback(self):
        """``var(--radius-md, 10px)`` shadows the token with a stale duplicate.

        tokens.css always loads, so the fallback can never fire; all it can do is
        disagree with the token it names and mislead the next reader. Nine of
        these were live in map-engine.css before Phase 138, several already
        wrong.
        """
        offenders = [
            f"{rel}:{number}  {value}"
            for rel, number, value in _declarations()
            if "var(--radius-" in value and re.search(r"var\(\s*--radius-[a-z]+\s*,", value)
        ]
        assert not offenders, (
            "A radius token is read with a fallback value:\n  " + "\n  ".join(offenders)
        )


class TestTheCirclesAreStillCircles:
    """Guard 2 -- ``50%`` is a circle and a squaring sweep must not touch it."""

    def test_circles_survive(self):
        circles = [
            f"{rel}:{number}"
            for rel, number, value in _declarations()
            if "50%" in value
        ]
        # Avatars, status dots, the data-freshness pips, the map legend's swatch
        # dot and the empty-pane icon. The count is asserted, not just the
        # presence, so flattening one fails loudly instead of passing quietly.
        assert len(circles) >= 15, (
            f"Only {len(circles)} `border-radius: 50%` rules remain; there were "
            "15 or more when ISS-149 was swept. A circle has been squared:\n  "
            + "\n  ".join(circles)
        )


class TestDesignDocMatchesTheTokens:
    """Guard 3 -- DESIGN.md states the values tokens.css actually holds."""

    @pytest.mark.parametrize(
        "token", ["--radius-sm", "--radius-md", "--radius-lg", "--radius-xl", "--radius-pill"]
    )
    def test_design_md_states_the_live_value(self, token):
        css = TOKENS_CSS.read_text()
        match = re.search(rf"{token}\s*:\s*([^;]+);", css)
        assert match, f"{token} is missing from tokens.css"
        value = match.group(1).strip()

        design = DESIGN_MD.read_text()
        section = design.split("## Border Radius", 1)
        assert len(section) == 2, "DESIGN.md has no Border Radius section"
        body = section[1].split("\n## ", 1)[0]

        # Bind the value to the token's OWN table row. Checking only that the
        # value appears somewhere in the section is not a measurement: with four
        # tokens sharing one value, every wrong row still finds its number in a
        # neighbour's. Proven by deliberately setting --radius-lg to 12px in the
        # document on 2026-09-06; the loose check passed.
        row = re.search(rf"^\|\s*`{re.escape(token)}`\s*\|([^|]*)\|", body, re.MULTILINE)
        assert row, (
            f"DESIGN.md's Border Radius table has no row for {token}. It named no "
            "extra-large token for months while tokens.css had one."
        )
        stated = row.group(1).strip()
        assert stated == value, (
            f"DESIGN.md states {token} is {stated!r}; tokens.css says {value!r}. "
            "Fix the document, not this test."
        )
