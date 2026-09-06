# SPDX-License-Identifier: AGPL-3.0-or-later
"""The figure ledger must cover every figure, and cover nothing else.

**What this protects.** A partial ledger is worse than no ledger, because it
invites the reader to assume the figures it does not list were checked and found
fine. ``docs/figure-ledger-2026-09.md`` says, by its silence, that there is
nothing else to say. This test is what makes that silence mean something.

**It ratchets in both directions, and both directions matter.**

- *A figure with no ledger row* goes red. Six months from now somebody adds a
  ``floatformat`` to a template, and this test is the only thing in the codebase
  that will tell them the audit document just went stale.
- *A ledger row with no figure* goes red too. A row that outlives the template it
  described is a claim about a screen that no longer exists — quieter than a
  missing row and worse, because it reads as verified.

**The live set is measured, never transcribed.** ``scripts/figure_inventory.py``
is imported and run, not reimplemented here. A second implementation of the
inventory rules would test this file's reading of the templates rather than the
script the ledger was actually built from, and the two would drift apart the
first time either changed.

**``inventory.json`` is checked against the live sweep as well**, because every
sub-agent partitioned its work from that file. If it drifts from the templates,
the ledger was built from a stale scope and nobody would otherwise find out.

⚠ One of the ``floatformat`` occurrences is prose inside a ``{% comment %}``
block — a note in the drinking-water module explaining that lab results
deliberately do *not* go through that formatter. It is a real occurrence and the
inventory keeps it, marked ``kind="comment_prose"``, so the total stays
reproducible against a plain text search. It renders nothing, so it gets no
ledger row. **The set compared here is the ``kind == "figure"`` set.**

⚠ The ``web`` container has no code bind mount. A new test file is invisible to
``make test`` until ``docker compose up -d --build web``, and a suite that never
collected this file reports a pass that is the pass of a test which does not
exist.
"""

import contextlib
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "docs" / "figure-ledger-2026-09.md"
INVENTORY = REPO_ROOT / "audit" / "figure_ledger" / "inventory.json"
INVENTORY_SCRIPT = REPO_ROOT / "scripts" / "figure_inventory.py"

#: A verdict is one of these, and a row may not ship without one.
#:
#: ``UNVERIFIED`` is deliberately allowed. Phase 135 asked its readers to NAME
#: the sites they could not independently recompute rather than omit them — a
#: user-entered form field has nothing to check it against, and saying so is a
#: complete answer. A fabricated ``MATCH`` is not.
#:
#: ``MATCH · ISS-###`` is allowed for the same reason and is not a hedge: the
#: number agrees with the recomputation to the cent AND the words printed beside
#: it are wrong. Collapsing that to either half alone loses something a reader
#: needs. Four rows in this ledger are of that kind.
#:
#: What this pattern refuses is the blank cell and the hand-wave — including the
#: ``ISS-###-pending`` placeholder, which reads like a filed issue and is not
#: one. Reserve a real number before the row ships.
VERDICT = re.compile(r"^(MATCH|EXPLAINED|UNVERIFIED|ISS-\d{3}|MATCH · ISS-\d{3})$")

#: A ledger row starts with the figure id in a code span, in the leading cell.
ROW = re.compile(r"^\|\s*`(FIG-[a-z]+-\d{3})`\s*\|")

#: The schema from 135-01: id, screen, site, label, context_var, view, service,
#: raw_tables, rendered, recomputed, delta, verdict, notes.
COLUMNS = 13
VERDICT_INDEX = 11


@contextlib.contextmanager
def _in_repo_root():
    """``figure_inventory.collect`` walks a RELATIVE root and records relative paths."""
    previous = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


