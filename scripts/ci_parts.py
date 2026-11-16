#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deal the tests into the parallel jobs of .github/workflows/tests.yml.

The suite runs as several jobs at once. Every test file is one unit, except the
module-drop proof (tests/test_droppability_acceptance.py): it is about 30%
of the run on its own, so each of its cases is a unit of its own. The units are
dealt by measured seconds, longest first, each into the part with the fewest
seconds so far, so the parts finish close together. Dealing the files
round-robin by name, as tests.yml once did, left one part about 1.5 times as
long as another.

    # The module-drop node ids, as pytest collects them INSIDE the web container
    docker compose exec -T web python -m pytest --collect-only -q \\
        tests/test_droppability_acceptance.py --ds=config.settings.local > drop_ids.txt

    # The test files and module-drop cases for part 1 of 6, one per line
    python3 scripts/ci_parts.py --part 1 --parts 6 --drop-ids drop_ids.txt

    # Only check that the parts hold every test exactly once
    python3 scripts/ci_parts.py --check --parts 6 --drop-ids drop_ids.txt

    # Rewrite tests/ci_durations.tsv from the JUnit files of one or more CI runs
    # (the durations-<part> artifacts of tests.yml)
    python3 scripts/ci_parts.py --refresh run-*/durations-*/junit.xml

Without --drop-ids the module-drop file is one unit like any other file.

Why the module-drop cases come in as collected ids rather than a case list:
the cases are built from core.modules, which imports Django, and this script
runs on the runner host with no Django installed. pytest inside the container
already knows the exact ids, so the host only has to deal a list.

Every way of printing a part also checks it: the run fails when the parts do
not hold every test file (and, with --drop-ids, every module-drop case instead
of the module-drop file) exactly once, so no test can be quietly left out of CI.

About the seconds: tests/ci_durations.tsv holds one row per test file and one
per module-drop case (its pytest node id). The module-drop file's own weight is
the sum of its case rows. A file missing from the durations file is weighted
with the median of the known files, a missing case with the median of the
known cases, so a new test lands somewhere sensible without a refresh.
--refresh averages each unit over the JUnit files that hold it (one per run),
because the same test's seconds vary up to 2x between runs. JUnit gives each
test's own seconds; under xdist those run longer than serial ones, so refresh
from one kind of run consistently: the parts only need the RATIOS to be right.

Exit codes: 0 fine, 1 the parts do not hold every test exactly once or the
module-drop id list is empty, 2 bad arguments or an unreadable input file.

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
    """The parts would leave a test out of CI, or run one twice."""


def _is_case(unit):
    return "::" in unit


def test_modules(root=REPO_ROOT):
    """Every test module pytest would collect, as repository-relative paths."""
    found = set()
    for pattern in PATTERNS:
        found.update(glob.glob(pattern, root_dir=root))
    return sorted(found)


def read_durations(path=DURATIONS):
    """{file or node id: seconds} from the TSV. Lines starting with # are comments."""
    seconds = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        value, name = line.split("\t", 1)
        seconds[name.strip()] = float(value)
    return seconds


def units(modules, drop_ids=None):
    """What gets dealt: the test files, with the module-drop file's cases in its place.

    ``drop_ids`` None keeps the module-drop file as one unit.
    """
    if drop_ids is None:
        return sorted(set(modules))
    return sorted({m for m in modules if m != DROP_FILE} | set(drop_ids))


def weights(units, seconds):
    """Seconds for each unit; the module-drop file weighs what its cases weigh.

    An unknown file gets the median of the known files, an unknown case the
    median of the known cases.
    """
    case_rows = {k: s for k, s in seconds.items() if k.startswith(DROP_FILE + "::")}
    files = [u for u in units if not _is_case(u) and u != DROP_FILE]
    cases = [u for u in units if _is_case(u)]
    known_files = [seconds[f] for f in files if f in seconds]
    file_median = statistics.median(known_files) if known_files else 1.0
    known_cases = [seconds[c] for c in cases if c in seconds] or list(case_rows.values())
    case_median = statistics.median(known_cases) if known_cases else file_median

    result = {}
    for unit in units:
        if _is_case(unit):
            result[unit] = seconds.get(unit, case_median)
        elif unit == DROP_FILE:
            if case_rows:
                result[unit] = round(sum(case_rows.values()), 1)
            else:
                result[unit] = seconds.get(unit, file_median)
        else:
            result[unit] = seconds.get(unit, file_median)
    return result


def deal(units, seconds, parts):
    """The units in ``parts`` lists, longest first into the lightest part.

    Deterministic: ties on seconds break by name, ties on a part's total by
    the lower part number. Each part comes back sorted by name.
    """
    weight = weights(units, seconds)
    bins = [[] for _ in range(parts)]
    totals = [0.0] * parts
    for name in sorted(weight, key=lambda u: (-weight[u], u)):
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


def check_parts(modules, parts, drop_ids=None):
    """Raise PartsError unless the parts hold every unit exactly once.

    With ``drop_ids`` the module-drop file must not be dealt itself: its
    cases are, so dealing both would run each case twice.
    """
    if DROP_FILE not in modules:
        raise PartsError(f"missing from every part: the module-drop file {DROP_FILE}")
    _exactly_once(units(modules, drop_ids), [u for p in parts for u in p], "part")


