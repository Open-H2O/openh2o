#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""List every printed demonstration figure that differs between two figure files.

tests/test_year_reading_demonstration.py, run in write mode, writes every figure the
demonstration's year pages print: the dashboard, the accounts list, each zone, account and use
area, month by month. tests/data/demonstration_figures_before.json is that file as last approved,
and the release test fails on the first figure that differs from it. This script lists them all:

    python3 -I scripts/figures_moved.py [--before FILE | --base-commit COMMIT [--repo DIR]] NOW [--tsv OUT]

Before is the stored file in the working tree unless --before names a file or --base-commit names
a commit whose stored file to read (git show). NOW is a file the release test wrote
(YEAR_FIGURES_OUT=<path>; `make figures-moved` does both steps).

Printed: one line per moved value (path, before, now, change; tab separated), then a summary
after a line starting "#": how many moved, per water year and section, and the largest moves.
"No printed figure moved." when none did. The exit is 0 either way: this measures; whether a move
is intended is for the person who made the change to say. Standard library only.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

STORED = "tests/data/demonstration_figures_before.json"
LARGEST = 10


def row_key(row):
    """A figures row is scope, name, month, figure, value, method, detail: its key is all but the value."""
    return tuple(row[:4]) + tuple(row[5:])


def change(before, now):
    """now - before for two "D:<decimal>" values, else empty."""
    if isinstance(before, str) and isinstance(now, str) and before.startswith("D:") and now.startswith("D:"):
        try:
            return str(Decimal(now[2:]) - Decimal(before[2:]))
        except InvalidOperation:
            return ""
    return ""


def differences(before, now):
    """(path, before, now, change) for every leaf that differs, in path order."""
    out = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                if k not in x or k not in y:
                    out.append((f"{path}.{k}", x.get(k, "<absent>"), y.get(k, "<absent>"), ""))
                else:
                    walk(x[k], y[k], f"{path}.{k}")
        elif isinstance(x, list) and isinstance(y, list) and path.endswith(".figures"):
            xa = {row_key(r): r[4] for r in x}
            ya = {row_key(r): r[4] for r in y}
            for k in sorted(set(xa) | set(ya), key=str):
                if xa.get(k) != ya.get(k):
                    a, b = xa.get(k, "<absent>"), ya.get(k, "<absent>")
                    out.append((f"{path}{list(k)}", a, b, change(a, b)))
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (p, q) in enumerate(zip(x, y)):
                walk(p, q, f"{path}[{i}]")
        elif x != y:
            out.append((path, x, y, change(x, y)))

    walk(before, now, "")
    return out


def section(path):
    """The water year and the section a path sits in: ".WY 2024-2025.zone_pages.X..." gives both."""
    parts = path.lstrip(".").split(".", 2)
    head = parts[0]
    sec = (parts[1] if len(parts) > 1 else "").split("[", 1)[0]
    return head, sec


def summary(rows):
    if not rows:
        return ["No printed figure moved."]
    lines = [f"# {len(rows)} printed values moved"]
    by_year = {}
    for path, *_ in rows:
        y, s = section(path)
        by_year.setdefault(y, Counter())[s] += 1
    for y in sorted(by_year):
        counts = by_year[y]
        parts = ", ".join(f"{s} {n}" for s, n in sorted(counts.items()))
        lines.append(f"{y}: {sum(counts.values())} ({parts})")
    sized = [r for r in rows if r[3]]
    sized.sort(key=lambda r: abs(Decimal(r[3])), reverse=True)
    if sized:
        lines.append(f"Largest {min(LARGEST, len(sized))} by size of change:")
        lines += [f"  {r[3]}\t{r[0]}\t{r[1]} to {r[2]}" for r in sized[:LARGEST]]
    return lines


def read_before(args):
    if args.before:
        return json.loads(Path(args.before).read_text(encoding="utf-8"))
    if args.base_commit:
        text = subprocess.run(
            ["git", "-C", args.repo, "show", f"{args.base_commit}:{STORED}"],
            check=True, capture_output=True, text=True,
        ).stdout
        return json.loads(text)
    return json.loads((Path(args.repo) / STORED).read_text(encoding="utf-8"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    which = p.add_mutually_exclusive_group()
    which.add_argument("--before", help="a figures file to compare against")
    which.add_argument("--base-commit", help="read the stored figures file as it was at this commit")
    p.add_argument("--repo", default=".", help="the repository (default: the working folder)")
    p.add_argument("--tsv", help="write the moved values here instead of printing them")
    p.add_argument("now", help="a figures file the release test wrote")
    args = p.parse_args(argv)

    rows = differences(read_before(args), json.loads(Path(args.now).read_text(encoding="utf-8")))
    lines = ["\t".join(map(str, r)) for r in rows]
    if args.tsv:
        Path(args.tsv).write_text("path\tbefore\tnow\tchange\n" + "".join(line + "\n" for line in lines), encoding="utf-8")
    else:
        for line in lines:
            print(line)
    for line in summary(rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
