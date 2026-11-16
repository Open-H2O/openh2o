# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for scripts/ci_parts.py, which deals the tests into CI's parallel jobs.

The script runs on the runner host, outside the image, so it is loaded from its
file here, the way tests/test_ci_gate.py loads ci_gate.py. The module names,
case ids and seconds below are invented (TEST DATA); the last test reads the
real durations file and the real tests/ folder.
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
IDS = [f"{DROP}::test_dropped[case{n}]" for n in range(6)]
SECONDS.update({case: 40.0 + n for n, case in enumerate(IDS)})


def _all(parts):
    return [unit for part in parts for unit in part]


def test_dealing_is_deterministic():
    first = ci_parts.deal(ci_parts.units(MODULES, IDS), SECONDS, 3)
    again = ci_parts.deal(
        ci_parts.units(list(reversed(MODULES)), list(reversed(IDS))), dict(SECONDS), 3
    )
    assert first == again


def test_with_case_ids_every_file_and_case_lands_once_and_the_drop_file_never():
    parts = ci_parts.deal(ci_parts.units(MODULES, IDS), SECONDS, 4)
    dealt = _all(parts)
    assert sorted(dealt) == sorted([m for m in MODULES if m != DROP] + IDS)
    assert DROP not in dealt
    ci_parts.check_parts(MODULES, parts, IDS)  # raises on a fault


def test_without_case_ids_the_drop_file_is_one_unit():
    parts = ci_parts.deal(ci_parts.units(MODULES), SECONDS, 3)
    assert sorted(_all(parts)) == sorted(MODULES)
    ci_parts.check_parts(MODULES, parts)


def test_the_drop_file_unit_weighs_what_its_cases_weigh():
    weights = ci_parts.weights(ci_parts.units(MODULES), SECONDS)
    assert weights[DROP] == sum(40.0 + n for n in range(6))


def test_parts_are_balanced_by_seconds():
    units = ci_parts.units(MODULES, IDS)
    weights = ci_parts.weights(units, SECONDS)
    totals = [sum(weights[u] for u in part) for part in ci_parts.deal(units, SECONDS, 4)]
    assert max(totals) - min(totals) <= max(weights.values())


def test_an_unknown_module_gets_the_median_of_the_known_files():
    known = {k: s for k, s in SECONDS.items() if k != "tests/test_m05.py"}
    weights = ci_parts.weights(ci_parts.units(MODULES, IDS), known)
    # The eleven known files take 10, 17, 24, 31, 38, 52, 59, 66, 73, 80 and 87
    # seconds (m05's 45 is the unknown one); the cases' seconds do not count.
    assert weights["tests/test_m05.py"] == 52.0


def test_an_unknown_case_gets_the_median_of_the_known_cases():
    new_case = f"{DROP}::test_dropped[brand-new]"
    weights = ci_parts.weights(ci_parts.units(MODULES, IDS + [new_case]), SECONDS)
    assert weights[new_case] == 42.5  # median of 40 to 45


def test_the_check_fails_on_a_missing_module():
    parts = ci_parts.deal(ci_parts.units(MODULES, IDS), SECONDS, 3)
    parts[0] = [u for u in parts[0] if u != "tests/test_m11.py"]
    parts[1] = [u for u in parts[1] if u != "tests/test_m11.py"]
    parts[2] = [u for u in parts[2] if u != "tests/test_m11.py"]
    with pytest.raises(ci_parts.PartsError, match="missing"):
        ci_parts.check_parts(MODULES, parts, IDS)


def test_the_check_fails_on_a_missing_case():
    parts = ci_parts.deal(ci_parts.units(MODULES, IDS), SECONDS, 3)
    parts = [[u for u in part if u != IDS[0]] for part in parts]
    with pytest.raises(ci_parts.PartsError, match="missing"):
        ci_parts.check_parts(MODULES, parts, IDS)


def test_the_check_fails_on_a_duplicated_case():
    parts = ci_parts.deal(ci_parts.units(MODULES, IDS), SECONDS, 3)
    parts[0] = parts[0] + [IDS[0]] if IDS[0] not in parts[0] else parts[0]
    parts[1] = parts[1] + [IDS[0]] if IDS[0] not in parts[1] else parts[1]
    with pytest.raises(ci_parts.PartsError, match="more than once"):
        ci_parts.check_parts(MODULES, parts, IDS)


def test_the_check_fails_when_the_drop_file_and_its_cases_are_both_dealt():
    parts = ci_parts.deal(ci_parts.units(MODULES, IDS), SECONDS, 3)
    parts[0] = parts[0] + [DROP]
    with pytest.raises(ci_parts.PartsError, match="not a test here"):
        ci_parts.check_parts(MODULES, parts, IDS)


def _junit(path, cases):
    path.write_text(
        '<testsuites><testsuite name="pytest">'
        + "".join(
            f'<testcase classname="{c}" name="{n}" time="{t}" />' for c, n, t in cases
        )
        + "</testsuite></testsuites>"
    )
    return path


def test_refresh_sums_per_module_and_keeps_drop_cases_apart(tmp_path):
    junit = _junit(tmp_path / "junit.xml", [
        ("tests.test_m00", "a", 1.5),
        ("tests.test_m00", "b", 2.0),
        ("tests.test_m01.TestThing", "c", 4.5),
        ("tests.test_droppability_acceptance", "test_dropped[case0]", 30.0),
    ])
    assert ci_parts.junit_seconds([junit]) == {
        "tests/test_m00.py": 3.5,
        "tests/test_m01.py": 4.5,
        f"{DROP}::test_dropped[case0]": 30.0,
    }


def test_refresh_averages_a_unit_over_the_runs_that_hold_it(tmp_path):
    run1 = _junit(tmp_path / "run1.xml", [("tests.test_m00", "a", 2.0)])
    run2 = _junit(tmp_path / "run2.xml", [
        ("tests.test_m00", "a", 4.0), ("tests.test_m01", "b", 5.0),
    ])
    assert ci_parts.junit_seconds([run1, run2]) == {
        "tests/test_m00.py": 3.0,
        "tests/test_m01.py": 5.0,
    }


def test_refresh_keys_a_drop_case_in_a_class_by_its_node_id(tmp_path):
    junit = _junit(tmp_path / "junit.xml", [
        ("tests.test_droppability_acceptance.TestDropClosure", "test_x", 7.0),
    ])
    assert ci_parts.junit_seconds([junit]) == {f"{DROP}::TestDropClosure::test_x": 7.0}


def test_an_empty_drop_id_list_is_refused(tmp_path):
    empty = tmp_path / "drop_ids.txt"
    empty.write_text("no tests collected\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--part", "1", "--parts", "6", "--drop-ids", str(empty)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "For Claude" in result.stderr


def test_the_real_parts_hold_every_test_module_once():
    """The committed durations file and today's tests/ folder, dealt as CI deals them."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--parts", "6"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
