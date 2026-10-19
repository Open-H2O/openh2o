# SPDX-License-Identifier: AGPL-3.0-or-later
"""List the guide and help page sections whose code has changed since they were read.

Phase 150.6 (2026-10-19). ``tests/document_sources.toml`` lists, for each
section of the twenty documents, the code its sentences rest on and the
commit it was last read against (``checked_at``). At each phase's close this
script lists the sections to re-read: those where one of the listed files, or
the section's own text, changed between ``checked_at`` and HEAD. The re-read
itself is done by a person or an agent, against the diff and the code.

What counts as a change:

- any edit to a listed file or to a file that shows one of the section's
  labels, comments included: a re-read costs a reader's time, and a missed
  change costs a false sentence;
- an edit to the section's own text (an edited section is read again);
- nothing under ``tests/``.

It needs only git and the standard library, so it runs on the host::

    python3 scripts/guide_reread.py                 # sections to re-read
    python3 scripts/guide_reread.py --all           # every section (full re-read)
    python3 scripts/guide_reread.py --mark-read DEPLOY.md#Upgrades docs/DATA-IMPORT.md
    python3 scripts/guide_reread.py --since A --until B   # as if every section were read at A

``--mark-read`` is the only thing that changes a ``checked_at``: it sets the
named sections (or every section of a named document) to HEAD.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "tests" / "document_sources.toml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guide_names import sections as document_sections  # noqa: E402


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def load(path: Path = SOURCES) -> list[dict]:
    with open(path, "rb") as handle:
        return tomllib.load(handle)["section"]


_CHANGED: dict = {}


def changed_files(start: str, end: str) -> set:
    """Files changed between two commits, tests/ left out."""
    if (start, end) not in _CHANGED:
        names = git("diff", "--name-only", f"{start}..{end}").split("\n")
        _CHANGED[(start, end)] = {n for n in names if n and not n.startswith("tests/")}
    return _CHANGED[(start, end)]


_TEXTS: dict = {}


def section_texts(document: str, rev: str) -> dict:
    """Each section's text at a commit, by heading; empty if the document was not there."""
    key = (document, rev)
    if key not in _TEXTS:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{rev}:{document}"],
                                capture_output=True, text=True)
        texts: dict = {}
        if result.returncode == 0:
            lines = result.stdout.split("\n")
            for heading, first, last in document_sections(document, result.stdout):
                texts[heading] = "\n".join(lines[first - 1:last]).strip()
        _TEXTS[key] = texts
    return _TEXTS[key]


def to_reread(entries: list[dict], end: str = "HEAD", since: str | None = None) -> list[tuple[dict, list]]:
    """Each section to re-read, with what changed: its files, and "(its own text)"."""
    result = []
    for entry in entries:
        start = since or entry["checked_at"]
        changed = changed_files(start, end)
        # A label's screen is code the section rests on as well.
        paths = set(entry["files"]) | {label["where"] for label in entry.get("labels", [])}
        reasons = sorted(path for path in paths if path in changed)
        if entry["document"] in changed:
            before = section_texts(entry["document"], start).get(entry["heading"])
            after = section_texts(entry["document"], end).get(entry["heading"])
            if before != after:
                reasons.append("(its own text)")
        if reasons:
            result.append((entry, reasons))
    return result


def report(flagged: list[tuple[dict, list]], total: int, end: str, since: str | None) -> str:
    lines = []
    by_document: dict = {}
    for entry, reasons in flagged:
        by_document.setdefault(entry["document"], []).append((entry, reasons))
    for document, items in by_document.items():
        lines.append(f"{document}")
        for entry, reasons in items:
            start = since or entry["checked_at"]
            lines.append(f"  {entry['heading']}  (read at {start})")
            files = [r for r in reasons if not r.startswith("(")]
            for reason in reasons:
                lines.append(f"    changed: {reason}")
            if files:
                stat = git("diff", "--stat", f"{start}..{end}", "--", *files).rstrip()
                lines.extend("      " + line for line in stat.split("\n") if line)
    lines.append(f"{len(flagged)} of {total} sections to re-read")
    return "\n".join(lines)


def mark_read(targets: list[str], path: Path = SOURCES) -> list[str]:
    """Set checked_at to HEAD for DOCUMENT or DOCUMENT#HEADING; returns what was set."""
    head = git("rev-parse", "--short", "HEAD").strip()
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^\[\[section\]\]$)", text, flags=re.M)
    wanted = [target.partition("#") for target in targets]
    done, used = [], set()
    for index, block in enumerate(blocks):
        if not block.startswith("[[section]]"):
            continue
        entry = tomllib.loads(block)["section"][0]
        for number, (document, _, heading) in enumerate(wanted):
            if entry["document"] == document and (not heading or entry["heading"] == heading):
                blocks[index] = re.sub(r'^checked_at = ".*"$', f'checked_at = "{head}"', block, flags=re.M)
                done.append(f"{document}#{entry['heading']} -> {head}")
                used.add(number)
    missing = [targets[n] for n in range(len(targets)) if n not in used]
    if missing:
        raise SystemExit("No such section: " + ", ".join(missing))
    path.write_text("".join(blocks), encoding="utf-8")
    return done


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--all", action="store_true", help="list every section (a full re-read)")
    parser.add_argument("--mark-read", nargs="+", metavar="DOCUMENT[#HEADING]",
                        help="set these sections' checked_at to HEAD")
    parser.add_argument("--since", help="treat every section as read at this commit")
    parser.add_argument("--until", default="HEAD", help="compare with this commit (default HEAD)")
    parser.add_argument("--sources", type=Path, default=SOURCES, help="a copy of the sources file")
    parser.add_argument("--count", action="store_true", help="print only the count")
    args = parser.parse_args(argv)

    if args.mark_read:
        for line in mark_read(args.mark_read, args.sources):
            print(line)
        return 0
    entries = load(args.sources)
    if args.all:
        for entry in entries:
            print(f"{entry['document']}  {entry['heading']}  (read at {entry['checked_at']})")
        print(f"{len(entries)} sections")
        return 0
    flagged = to_reread(entries, args.until, args.since)
    if args.count:
        print(f"{len(flagged)} of {len(entries)}")
    else:
        print(report(flagged, len(entries), args.until, args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
