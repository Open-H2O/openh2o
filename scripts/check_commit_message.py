#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refuse a commit message that names a person or cites a number from outside the repository.

The commit list on GitHub is public and reads as OpenH2O's change log: a message says what
changed and why. An issue, plan or phase number from the maintainer's private planning record,
a decision number (the word "ruling" and a number) or a person's name points a reader at something they cannot
open. This script prints each such line with its reason and exits 1; the commit-msg hook that
``make hooks`` installs runs it before the commit exists.

    python3 -I scripts/check_commit_message.py <message file>
    python3 -I scripts/check_commit_message.py --range <base>..<head> [--after <commit>]

The shapes are the planning-reference guard's (tests/test_no_planning_references.py), imported
so the two cannot drift, plus a decision number. A maintainer can list more words to refuse,
such as the names of their own machines, one a line in ``.git/info/commit-words``: that file is
never committed, so the names stay out of the repository too.

Allowed: dates, versions, commit hashes, file and test names, this repository's own issue and
pull request numbers (#123), and the ``Test-Change:`` and ``Fix-Test:`` lines the release check
reads (their path or commit is not checked, their reason is). Lines starting with ``#`` are
git's own notes and are not part of the message; nothing below git's scissors line is read.

``--range`` checks the messages of the commits in a range (the test workflow runs it on each
push); ``--after`` leaves out every commit that does not descend from the named one, so the
history before the rule began is not read. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_no_planning_references import PATTERNS as GUARD_PATTERNS  # noqa: E402

#: The guard's shapes that mean a planning reference in any text. Its other shapes (a version
#: beside certain words, a labelled plan item, a planning document's name) are about code
#: comments and would refuse ordinary messages.
SHAPES = {
    name: GUARD_PATTERNS[name]
    for name in (
        "issue number", "phase number", "plan number", "planning file", "review row", "first name", "decision number",
    )
}

REASON_LINE = re.compile(r"^\s*(Test-Change|Fix-Test):\s*[^:]+:\s*(.*)$")
SCISSORS = "# ------------------------ >8 ------------------------"


def message_lines(message: str):
    """The lines git keeps from ``message``: comments and everything below the scissors dropped."""
    for line in message.splitlines():
        if line.startswith(SCISSORS):
            return
        if line.startswith("#"):
            continue
        yield line


def refused_lines(message: str, words=()) -> list[tuple[str, str]]:
    """``[(line, reason), ...]`` for every line of ``message`` the rule refuses."""
    word_shapes = [(w, re.compile(rf"\b{re.escape(w)}\b", re.I)) for w in words if w.strip()]
    out = []
    for line in message_lines(message):
        reason_line = REASON_LINE.match(line)
        text = reason_line.group(2) if reason_line else line
        for name, shape in SHAPES.items():
            if shape.search(text):
                out.append((line, f"a {name} from outside the repository"))
                break
        else:
            for word, shape in word_shapes:
                if shape.search(text):
                    out.append((line, f'"{word}" is on this clone\'s list of words to keep out of commits'))
                    break
    return out


def local_words(repo: Path) -> list[str]:
    """The words in this clone's ``.git/info/commit-words``, if it has one."""
    try:
        where = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/commit-words"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return []
    path = repo / where
    if not path.is_file():
        return []
    return [w.strip() for w in path.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]


def report(refused, where="") -> None:
    for line, reason in refused:
        print(f"{where}refused: {line}\n    {reason}", file=sys.stderr)


def check_file(path: Path) -> int:
    refused = refused_lines(path.read_text(encoding="utf-8"), local_words(Path.cwd()))
    if refused:
        report(refused)
        print(
            "\nA commit message says what changed and why, with no person's name and no issue, plan,\n"
            "phase or decision number from outside the repository (CONTRIBUTING.md, Ground rules).\n"
            "Rewrite the lines above and commit again.",
            file=sys.stderr,
        )
        return 1
    return 0


def check_range(spec: str, after: str | None) -> int:
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout

    commits = git("rev-list", "--no-merges", spec).split()
    bad = 0
    for commit in commits:
        if after:
            if commit.startswith(after) or after.startswith(commit):
                continue
            if subprocess.run(["git", "merge-base", "--is-ancestor", after, commit]).returncode != 0:
                continue
        refused = refused_lines(git("log", "-1", "--format=%B", commit))
        if refused:
            bad += 1
            report(refused, where=f"{commit[:12]} ")
    if bad:
        print(
            f"\n{bad} commit(s) carry a line the commit-message rule refuses. A pushed commit is not\n"
            "rewritten; this means a clone committed without the hook: run `make hooks` there.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("message", nargs="?", type=Path, help="the commit message file git passes to commit-msg")
    parser.add_argument("--range", dest="spec", help="check every commit in <base>..<head>")
    parser.add_argument("--after", help="with --range: only commits that descend from this one")
    args = parser.parse_args(argv)
    if args.spec:
        return check_range(args.spec, args.after)
    if not args.message:
        parser.error("give a message file or --range")
    return check_file(args.message)


if __name__ == "__main__":
    sys.exit(main())