def _inventory_module():
    """Import the real inventory script. Never reimplement what you are auditing."""
    if not INVENTORY_SCRIPT.exists():  # pragma: no cover - script was moved
        pytest.fail(
            f"{INVENTORY_SCRIPT} does not exist. The figure ledger's coverage proof "
            "runs that script rather than restating its rules; if it moved, point "
            "INVENTORY_SCRIPT at the new path rather than letting this test check "
            "nothing."
        )
    spec = importlib.util.spec_from_file_location(
        "figure_inventory_under_test", INVENTORY_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_records():
    """Every figure site the templates carry RIGHT NOW, with stable ids."""
    module = _inventory_module()
    with _in_repo_root():
        records, problems = module.collect()
    assert not problems, (
        "scripts/figure_inventory.py reported malformed figure sites:\n  "
        + "\n  ".join(problems)
    )
    return module.number(records)


def _live_figure_ids():
    return {r["id"] for r in _live_records() if r["kind"] == "figure"}


def _ledger_rows():
    """Every ledger row in the document, as ``{id: [cells]}``."""
    if not LEDGER.exists():  # pragma: no cover - document was moved
        pytest.fail(
            f"{LEDGER} does not exist. That document IS the figure ledger; without "
            "it there is no coverage to prove."
        )
    rows = {}
    duplicates = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        figure_id = match.group(1)
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if figure_id in rows:
            duplicates.append(figure_id)
        rows[figure_id] = cells
    assert not duplicates, (
        "The figure ledger states these figures TWICE, so at least one of the two "
        "rows is unread by anybody: " + ", ".join(sorted(set(duplicates)))
    )
    return rows


def test_the_live_sweep_finds_figures_at_all():
    """An empty sweep would make every set comparison below pass vacuously.

    This is the same defence the independence guard carries: a check that can
    only pass is not a check. If the templates directory moves or the script
    stops matching, this test says so instead of going quietly green.
    """
    live = _live_figure_ids()
    assert len(live) > 50, (
        f"scripts/figure_inventory.py found only {len(live)} figure sites. The "
        "platform carried 106 when this ratchet was written. Either the template "
        "root moved or the script stopped matching — nothing below is meaningful "
        "until that is resolved."
    )


def test_inventory_json_matches_the_templates():
    """The file every sub-agent partitioned its work from must not be stale."""
    on_disk = {
        (r["id"], r["template"], r["line"], r["column"], r["kind"])
        for r in json.loads(INVENTORY.read_text(encoding="utf-8"))
    }
    live = {
        (r["id"], r["template"], r["line"], r["column"], r["kind"])
        for r in _live_records()
    }
    assert on_disk == live, (
        "audit/figure_ledger/inventory.json no longer describes the templates.\n"
        f"  in the file but not in the templates: {sorted(on_disk - live)}\n"
        f"  in the templates but not in the file: {sorted(live - on_disk)}\n"
        "The ledger's scope was partitioned from that file, so a drift here means "
        "the document was built against a set of screens that no longer exists.\n"
        "Regenerate it:\n"
        "  python3 scripts/figure_inventory.py --out audit/figure_ledger/inventory.json\n"
        "then trace any newly appearing site and give it a ledger row."
    )


def test_every_figure_has_a_ledger_row():
    """A figure on a screen with no row is an unaudited number."""
    missing = sorted(_live_figure_ids() - set(_ledger_rows()))
    assert not missing, (
        f"{len(missing)} figure(s) render on a screen with no row in the figure "
        "ledger:\n  " + "\n  ".join(missing) + "\n\n"
        "WHAT THIS MEANS. docs/figure-ledger-2026-09.md traces every number the "
        "platform puts on a screen back to the rows it came from, and recomputes "
        "it a second way. A figure with no row is a number nobody has checked, in "
        "a document whose whole value is that it is complete.\n\n"
        "WHAT TO DO. You have almost certainly just added a `floatformat` to a "
        "template. Find your site:\n"
        "  python3 scripts/figure_inventory.py --out audit/figure_ledger/inventory.json\n"
        "  grep -n '<the id above>' audit/figure_ledger/inventory.json\n"
        "Then add one row to the ledger: trace the value back through the view to "
        "the base tables, recompute it in SQL under audit/figure_ledger/sql/ (that "
        "SQL may not import or call project code — see "
        "tests/test_figure_ledger_independence.py), and record both numbers.\n"
        "docs/figure-ledger-2026-09.md's own opening section explains the schema."
    )


def test_every_ledger_row_has_a_figure():
    """A row that outlives its template is a claim about a screen nobody can open."""
    orphans = sorted(set(_ledger_rows()) - _live_figure_ids())
    assert not orphans, (
        f"{len(orphans)} ledger row(s) describe a figure that no longer renders:\n"
        "  " + "\n  ".join(orphans) + "\n\n"
        "WHAT THIS MEANS. You have probably deleted or reworked a template, or "
        "moved a number to a different line. The ledger still carries a row for "
        "it, stating a rendered value and a verdict for a screen that no longer "
        "shows that figure. That is quieter than a missing row and worse, because "
        "it reads as verified.\n\n"
        "WHAT TO DO. If the figure is gone for good, delete its row. If it MOVED, "
        "the id has changed with it (ids are assigned in template/line/column "
        "order): regenerate the inventory, find the new id, and update the row's "
        "id and `site` column together."
    )


@pytest.mark.parametrize("figure_id", sorted(_ledger_rows()))
def test_ledger_row_is_complete_and_carries_a_verdict(figure_id):
    """No blank cells, and no row that shipped without saying what it concluded."""
    cells = _ledger_rows()[figure_id]
    assert len(cells) == COLUMNS, (
        f"{figure_id}: the ledger schema has {COLUMNS} columns and this row has "
        f"{len(cells)}. A row with a column missing silently shifts every value "
        "after it into the wrong heading."
    )
    blank = [i for i, cell in enumerate(cells) if not cell]
    assert not blank, (
        f"{figure_id}: column(s) {blank} are empty. Every column is filled or the "
        "row is not finished — including `notes`, which carries the independence "
        "class the whole ledger rests on."
    )
    verdict = cells[VERDICT_INDEX]
    assert VERDICT.match(verdict), (
        f"{figure_id}: verdict {verdict!r} is not one this ledger recognises.\n"
        "  MATCH          — the two numbers agree to the cent\n"
        "  EXPLAINED      — they agree or differ for a stated reason that is not a\n"
        "                   measurement, written out in notes\n"
        "  UNVERIFIED     — it could not be independently recomputed, and notes says why\n"
        "  ISS-###        — the screen states two things that cannot both be true\n"
        "  MATCH · ISS-### — the number is right and the words beside it are wrong\n"
        "A blank or hand-waved verdict is the one thing this ledger cannot carry: "
        "the reader has no way to tell it from a check that passed. If you meant "
        "'an issue is coming', reserve the number now — a placeholder reads like a "
        "filed issue and is not one."
    )
