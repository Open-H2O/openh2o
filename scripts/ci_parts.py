#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deal the test files into the parallel jobs of .github/workflows/tests.yml.

The suite runs as five jobs at once: three parts of ordinary test files and the
module-drop proof (tests/test_droppability_acceptance.py) split in two halves.
The parts are dealt by measured seconds, longest file first, each into the part
with the fewest seconds so far, so the three finish close together. Dealing the
files round-robin by name, as tests.yml once did, left one part about 1.5 times
as long as another.

    # The test files for part 1 of 3, one per line
    python3 scripts/ci_parts.py --part 1 --parts 3

    # The module-drop node ids for half 1 of 2. The ids come in on stdin, as
    # pytest collects them INSIDE the web container:
    docker compose exec -T web python -m pytest --collect-only -q \\
        tests/test_droppability_acceptance.py --ds=config.settings.local \\
      | python3 scripts/ci_parts.py --drop-half 1

    # Only check that the parts hold every test file exactly once
    python3 scripts/ci_parts.py --check --parts 3

    # Rewrite tests/ci_durations.tsv from the JUnit files of a CI run
    # (the durations-<part> artifacts of tests.yml)
    python3 scripts/ci_parts.py --refresh durations-*/junit.xml

Why the drop halves read collected ids rather than the case list: the cases
are built from core.modules, which imports Django, and this script runs on the
runner host with no Django installed. pytest inside the container already
knows the exact ids, so the host only has to split a list.

Every way of printing a part also checks it: the run fails when the parts and
the module-drop file do not hold every test file exactly once, or the two
halves do not hold every module-drop test exactly once, so no test can be
quietly left out of CI.

About --refresh: JUnit gives each test's own seconds. Under xdist those run
about 1.7 times the serial figure (four workers share the CPUs), so refresh
from one kind of run consistently; the parts only need the RATIOS to be right.
A file missing from the durations file is weighted with the median of the known
files, so a new test file lands somewhere sensible without a refresh.

Exit codes: 0 fine, 1 the parts or halves do not hold every test exactly once,
2 bad arguments or an unreadable input file.

Standard library only: it runs on the host, outside the image.
"""

import argparse
import glob
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DURATIONS = REPO_ROOT / "tests" / "ci_durations.tsv"
DROP_FILE = "tests/test_droppability_acceptance.py"
#: pyproject.toml's python_files, all directly in tests/.
PATTERNS = ("tests/test_*.py", "tests/*_tests.py", "tests/tests.py")

FIXER = (
    "(For Claude, as the fixer. If you are not Claude, paste this message to Claude.)"
)


class PartsError(Exception):
    """The parts or halves would leave a test out of CI, or run one twice."""


def test_modules(root=REPO_ROOT):
    """Every test module pytest would collect, as repository-relative paths."""
    found = set()
    for pattern in PATTERNS:
        found.update(glob.glob(pattern, root_dir=root))
    return sorted(found)


def read_durations(path=DURATIONS):
    """{module: seconds} from the TSV. Lines starting with # are comments."""
    seconds = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        value, name = line.split("\t")
        seconds[name.strip()] = float(value)
    return seconds


def weights(modules, seconds):
    """Seconds for each dealt module; a module with no figure gets the median."""
    dealt = [m for m in modules if m != DROP_FILE]
    known = [seconds[m] for m in dealt if m in seconds]
    fallback = statistics.median(known) if known else 1.0
    return {m: seconds.get(m, fallback) for m in dealt}


def deal(modules, seconds, parts):
    """The dealt modules in ``parts`` lists, longest first into the lightest part.

    Deterministic: ties on seconds break by name, ties on a part's total by
    the lower part number. Each part's files come back sorted by name.
    """
    weight = weights(modules, seconds)
    bins = [[] for _ in range(parts)]
    totals = [0.0] * parts
    for name in sorted(weight, key=lambda m: (-weight[m], m)):
        lightest = min(range(parts), key=lambda k: (totals[k], k))
        bins[lightest].append(name)
        totals[lightest] += weight[name]
    return [sorted(b) for b in bins]


def _exactly_once(expected, dealt, what):
    seen, twice = set(), set()
    for item in dealt:
        (twice if item in seen else seen).add(item)
    missing = sorted(set(expected) - seen)
    extra = sorted(seen - set(expected))
    problems = []
    if missing:
        problems.append(f"missing from every {what}: {missing}")
    if twice:
        problems.append(f"dealt more than once: {sorted(twice)}")
    if extra:
        problems.append(f"dealt but not a test here: {extra}")
    if problems:
        raise PartsError("; ".join(problems))


def check_parts(modules, parts):
    """Raise PartsError unless the parts plus the module-drop file hold every module once."""
    if DROP_FILE not in modules:
        raise PartsError(f"missing from every part: the module-drop file {DROP_FILE}")
    _exactly_once(modules, [m for p in parts for m in p] + [DROP_FILE], "part")


