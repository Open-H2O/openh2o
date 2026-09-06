# SPDX-License-Identifier: AGPL-3.0-or-later
"""The figure ledger's recomputations must not call the code they check.

This is the guard on the correctness argument the whole figure ledger rests on.
A recomputation that imports ``accounting.services`` and calls
``consumptive_use_balance`` does not measure the platform — it measures whether
that function is deterministic, which it is. It would pass on a codebase whose
arithmetic was wrong in every figure.

So every ``audit/figure_ledger/sql/*.sql`` file is read here AS TEXT and refused
if it imports a module or calls a function the application defines. The function
names are collected by parsing the modules with ``ast``, never hardcoded: a
hardcoded list goes stale the first time a service gains a function, and a stale
allow-list is a guard that has silently stopped guarding.

⚠ ``FROM parcels_parcel`` is a table reference, not a Python import. The forbidden
patterns below are matched as Python *statement shapes* precisely so a legitimate
SQL ``FROM`` clause does not trip them — a guard that fires on every correct file
gets disabled within a week, and then nothing is guarded at all.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "audit" / "figure_ledger" / "sql"

#: The modules whose functions a recomputation must never call.
GUARDED_MODULES = (
    "accounting/services.py",
    "surface/services.py",
    "accounting/calculation.py",
)

#: Python statement shapes. Written as regexes over the raw text because that is
#: all a .sql file is — there is nothing to parse, and a substring search would
#: fire on ``FROM parcels_parcel``.
FORBIDDEN_PATTERNS = (
    (r"\bimport\s+[A-Za-z_]", "a Python import statement"),
    (r"\bmanage\.py\b", "a manage.py invocation"),
    (r"\bdjango\b", "the object-relational mapper"),
    (
        r"\bfrom\s+(accounting|surface|parcels|geography|wells|recharge|core|config)\s+import\b",
        "an import of an application module",
    ),
)


def _sql_files():
    if not SQL_DIR.is_dir():
        return []
    return sorted(SQL_DIR.glob("*.sql"))


def _guarded_function_names():
    """Every function name defined in the guarded modules, parsed not listed."""
    names = set()
    for relative in GUARDED_MODULES:
        path = REPO_ROOT / relative
        if not path.exists():  # pragma: no cover - a module was renamed
            pytest.fail(
                f"{relative} does not exist. The independence guard names it as a "
                "module the recomputations must not call; if it moved, update "
                "GUARDED_MODULES rather than letting the guard check nothing."
            )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return names


def test_guarded_modules_yield_function_names():
    """The name collection itself must not silently return an empty set.

    An empty set makes every call check below pass unconditionally — the guard
    would be green while guarding nothing, which is the failure mode this whole
    file exists to prevent elsewhere.
    """
    names = _guarded_function_names()
    assert len(names) >= 20, (
        "parsed only %d function names out of %s — the guard would be vacuous"
        % (len(names), ", ".join(GUARDED_MODULES))
    )
    assert "consumptive_use_balance" in names
    assert "billable_ledger" in names


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: p.name)
def test_sql_file_imports_no_application_code(path):
    text = path.read_text(encoding="utf-8")
    for pattern, description in FORBIDDEN_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            pytest.fail(
                f"{path.name}:{line} contains {description} "
                f"({match.group(0)!r}). A recomputation that reaches into the "
                "application is checking the application against itself."
            )


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: p.name)
def test_sql_file_calls_no_application_function(path):
    text = path.read_text(encoding="utf-8")
    for name in sorted(_guarded_function_names()):
        # A CALL, not a mention: prose in a comment may name the function whose
        # constant or exclusion rule was transcribed, and should, because that is
        # the provenance a reader needs. `name(` is the thing that would make the
        # check circular.
        match = re.search(rf"\b{re.escape(name)}\s*\(", text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            pytest.fail(
                f"{path.name}:{line} calls {name}() — defined in one of "
                f"{', '.join(GUARDED_MODULES)}. The recomputation must start "
                "from the stored rows, not from the code that produced them."
            )


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: p.name)
def test_sql_file_declares_which_figures_it_recomputes(path):
    """Every file names its ledger rows, so an orphan cannot accumulate here."""
    text = path.read_text(encoding="utf-8")
    assert re.search(r"^--.*\bFIG-", text, flags=re.MULTILINE), (
        f"{path.name} has no `-- FIG-` header line. A recomputation file that "
        "does not say which ledger rows it produces stops matching them without "
        "anything going red."
    )


def test_the_guard_is_not_vacuous():
    """There is at least one recomputation file for the guard to guard.

    The three checks above are parametrized over the SQL directory. With no files
    in it they collect zero cases and the module reports green while checking
    nothing — the exact shape of "0 firings read as effective" this project has
    been caught by before.
    """
    files = _sql_files()
    assert files, (
        f"{SQL_DIR} holds no .sql files, so every independence check above is "
        "parametrized over an empty list and passes without running."
    )
