# SPDX-License-Identifier: AGPL-3.0-or-later
"""The commit-message check refuses a name or an internal code before the commit exists.

The commit list on GitHub is public and reads as the project's change log, so a message says
what changed and why. Numbers from the maintainer's private planning record (issue, plan and
phase numbers, decision numbers) and people's names point a reader at something they cannot
open. ``scripts/check_commit_message.py`` refuses them; ``make hooks`` runs it on every commit.
The ``Test-Change:`` and ``Fix-Test:`` lines the release check reads stay allowed.

Standard library and git only, so it runs on the GitHub runner beside test_test_reasons.py.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_commit_message.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_commit_message", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _maintainer():
    return (ROOT / "NOTICE").read_text(encoding="utf-8").split("Copyright (C) 2026 ", 1)[1].split()[0]


def _refused(message, words=()):
    return _load().refused_lines(message, words)


@pytest.mark.parametrize(
    "message",
    [
        "fix: the card's total (ISS-443)",
        "feat(155-01): the card states its sum",
        "153-09: the guard the full run named",
        "feat: the carry-over lines (ruling 250)",
        "test: Ruling 212's words",
        "docs: Phase 154 complete",
        "fix: the words from 155-01-ROWS.md",
    ],
)
def test_an_internal_code_is_refused(message):
    assert _refused(message), message


def test_the_maintainers_first_name_is_refused():
    assert _refused(f"fix: the wording {_maintainer()} approved")


@pytest.mark.parametrize(
    "message",
    [
        "fix: the end date of a range is included\n\nRead on 2026-11-22 against v3.1.",
        "feat: the card states its sum, as #123 asked",
        "test: tests/test_release_bar_353.py reads the recorded month",
        "fix: the migration 0047_el_nido_allocation_note_words keeps its words",
        "fix: the canal total\n\nTest-Change: tests/test_canal_lining.py: comments only, the reason replaces a quote",
        "fix: the canal total\n\nFix-Test: 2a5767b061d6: the old test already covered the case",
        "feat: a, b\n\n# Please enter the commit message for your changes. ISS-1 in a comment is git's, not the message",
    ],
)
def test_dates_versions_hashes_file_names_and_reason_lines_pass(message):
    assert _refused(message) == [], message


def test_a_reason_line_is_still_checked_after_its_path():
    assert _refused("fix: x\n\nTest-Change: tests/test_x.py: rows of ruling 248")


def test_nothing_below_the_scissors_line_is_read():
    message = "fix: x\n# ------------------------ >8 ------------------------\ndiff --git a/ISS-1 b/ISS-1\n"
    assert _refused(message) == []


def test_a_local_word_list_refuses_its_words_only_when_listed():
    message = "fix: staging on Kestrel reads the footer"
    assert _refused(message) == []
    assert _refused(message, words=["kestrel"])


def test_each_refused_line_carries_its_reason():
    [(line, reason)] = _refused("fix: x (ISS-443)")
    # not wording: the message under test, read back as it was given
    assert line == "fix: x (ISS-443)"
    assert "issue number" in reason


def test_the_command_exits_1_and_names_the_line(tmp_path):
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("feat(155-01): x\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(message)], capture_output=True, text=True, cwd=tmp_path
    )
    assert result.returncode == 1
    assert "feat(155-01): x" in result.stderr


def test_the_command_exits_0_on_a_plain_message(tmp_path):
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix: the end date of a range is included\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(message)], capture_output=True, text=True, cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr


def test_the_patterns_come_from_the_planning_reference_guard():
    """One list of shapes for code comments and commit messages, so the two cannot drift."""
    guard = (ROOT / "tests" / "test_no_planning_references.py").read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "test_no_planning_references" in script
    assert 're.compile(r"ISS-' not in script and "ISS-" in guard