def drop_half(node_ids, half):
    """Half ``half`` (1 or 2) of the module-drop node ids, alternating in sorted order.

    Sorted ids keep each test function's cases together, so alternating gives
    each half about half of every function's cases, including the expensive
    subprocess ones.
    """
    return sorted(node_ids)[half - 1::2]


def check_halves(node_ids, halves):
    _exactly_once(node_ids, [i for h in halves for i in h], "half")


def read_node_ids(stream):
    """The node ids in ``pytest --collect-only -q`` output (lines with ``::``)."""
    ids = [line.strip() for line in stream if "::" in line]
    return [i for i in ids if i.startswith(DROP_FILE + "::")]


def junit_seconds(paths):
    """{module: seconds} summed from the testcase ``time`` attributes of JUnit files."""
    seconds = {}
    for path in paths:
        for case in ET.parse(path).iter("testcase"):
            parts = case.get("classname", "").split(".")
            if len(parts) < 2 or parts[0] != "tests":
                continue
            module = f"tests/{parts[1]}.py"
            seconds[module] = seconds.get(module, 0.0) + float(case.get("time", 0))
    return {m: round(s, 1) for m, s in seconds.items()}


def refresh(paths, durations=DURATIONS, root=REPO_ROOT):
    """Merge JUnit seconds into the durations file; return how many modules changed."""
    old = read_durations(durations) if Path(durations).exists() else {}
    fresh = junit_seconds(paths)
    present = set(test_modules(root))
    merged = {m: s for m, s in old.items() if m in present}
    merged.update({m: s for m, s in fresh.items() if m in present})
    changed = sum(1 for m in set(merged) | set(old) if merged.get(m) != old.get(m))
    # Only each file's last two path parts (durations-1/junit.xml): the full
    # path would publish the folder layout of whoever ran the refresh.
    header = (
        "# openh2o per-file test seconds, summed from JUnit testcase times by "
        "scripts/ci_parts.py --refresh, from: "
        + " ".join("/".join(Path(p).parts[-2:]) for p in paths)
    )
    rows = sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))
    Path(durations).write_text(
        header + "\n" + "".join(f"{s}\t{m}\n" for m, s in rows)
    )
    return changed


def _refuse(message):
    print(f"ci_parts.py: {message}", file=sys.stderr)
    print(FIXER, file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", type=int, help="print this part's test files (1-based)")
    ap.add_argument("--parts", type=int, default=3, help="how many parts (default 3)")
    ap.add_argument("--drop-half", type=int, choices=(1, 2),
                    help="print this half of the module-drop node ids read on stdin")
    ap.add_argument("--check", action="store_true",
                    help="only check that the parts hold every test file once")
    ap.add_argument("--refresh", nargs="+", metavar="JUNIT",
                    help="rewrite tests/ci_durations.tsv from these JUnit files")
    args = ap.parse_args(argv)

    if args.refresh:
        try:
            changed = refresh(args.refresh)
        except (OSError, ET.ParseError) as error:
            print(f"ci_parts.py: cannot read a JUnit file: {error}", file=sys.stderr)
            return 2
        print(f"{changed} module(s) changed in {DURATIONS.relative_to(REPO_ROOT)}")
        return 0

    if args.drop_half:
        ids = read_node_ids(sys.stdin)
        if not ids:
            return _refuse(
                f"no {DROP_FILE} node ids on stdin. Pipe in `pytest --collect-only -q "
                f"{DROP_FILE}` run inside the web container; an empty list would "
                "run no module-drop test and still pass."
            )
        halves = [drop_half(ids, h) for h in (1, 2)]
        try:
            check_halves(ids, halves)
        except PartsError as error:
            return _refuse(f"the two module-drop halves are wrong: {error}")
        print("\n".join(halves[args.drop_half - 1]))
        return 0

    if args.parts < 1 or (args.part is not None and not 1 <= args.part <= args.parts):
        print(f"ci_parts.py: --part must be 1 to {args.parts}", file=sys.stderr)
        return 2
    if args.part is None and not args.check:
        ap.print_usage(sys.stderr)
        return 2
    modules = test_modules()
    try:
        seconds = read_durations()
    except (OSError, ValueError) as error:
        print(f"ci_parts.py: cannot read {DURATIONS}: {error}", file=sys.stderr)
        return 2
    parts = deal(modules, seconds, args.parts)
    try:
        check_parts(modules, parts)
    except PartsError as error:
        return _refuse(
            f"the {args.parts} parts and {DROP_FILE} do not hold every test file "
            f"exactly once: {error}"
        )
    if args.part is not None:
        print("\n".join(parts[args.part - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
