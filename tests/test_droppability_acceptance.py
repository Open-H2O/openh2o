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

Phases 87-89 bring a newly decoupled module under this gate by flipping
``required=False`` in ``core/modules.py``. Nothing in this file needs editing —
the parametrization reads ``OPTIONAL_MODULE_NAMES``, and the cases it builds are
dependency-closure-aware, so a module that validly drags another out with it
generates the right configuration on its own.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.modules import (
    ALL_MODULE_NAMES,
    MODULE_REGISTRY,
    OPTIONAL_MODULE_NAMES,
    REQUIRED_MODULE_NAMES,
    ModuleSpec,
    validate_module_names,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHILD = "tests/droppability/checks.py"

#: One case per optional module, plus the harshest configuration there is: all of
#: them gone at once. ``None`` means "drop everything optional".
CASES = tuple(OPTIONAL_MODULE_NAMES) + (None,)


def _case_id(case):
    """Name a case by everything it actually drops, not just the module it targets.

    Phase 87: `without-surface` boots without `recharge` too, because the closure
    below drags it out. An id that named only `surface` would understate what
    `make test-droppable` just proved. Display only — no assertion depends on it.
    """
    if case is None:
        return "all-optional-dropped"
    gone = sorted(drop_closure(case))
    if gone == [case]:
        return f"without-{case}"
    return "without-" + "+".join([case] + [n for n in gone if n != case])


def drop_closure(dropped, registry=None, optional=None) -> frozenset:
    """Every optional module that has to go when ``dropped`` goes.

    Dropping X is only a valid configuration if every optional module that
    depends on X — directly or transitively — leaves with it. Otherwise
    ``validate_module_names`` raises at startup and the case ends up testing the
    validator instead of droppability.

    Today every closure is just the module itself, because no optional module
    requires another optional one. **Phase 87 is what changes that**: ``recharge``
    declares ``requires=(..., "surface")``, so the moment ``surface`` becomes
    optional, dropping it validly takes ``recharge`` too — and this function is
    what makes the harness generate that configuration with no edit to any test
    file. That is the same claim Phase 82 proved for flag-flipping, extended to
    dependencies.

    Only OPTIONAL modules can be dragged out. A required module cannot be
    dropped at all, so a required module depending on an optional one would be a
    registry bug rather than a case to generate — and
    ``tests/test_composition_rule.py`` is where that gets caught.

    Iterative with a visited set on purpose: ``requires`` is allowed to contain
    cycles (``measurements`` and ``standards`` genuinely reference each other),
    and a naive recursive walk would not terminate.
    """
    registry = MODULE_REGISTRY if registry is None else registry
    optional = OPTIONAL_MODULE_NAMES if optional is None else optional

    closure = {dropped}
    while True:
        added = {
            name
            for name in optional
            if name not in closure and set(registry[name].requires) & closure
        }
        if not added:
            return frozenset(closure)
        closure |= added


def _kept_names(dropped) -> list:
    """The module names a case boots with, in registry order."""
    if dropped is None:
        return [n for n in ALL_MODULE_NAMES if n in REQUIRED_MODULE_NAMES]
    gone = drop_closure(dropped)
    return [n for n in ALL_MODULE_NAMES if n not in gone]


def _module_list(dropped) -> str:
    """The comma-separated OPENH2O_MODULES value for a case."""
    return ",".join(_kept_names(dropped))


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


@pytest.mark.parametrize("dropped", CASES, ids=[_case_id(c) for c in CASES])
def test_case_is_the_exact_requires_closure_and_validates(dropped):
    """The premise that makes each case a valid test of droppability.

    This replaces the old ``no optional module depends on another optional
    module`` guard, whose premise stops being true by design in Phase 87: once
    ``surface`` is optional, ``recharge`` — which requires it — is an optional
    module depending on an optional module, and that is correct rather than a
    violation.

    The premise that survives is narrower and stronger. A case must drop exactly
    the requires-closure of the module it names — no more, so it is not quietly
    proving something easier than it claims, and no less, so it is not handing
    the child an invalid configuration. If a generated list does not validate,
    the child process would die in ``validate_module_names`` before rendering a
    single page, and this file would be testing the validator while looking like
    a droppability gate.
    """
    kept = _kept_names(dropped)
    expected_gone = (
        set(OPTIONAL_MODULE_NAMES) if dropped is None else drop_closure(dropped)
    )
    assert set(ALL_MODULE_NAMES) - set(kept) == expected_gone
    assert kept == [n for n in ALL_MODULE_NAMES if n in kept], "not in registry order"

    try:
        validate_module_names(kept)
    except ImproperlyConfigured as exc:
        pytest.fail(
            f"Case {_case_id(dropped)!r} generates a module list that is not a "
            f"valid configuration, so booting it would test "
            f"validate_module_names() rather than droppability.\n"
            f"OPENH2O_MODULES={','.join(kept)}\n{exc}"
        )


class TestDropClosure:
    """The closure logic itself, against registries this repo does not have yet.

    Unit-testable because ``drop_closure`` takes its registry as an argument.
    Phase 87 is the first phase where the real registry produces a closure
    bigger than one module, and waiting until then to find out whether the
    computation is right would be finding out at the worst possible moment.
    """

    @staticmethod
    def _registry(**requires_by_name):
        return {
            name: ModuleSpec(
                name=name, label=name.title(), apps=(name,), requires=tuple(requires)
            )
            for name, requires in requires_by_name.items()
        }

    def test_a_module_nothing_depends_on_closes_over_itself(self):
        registry = self._registry(a=(), b=())
        assert drop_closure("a", registry, ("a", "b")) == {"a"}

    def test_an_optional_dependent_is_dragged_out(self):
        """The Phase 87 shape: optional A requires optional B, so B takes A."""
        registry = self._registry(a=("b",), b=())
        assert drop_closure("b", registry, ("a", "b")) == {"a", "b"}
        # ...and not the other way round. Dropping the dependency's dependent
        # says nothing about the dependency.
        assert drop_closure("a", registry, ("a", "b")) == {"a"}

    def test_the_closure_is_transitive(self):
        registry = self._registry(a=("b",), b=("c",), c=())
        assert drop_closure("c", registry, ("a", "b", "c")) == {"a", "b", "c"}

    def test_required_modules_are_never_dragged_out(self):
        """`d` depends on `b` but is not in the optional set, so it stays."""
        registry = self._registry(b=(), d=("b",))
        assert drop_closure("b", registry, ("b",)) == {"b"}

    def test_a_requires_cycle_terminates(self):
        """`measurements` and `standards` genuinely require each other."""
        registry = self._registry(a=("b",), b=("a",), c=())
        assert drop_closure("a", registry, ("a", "b", "c")) == {"a", "b"}

    def test_todays_registry_closes_over_single_modules(self):
        """The closure list, stated as a fact rather than a hope.

        Phase 86 wrote this to go red on exactly one event, and Phase 87 is that
        event: `recharge` declares `requires=(..., "surface")`, so the moment
        `surface` became optional, dropping it validly took `recharge` with it —
        and the harness generated the `without-surface+recharge` case with no
        edit to any file under `tests/droppability/`. Confirmed 2026-07-21, not
        merely re-baselined.

        Every other optional module still closes over itself alone.
        """
        multi = {
            name: sorted(drop_closure(name))
            for name in OPTIONAL_MODULE_NAMES
            if drop_closure(name) != {name}
        }
        assert multi == {"surface": ["recharge", "surface"]}, (
            f"The set of cases that drop more than the module they name has "
            f"changed: {multi}. That is correct behaviour if a phase just made "
            f"one optional module depend on another — confirm the new case list "
            f"is what you intended, then update this pin."
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
