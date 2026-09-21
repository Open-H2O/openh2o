# SPDX-License-Identifier: AGPL-3.0-or-later
"""146-01 Task 1: the persisted shape stand-up script is syntactically valid and
its per-shape module lists are real, registry-valid configurations.

No Docker needed: `bash -n` checks syntax without running anything, and
`core.modules.validate_module_names` is a pure function safe to call without a
database. Actually standing a shape up and walking it is Task 1's manual verify
step, not this test.
"""
import re
import subprocess
from pathlib import Path

import pytest

from core.modules import ALL_MODULE_NAMES, validate_module_names

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "shape_stack.sh"

# Mirrors the `case "$1" in ... esac` body of `modules_for()` in
# scripts/shape_stack.sh: one quoted, comma-separated module list per shape
# number 1-6, shape 6 empty (meaning "all sixteen", per OPENH2O_MODULES' own
# fallback in config/settings/base.py).
SHAPE_LINE_RE = re.compile(r'^\s*(\d)\)\s*echo\s*"([^"]*)"', re.MULTILINE)


def test_shape_stack_script_bash_syntax_is_clean():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _module_lists_from_script():
    text = SCRIPT.read_text()
    found = dict(SHAPE_LINE_RE.findall(text))
    assert set(found) == {"1", "2", "3", "4", "5", "6"}, (
        f"expected shapes 1-6 in modules_for(), found {sorted(found)}"
    )
    return found


@pytest.mark.parametrize("shape", ["1", "2", "3", "4", "5", "6"])
def test_each_shapes_module_list_is_registry_valid(shape):
    lists = _module_lists_from_script()
    raw = lists[shape]
    names = tuple(m.strip() for m in raw.split(",") if m.strip())
    if shape == "6":
        # Empty string means "all sixteen", the same fallback OPENH2O_MODULES
        # itself applies (config/settings/base.py: `... or list(ALL_MODULE_NAMES)`).
        assert names == ()
        names = ALL_MODULE_NAMES
    # Raises ImproperlyConfigured on an unknown module, a duplicate, or a missing
    # required/dependency module, so this is a real validation, not a shape check.
    validated = validate_module_names(names)
    assert set(validated) == set(names)


def test_shape_module_lists_match_145_02_evidence():
    """Pins the six lists against 145-02-EVIDENCE.md's per-shape table (the
    plan's own source), so a future edit to the script cannot silently drift
    from the measured recipe."""
    lists = _module_lists_from_script()
    expected = {
        "1": "core,geography,measurements,standards,parcels,accounting,surface,reporting,setup,infrastructure,health,feedback",
        "2": "core,geography,measurements,standards,drinking,setup,infrastructure,health,feedback",
        "3": "core,geography,measurements,standards,parcels,accounting,datasync,setup,infrastructure,health,feedback",
        "4": "core,geography,measurements,standards,parcels,accounting,wells,datasync,setup,infrastructure,health,feedback",
        "5": "core,geography,measurements,standards,parcels,accounting,surface,recharge,setup,infrastructure,health,feedback",
        "6": "",
    }
    for shape, modules in expected.items():
        assert lists[shape] == modules, f"shape {shape}: {lists[shape]!r} != {modules!r}"


def test_script_never_touches_the_maintainers_own_stacks():
    """The literal project names `openh2o` and `openh2o-staging` (MAINTAINER.md's
    live checkouts) must never appear as a docker compose -p argument in this
    script; only openh2o-shape-<n> may."""
    text = SCRIPT.read_text()
    for line in text.splitlines():
        if "-p " not in line and "-p\"" not in line:
            continue
        assert "openh2o-staging" not in line
        assert re.search(r'-p\s+"?openh2o"?(\s|"|$)', line) is None


def test_script_is_executable():
    assert SCRIPT.stat().st_mode & 0o111, "scripts/shape_stack.sh must be chmod +x"
