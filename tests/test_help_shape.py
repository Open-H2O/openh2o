# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shape of the help pages: 60 words a block, and half a page at most in prose.

Brent's thresholds (2026-10-06 18:17 PDT) live in ``scripts/help_shape.py``. A
help page is a table, a heading, a link card and short blocks; a wall of
paragraphs is the fault. Every file under ``templates/help/`` is in exactly one
of two lists below: ``ENFORCED`` is held to the thresholds, ``PENDING`` is held
to the numbers it had when this file was written and may only get better.

The cap limits length and says nothing about the shape of a sentence: a
60-word paragraph can still be written in a shape Brent has struck. That is
checked by ``tests/test_writing_shapes.py`` and by a reader. Brent kept the
cap on 2026-10-09 at 20:03 PDT.

**Kill switch:** ``OPENH2O_HELP_SHAPE_CHECK=0`` skips this module.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_HELP_SHAPE_CHECK", "1") == "0",
    reason="OPENH2O_HELP_SHAPE_CHECK=0",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HELP_DIR = REPO_ROOT / "templates" / "help"
SCRIPT = REPO_ROOT / "scripts" / "help_shape.py"

#: Files under the gate: each fails if longest > 60 or share > 0.50. A page joins when Brent approves it.
ENFORCED: list = [
    "templates/help/budgets_allocations.html",
    "templates/help/methods.html",
    "templates/help/settings_explained.html",
    "templates/help/surface_deliveries.html",
    "templates/help/water_balances.html",
    "templates/help/getting_started.html",
    "templates/help/glossary.html",
    "templates/help/partials/_the_subtraction.html",
    "templates/help/partials/_canal_split_diagram.html",
    # 150-03 (2026-10-09): About carried to the help-page shape; measured 18 blocks,
    # longest 43, share 0.35 on the day it joined.
    "templates/about.html",
]

#: Files not yet under the gate, with (longest, share) as measured; the test fails if either rises.
#: Empty since 149.1-04 (2026-10-07): every help page is in ENFORCED. A new help page
#: starts here at its measured numbers and moves up when Brent approves it.
PENDING: dict = {}


def _load():
    if not SCRIPT.exists():
        pytest.fail(f"{SCRIPT} is missing; update SCRIPT if it moved.")
    spec = importlib.util.spec_from_file_location("help_shape_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shape = _load()


def _paragraph(words: int) -> str:
    return "<p>" + " ".join(["word"] * words) + "</p>"


@pytest.mark.parametrize(
    "rel",
    ENFORCED or [pytest.param(None, marks=pytest.mark.skip(reason="ENFORCED is empty"))],
)
def test_enforced_pages_hold_the_shape(rel):
    row = shape.measure(REPO_ROOT / rel)
    assert row["longest"] <= shape.MAX_BLOCK_WORDS, (
        f"{rel}: longest block is {row['longest']} words, the limit is "
        f"{shape.MAX_BLOCK_WORDS}"
    )
    assert row["share"] <= shape.MAX_PROSE_SHARE, (
        f"{rel}: {row['share']:.2f} of the words are in prose blocks, the limit is "
        f"{shape.MAX_PROSE_SHARE:.2f}"
    )


@pytest.mark.parametrize(
    "rel",
    sorted(PENDING) or [pytest.param(None, marks=pytest.mark.skip(reason="PENDING is empty"))],
)
def test_pending_pages_do_not_get_worse(rel):
    longest, share = PENDING[rel]
    row = shape.measure(REPO_ROOT / rel)
    assert row["longest"] <= longest, (
        f"{rel}: longest block rose from {longest} to {row['longest']} words. "
        "Lower the baseline when a page improves; never raise it."
    )
    assert round(row["share"], 2) <= share, (
        f"{rel}: prose share rose from {share:.2f} to {row['share']:.2f}."
    )


def test_the_check_bites_when_a_wall_is_planted(tmp_path):
    wall = tmp_path / "wall.html"
    wall.write_text("<h2>Heading</h2>" + _paragraph(61))
    assert shape.measure(wall)["longest"] > shape.MAX_BLOCK_WORDS

    fine = tmp_path / "fine.html"
    fine.write_text(
        "<h2>Heading</h2>" + _paragraph(60)
        + "<table><tr><td>" + " ".join(["cell"] * 100) + "</td></tr></table>"
    )
    row = shape.measure(fine)
    assert row["longest"] <= shape.MAX_BLOCK_WORDS
    assert row["share"] <= shape.MAX_PROSE_SHARE

    heavy = tmp_path / "heavy.html"
    heavy.write_text(
        _paragraph(35) * 2 + "<table><tr><td>" + " ".join(["cell"] * 30) + "</td></tr></table>"
    )
    row = shape.measure(heavy)
    assert row["longest"] <= shape.MAX_BLOCK_WORDS
    assert row["share"] > shape.MAX_PROSE_SHARE

    nested = tmp_path / "nested.html"
    nested.write_text("<ul><li>" + _paragraph(10) + "</li></ul>")
    assert shape.measure(nested)["blocks"] == [10]


def test_every_help_file_is_in_exactly_one_list():
    on_disk = {str(p.relative_to(REPO_ROOT)) for p in HELP_DIR.rglob("*.html")}
    listed = list(ENFORCED) + list(PENDING)
    assert len(listed) == len(set(listed)), "a help file is in both lists or twice in one"
    # A page outside templates/help/ may join ENFORCED (About did, 150-03); the
    # completeness check is over the help folder only.
    listed_help = {rel for rel in listed if rel.startswith("templates/help/")}
    assert listed_help == on_disk, (
        f"unlisted: {sorted(on_disk - listed_help)}; missing on disk: "
        f"{sorted(listed_help - on_disk)}"
    )
    for rel in listed:
        assert (REPO_ROOT / rel).exists(), f"{rel} is listed but not on disk"