def read_node_ids(lines):
    """The module-drop node ids in ``pytest --collect-only -q`` output."""
    ids = [line.strip() for line in lines if "::" in line]
    return [i for i in ids if i.startswith(DROP_FILE + "::")]


def _unit_of(case):
    """The durations key of a JUnit testcase, or None for a test outside tests/."""
    parts = case.get("classname", "").split(".")
    if len(parts) < 2 or parts[0] != "tests":
        return None
    module = f"tests/{parts[1]}.py"
    if module != DROP_FILE:
        return module
    return "::".join([module, *parts[2:], case.get("name", "")])


def junit_seconds(paths):
    """{unit: seconds}: summed per file within a JUnit file, averaged over the files.

    A unit's tests all land in one JUnit file per run, so averaging over the
    files that hold it averages over the runs.
    """
    totals, counts = {}, {}
    for path in paths:
        here = {}
        for case in ET.parse(path).iter("testcase"):
            unit = _unit_of(case)
            if unit is not None:
                here[unit] = here.get(unit, 0.0) + float(case.get("time", 0))
        for unit, value in here.items():
            totals[unit] = totals.get(unit, 0.0) + value
            counts[unit] = counts.get(unit, 0) + 1
    return {u: round(totals[u] / counts[u], 1) for u in totals}


def refresh(paths, durations=DURATIONS, root=REPO_ROOT):
    """Merge JUnit seconds into the durations file; return how many rows changed.

    Rows for files no longer in tests/ go. Once the module-drop file has case
    rows, its own whole-file row goes too, so it is not counted twice.
    """
    old = read_durations(durations) if Path(durations).exists() else {}
    fresh = junit_seconds(paths)
    present = set(test_modules(root))

    def keep(unit):
        return unit.split("::", 1)[0] in present

    merged = {u: s for u, s in old.items() if keep(u)}
    merged.update({u: s for u, s in fresh.items() if keep(u)})
    if any(u.startswith(DROP_FILE + "::") for u in merged):
        merged.pop(DROP_FILE, None)
    changed = sum(1 for u in set(merged) | set(old) if merged.get(u) != old.get(u))
    # Only each file's last three path parts (run/durations-1/junit.xml): the
    # full path would publish the folder layout of whoever ran the refresh.
    header = (
        f"# openh2o test seconds per file (and per module-drop case), averaged over "
        f"{len(paths)} JUnit file(s) by scripts/ci_parts.py --refresh, from: "
        + " ".join("/".join(Path(p).parts[-3:]) for p in paths)
    )
    rows = sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))
    Path(durations).write_text(
        header + "\n" + "".join(f"{s}\t{u}\n" for u, s in rows)
    )
    return changed


def _refuse(message):
    print(f"ci_parts.py: {message}", file=sys.stderr)
    print(FIXER, file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", type=int, help="print this part's tests (1-based)")
    ap.add_argument("--parts", type=int, default=3, help="how many parts (default 3)")
    ap.add_argument("--drop-ids", metavar="FILE",
                    help="`pytest --collect-only -q` output for the module-drop file; "
                         "its cases are then dealt one by one")
    ap.add_argument("--check", action="store_true",
                    help="only check that the parts hold every test once")
    ap.add_argument("--refresh", nargs="+", metavar="JUNIT",
                    help="rewrite tests/ci_durations.tsv from these JUnit files")
    args = ap.parse_args(argv)

    if args.refresh:
        try:
            changed = refresh(args.refresh)
        except (OSError, ET.ParseError) as error:
            print(f"ci_parts.py: cannot read a JUnit file: {error}", file=sys.stderr)
            return 2
        print(f"{changed} row(s) changed in {DURATIONS.relative_to(REPO_ROOT)}")
        return 0

    if args.parts < 1 or (args.part is not None and not 1 <= args.part <= args.parts):
        print(f"ci_parts.py: --part must be 1 to {args.parts}", file=sys.stderr)
        return 2
    if args.part is None and not args.check:
        ap.print_usage(sys.stderr)
        return 2

    drop_ids = None
    if args.drop_ids is not None:
        try:
            drop_ids = read_node_ids(Path(args.drop_ids).read_text().splitlines())
        except OSError as error:
            print(f"ci_parts.py: cannot read {args.drop_ids}: {error}", file=sys.stderr)
            return 2
        if not drop_ids:
            return _refuse(
                f"no {DROP_FILE} node ids in {args.drop_ids}. Fill it from `pytest "
                f"--collect-only -q {DROP_FILE}` run inside the web container; an "
                "empty list would run no module-drop test and still pass."
            )

    modules = test_modules()
    try:
        seconds = read_durations()
    except (OSError, ValueError) as error:
        print(f"ci_parts.py: cannot read {DURATIONS}: {error}", file=sys.stderr)
        return 2
    parts = deal(units(modules, drop_ids), seconds, args.parts)
    try:
        check_parts(modules, parts, drop_ids)
    except PartsError as error:
        return _refuse(
            f"the {args.parts} parts do not hold every test exactly once: {error}"
        )
    if args.part is not None:
        print("\n".join(parts[args.part - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
