# SPDX-License-Identifier: AGPL-3.0-or-later
"""Droppability acceptance: prove each optional module can actually be omitted.

**Why this spawns a subprocess instead of using ``override_settings``.**
``OPENH2O_MODULES`` is read from the environment at settings *import* time and
composes ``INSTALLED_APPS``. Django populates its app registry exactly once, at
startup, and builds the URLconf from whatever was installed then. By the time a
test body runs, the apps are loaded, the routes are registered and the tables
exist — ``override_settings(INSTALLED_APPS=...)`` changes a value nothing reads
again. The only honest way to prove a module is droppable is to boot a process
that never had it. Do not "simplify" this into an in-process test; doing so would
silently gut the gate while leaving it green.

``tests/droppability/checks.py`` is the body of the proof. This file is only the
spawner: it builds a reduced module list, runs that file in a fresh interpreter,
and surfaces the child's output when it fails. It is named ``test_*`` on purpose,
so ``make test`` carries it; the child is named ``checks.py`` on purpose, so a
normal collection does not.

Phases 82-85 bring a newly decoupled module under this gate by flipping
``required=False`` in ``core/modules.py``. Nothing in this file needs editing —
the parametrization reads ``OPTIONAL_MODULE_NAMES``.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from core.modules import (
    ALL_MODULE_NAMES,
    MODULE_REGISTRY,
    OPTIONAL_MODULE_NAMES,
    REQUIRED_MODULE_NAMES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHILD = "tests/droppability/checks.py"

#: One case per optional module, plus the harshest configuration there is: all of
#: them gone at once. ``None`` means "drop everything optional".
CASES = tuple(OPTIONAL_MODULE_NAMES) + (None,)


def _case_id(case):
    return "all-optional-dropped" if case is None else f"without-{case}"


def _module_list(dropped) -> str:
    """The comma-separated OPENH2O_MODULES value for a case."""
    if dropped is None:
        keep = [n for n in ALL_MODULE_NAMES if n in REQUIRED_MODULE_NAMES]
    else:
        keep = [n for n in ALL_MODULE_NAMES if n != dropped]
    return ",".join(keep)


DEFAULT_DATABASE_URL = "postgis://openh2o:openh2o@db:5432/openh2o"


def _database_url(case) -> str:
    """A DATABASE_URL whose database name is unique to this case.

    The child cannot share the parent's database. pytest-django derives the test
    database name from ``DATABASES['default']['NAME']``, so parent and child both
    land on ``test_openh2o`` — and the parent is still holding it, so the child's
    ``CREATE DATABASE`` fails before a single check runs. Renaming the source
    database per case gives each child its own ``test_openh2o_drop_<case>``.

    The source database itself never has to exist: Django creates the test
    database through a connection to the ``postgres`` maintenance database.
    """
    base = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    parts = urlsplit(base)
    name = parts.path.lstrip("/") or "openh2o"
    suffix = "all_optional" if case is None else case
    return urlunsplit(parts._replace(path=f"/{name}_drop_{suffix}"))


def test_no_optional_module_depends_on_another_optional_module():
    """The premise that makes dropping one module at a time a valid test.

    Every case above removes exactly one optional module and keeps the rest. That
    is only meaningful while no optional module needs another optional module: if
    one did, dropping the dependency would raise ``ImproperlyConfigured`` at
    startup and the case would be testing the validator rather than droppability.

    Today ``drinking`` is the only optional module with dependencies at all
    (``wells`` and ``standards``), and both are required modules, so both are
    always present. This assertion fails loudly on the day a future phase makes
    one optional module depend on another — at which point the parametrization
    above needs to grow dependency-aware cases rather than quietly testing the
    wrong thing.
    """
    optional = set(OPTIONAL_MODULE_NAMES)
    offenders = {
        name: sorted(set(MODULE_REGISTRY[name].requires) & optional)
        for name in OPTIONAL_MODULE_NAMES
        if set(MODULE_REGISTRY[name].requires) & optional
    }
    assert not offenders, (
        f"These optional modules depend on other optional modules: {offenders}. "
        f"Dropping one at a time no longer proves droppability — the run would "
        f"fail in validate_module_names() before reaching a single page render. "
        f"Give this file dependency-aware cases before relying on it again."
    )


@pytest.mark.parametrize("dropped", CASES, ids=[_case_id(c) for c in CASES])
def test_module_can_be_dropped(dropped):
    """Boot a process without the module and run the full check suite in it."""
    env = dict(os.environ)
    env["OPENH2O_MODULES"] = _module_list(dropped)
    env["DATABASE_URL"] = _database_url(dropped)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", CHILD, "-q", "--ds=config.settings.local"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        # Generous against a measured ~5s child. The point is not to be tight —
        # it is that a hung child fails this one case loudly instead of hanging
        # the entire suite with no explanation.
        timeout=300,
    )

    assert result.returncode == 0, (
        f"Dropping {_case_id(dropped)} broke the platform.\n"
        f"OPENH2O_MODULES={env['OPENH2O_MODULES']}\n\n"
        f"--- child stdout ---\n{result.stdout}\n"
        f"--- child stderr ---\n{result.stderr}"
    )
