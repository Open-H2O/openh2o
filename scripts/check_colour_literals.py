#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fail CI when a pre-Deep-Water colour literal spreads.

CLAUDE.md: "Never hardcode a colour." The six values below are the palette the
site used before Deep-Water. They are still painted in a few map files, and
moving those is visual work, so this check is a ratchet, not a sweep:

- a file that is not in BASELINE gaining any of the six fails;
- a file in BASELINE holding more of a value than its baseline count fails;
- a file holding FEWER than its baseline count passes and prints the line to
  lower the baseline to, so the ratchet tightens by an edit, never silently.

The fix for a failure is a design token (`var(--color-...)` in CSS and
templates, or the token read from the stylesheet in JS), never a new literal.
`--color-entity-*` lines are the documented exception (the map layer identity
palette in tokens.css) and are skipped. tests/, docs/ and Markdown files are
not scanned: they quote the old values on purpose.

    python scripts/check_colour_literals.py           # scan the repository
    python scripts/check_colour_literals.py --root D  # scan directory D

Standard library only: it runs in the lint job before any dependency install.
"""

import argparse
import subprocess
import sys
from pathlib import Path

OLD_VALUES = ("#040608", "#080b10", "#0e1219", "#e8edf4", "#8899aa", "#4d5e6f")

# Measured 2026-11-14 on main 5ce76994 (tracked files, case-insensitive).
# Counts may only fall. When one does, lower it here in the same commit.
BASELINE = {
    "error-pages/503.html": {"#040608": 2, "#080b10": 2, "#4d5e6f": 1, "#8899aa": 1, "#e8edf4": 1},
    "static/css/map-engine.css": {"#040608": 4, "#8899aa": 8, "#e8edf4": 5},
    "static/js/map-core.js": {"#040608": 16, "#080b10": 1, "#8899aa": 6, "#e8edf4": 1},
    "templates/geography/partials/_zones_overview_map.html": {"#8899aa": 1, "#e8edf4": 1},
}

SKIP_DIRS = {"tests", "docs", ".git", "node_modules", "__pycache__", ".venv", "venv", "staticfiles", "media"}
TEXT_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".py", ".svg", ".json", ".txt", ".toml", ".yml", ".yaml", ".sh", ".conf"}
EXEMPT_MARKER = "--color-entity-"
SELF = "scripts/check_colour_literals.py"


def candidate_files(root):
    """Relative POSIX paths to scan: git's tracked files when root is a checkout, else a walk."""
    root = Path(root)
    if (root / ".git").exists():
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
        paths = [p for p in out.stdout.decode().split("\0") if p]
    else:
        paths = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    keep = []
    for rel in paths:
        parts = rel.split("/")
        if parts[0] in SKIP_DIRS or any(part in SKIP_DIRS for part in parts[:-1]):
            continue
        if rel == SELF or Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        keep.append(rel)
    return sorted(keep)


def scan(root):
    """{relative path: {value: count}} for every file holding at least one old value."""
    root = Path(root)
    found = {}
    for rel in candidate_files(root):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        counts = {}
        for line in text.splitlines():
            if EXEMPT_MARKER in line:
                continue
            low = line.lower()
            for value in OLD_VALUES:
                n = low.count(value)
                if n:
                    counts[value] = counts.get(value, 0) + n
        if counts:
            found[rel] = counts
    return found


def compare(found, baseline):
    """(failures, lowerable) as lists of human-readable lines."""
    failures, lowerable = [], []
    for rel, counts in sorted(found.items()):
        allowed = baseline.get(rel, {})
        for value, n in sorted(counts.items()):
            limit = allowed.get(value, 0)
            if n > limit:
                where = "a file with no baseline" if rel not in baseline else f"baseline {limit}"
                failures.append(f"{rel}: {value} x{n} ({where})")
    for rel, allowed in sorted(baseline.items()):
        for value, limit in sorted(allowed.items()):
            n = found.get(rel, {}).get(value, 0)
            if n < limit:
                lowerable.append(f'BASELINE["{rel}"]["{value}"]: lower the baseline to {n} (was {limit})')
    return failures, lowerable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    found = scan(args.root)
    failures, lowerable = compare(found, BASELINE)

    totals = {v: sum(c.get(v, 0) for c in found.values()) for v in OLD_VALUES}
    print(f"colour literals: {len(candidate_files(args.root))} files scanned, "
          f"{len(found)} hold a pre-Deep-Water value")
    print("  per value: " + ", ".join(f"{v} {n}" for v, n in totals.items()))
    for rel, counts in sorted(found.items()):
        print(f"  {rel}: " + ", ".join(f"{v} {n}" for v, n in sorted(counts.items())))
    for line in lowerable:
        print(f"  ratchet: {line}")

    if failures:
        print(
            "\n  CI STOPPED: a pre-Deep-Water colour literal was added.\n\n"
            "  If you are not Claude: nothing for you to fix. Paste this whole message to Claude.\n\n"
            "  Claude: CLAUDE.md says \"Never hardcode a colour.\" Replace the new literal with the\n"
            "  design token (var(--color-...)), do not raise BASELINE to make this pass.\n"
            + "\n".join(f"    {f}" for f in failures)
            + "\n",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
