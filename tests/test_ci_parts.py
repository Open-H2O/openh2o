# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for scripts/ci_parts.py, which deals the test files into CI's parallel jobs.

The script runs on the runner host, outside the image, so it is loaded from its
file here, the way tests/test_ci_gate.py loads ci_gate.py. The module names and
seconds below are invented (TEST DATA); the last test reads the real durations
file and the real tests/ folder.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci_parts.py"


def _load():
    spec = importlib.util.spec_from_file_location("ci_parts_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_parts = _load()

DROP = ci_parts.DROP_FILE
MODULES = [f"tests/test_m{n:02d}.py" for n in range(12)] + [DROP]
SECONDS = {f"tests/test_m{n:02d}.py": float(10 + 7 * n) for n in range(12)}
SECONDS[DROP] = 999.0


def test_dealing_is_deterministic():
    first = ci_parts.deal(MODULES, SECONDS, 3)
    again = ci_parts.deal(list(reversed(MODULES)), dict(SECONDS), 3)
    assert first == again


def test_every_module_lands_exactly_once_and_the_drop_file_in_none():
    parts = ci_parts.deal(MODULES, SECONDS, 3)
    dealt = [m for part in parts for m in part]
    assert sorted(dealt) == sorted(m for m in MODULES if m != DROP)
    assert DROP not in dealt
    ci_parts.check_parts(MODULES, parts)  # raises on a fault


def test_parts_are_balanced_by_seconds():
    parts = ci_parts.deal(MODULES, SECONDS, 3)
    totals = [sum(SECONDS[m] for m in part) for part in parts]
    assert max(totals) - min(totals) <= max(SECONDS[m] for m in MODULES if m != DROP)


def test_an_unknown_module_gets_the_median_of_the_known_times():
    known = {m: s for m, s in SECONDS.items() if m != "tests/test_m05.py"}
    weights = ci_parts.weights(MODULES, known)
    # The eleven known files take 10, 17, 24, 31, 38, 52, 59, 66, 73, 80 and
    # 87 seconds (m05's 45 is the unknown one); the drop file's 999 is not
    # dealt, so it does not count.
    assert weights["tests/test_m05.py"] == 52.0


def test_the_check_fails_on_a_missing_module():
    parts = ci_parts.deal(MODULES, SECONDS, 3)
    parts[0] = parts[0][1:]
    with pytest.raises(ci_parts.PartsError, match="missing"):
        ci_parts.check_parts(MODULES, parts)


def test_the_check_fails_on_a_duplicated_module():
    parts = ci_parts.deal(MODULES, SECONDS, 3)
    parts[1] = parts[1] + [parts[0][0]]
    with pytest.raises(ci_parts.PartsError, match="more than once"):
        ci_parts.check_parts(MODULES, parts)


def test_the_two_drop_halves_cover_every_case_once():
    ids = [f"{DROP}::test_a[case{n}]" for n in range(15)]
    ids += [f"{DROP}::test_b[case{n}]" for n in range(15)]
    halves = [ci_parts.drop_half(ids, h) for h in (1, 2)]
    assert sorted(halves[0] + halves[1]) == sorted(ids)
    assert not set(halves[0]) & set(halves[1])
    assert abs(len(halves[0]) - len(halves[1])) <= 1
    # each half carries about half of each test function's cases
    for name in ("test_a", "test_b"):
        counts = [sum(name in i for i in half) for half in halves]
        assert abs(counts[0] - counts[1]) <= 1
    ci_parts.check_halves(ids, halves)


def test_the_halves_check_fails_on_a_lost_case():
    ids = [f"{DROP}::test_a[case{n}]" for n in range(4)]
    with pytest.raises(ci_parts.PartsError, match="missing"):
        ci_parts.check_halves(ids, [ids[:1], ids[2:]])


def test_refresh_sums_junit_seconds_per_module(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite name="pytest">'
        '<testcase classname="tests.test_m00" name="a" time="1.5" />'
        '<testcase classname="tests.test_m00" name="b" time="2.0" />'
        '<testcase classname="tests.test_m01.TestThing" name="c" time="4.5" />'
        "</testsuite></testsuites>"
    )
    assert ci_parts.junit_seconds([junit]) == {
        "tests/test_m00.py": 3.5,
        "tests/test_m01.py": 4.5,
    }


def test_the_real_parts_hold_every_test_module_once():
    """The committed durations file and today's tests/ folder, dealt as CI deals them."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--parts", "3"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
