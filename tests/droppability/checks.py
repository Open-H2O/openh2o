# SPDX-License-Identifier: AGPL-3.0-or-later
"""The child half of the droppability acceptance harness.

**This file is NOT collected by a normal ``pytest tests/`` run, and that is
deliberate.** ``python_files`` in ``pyproject.toml`` is
``["tests.py", "test_*.py", "*_tests.py"]``; ``checks.py`` matches none of them.
If the default suite collected it, it would run with every module enabled, where
it has nothing to assert — a permanently green no-op wearing the costume of
coverage. ``tests/test_droppability_acceptance.py`` is the parent that hands this
path to a subprocess explicitly, and that subprocess is the only thing that runs
it.

**Why a subprocess at all.** ``OPENH2O_MODULES`` is read from the environment at
settings *import* time and composes ``INSTALLED_APPS``. Django populates its app
registry exactly once, at startup. ``override_settings`` therefore cannot
simulate a dropped module: the apps are already loaded, the URLconf is already
built, and the tables already exist. The only honest way to prove a module can be
dropped is to boot a process that never had it. Do not "simplify" this into an
in-process test — you would be deleting the entire point.

Everything below derives the dropped set at runtime by comparing
``core.modules.ALL_MODULE_NAMES`` against ``settings.OPENH2O_MODULES``. No module
name is hardcoded anywhere in this file. That genericity is the deliverable:
Phases 82-85 flip ``required=False`` in ``core/modules.py`` and inherit this
coverage without editing a line here.
"""

import ast
import importlib.util
from pathlib import Path

import factory
import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import Client
from django.urls import NoReverseMatch, reverse

from core import modules as mod

# ---------------------------------------------------------------------------
# What this process is actually missing
# ---------------------------------------------------------------------------

#: The module names this process booted with, straight from the composed setting.
ENABLED_NAMES = tuple(settings.OPENH2O_MODULES)

#: Everything the registry knows about that this process does NOT have.
DROPPED_NAMES = tuple(n for n in mod.ALL_MODULE_NAMES if n not in ENABLED_NAMES)

#: Pages that must keep rendering no matter what was dropped. Measured, not
#: assumed: every one of these returns 200 with all six optional modules absent.
KEPT_PAGES = (
    "/",
    "/about/",
    "/help/getting-started/",
    "/help/glossary/",
    "/wells/",
    "/parcels/",
    "/recharge/",
    "/surface/",
    "/surface/rights/",
    "/accounting/dashboard/",
)

#: The kept list screens, paired with the factory that puts a row on them. These
#: are the pages that render ``templates/partials/_empty_onboarding.html`` when
#: empty, which is where the interesting guards live.
LIST_PAGES = (
    ("/wells/", "WellFactory"),
    ("/parcels/", "ParcelFactory"),
    ("/recharge/", "RechargeSiteFactory"),
    ("/surface/", "PointOfDiversionFactory"),
    ("/surface/rights/", "WaterRightFactory"),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"dropcheck{n}")
    email = factory.Sequence(lambda n: f"dropcheck{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True
    is_superuser = True


@pytest.fixture
def auth_client():
    """A logged-in superuser with the sidebar in Admin mode.

    Admin mode matters and is easy to get wrong: the Administration section is
    wrapped in ``{% if nav_mode == 'admin' %}``, and ``health`` and ``setup``
    contribute their only nav entries there. Under the default Operations mode
    the whole block is hidden, so the "no link into a dropped module" assertion
    below would pass without ever having rendered the links it is looking for.
    """
    c = Client()
    c.force_login(_UserFactory())
    c.cookies["nav_mode"] = "admin"
    return c


# ---------------------------------------------------------------------------
# Table discovery for modules this process never loaded
# ---------------------------------------------------------------------------


def _call_name(node) -> str:
    """The bare function name of an ``ast.Call``, e.g. ``migrations.CreateModel``."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _literal_kwarg(node, name):
    """A literal keyword argument's value, or None if absent or not a literal."""
    for keyword in node.keywords:
        if keyword.arg == name:
            try:
                return ast.literal_eval(keyword.value)
            except ValueError:
                return None
    return None


def _migration_dir(app_label: str):
    """The app's ``migrations/`` directory, located WITHOUT importing the app."""
    spec = importlib.util.find_spec(app_label)
    if spec is None or not spec.submodule_search_locations:
        return None
    directory = Path(list(spec.submodule_search_locations)[0]) / "migrations"
    return directory if directory.is_dir() else None


def _tables_from_migrations(app_label: str) -> tuple:
    """Table names a dropped app's migrations WOULD have created.

    The obvious approach — ask the app registry for the app's models — is not
    available here by construction: the app is not installed, which is the whole
    point of the run.

    Neither is importing the migration modules, which was the first thing tried
    and does not survive contact with this codebase. Several migrations import
    their own app's ``models`` at module scope (Django writes that import
    whenever a field references a model-level callable), and importing
    ``feedback.models`` while ``feedback`` is not in ``INSTALLED_APPS`` raises
    ``RuntimeError: Model class ... doesn't declare an explicit app_label``. So
    the migrations are read as source and parsed with ``ast`` instead — no
    execution, no imports, no app registry.

    Returns an empty tuple for an app with no migrations directory at all, which
    is how a model-less module (``setup``, ``infrastructure``) announces itself.
    """
    directory = _migration_dir(app_label)
    if directory is None:
        return ()

    tables: dict = {}  # model name (lowercased) -> db_table
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kind = _call_name(node)
            if kind == "CreateModel":
                name = _literal_kwarg(node, "name")
                if not name:
                    continue
                options = _literal_kwarg(node, "options") or {}
                # No model in this codebase sets a custom `db_table` today, but
                # reading it costs one line and keeps this honest the day one
                # does — rather than silently checking the wrong table name.
                tables[name.lower()] = options.get(
                    "db_table", f"{app_label}_{name.lower()}"
                )
            elif kind == "DeleteModel":
                name = _literal_kwarg(node, "name")
                if name:
                    tables.pop(name.lower(), None)
            elif kind == "RenameModel":
                old = _literal_kwarg(node, "old_name")
                new = _literal_kwarg(node, "new_name")
                if old and new and old.lower() in tables:
                    tables.pop(old.lower())
                    tables[new.lower()] = f"{app_label}_{new.lower()}"

    return tuple(sorted(tables.values()))


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_this_run_has_something_to_prove():
    """Fail loudly if nothing was actually dropped.

    Every other test in this file is parametrized over ``DROPPED_NAMES``. If that
    tuple is empty they collect zero cases and the file reports a serene green
    while proving absolutely nothing. This is the assertion that makes the
    difference between a gate and a decoration.
    """
    assert DROPPED_NAMES, (
        "This process booted with every module enabled, so there is nothing to "
        "check. Set OPENH2O_MODULES to a reduced list before running this file — "
        "tests/test_droppability_acceptance.py is what normally does that."
    )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_dropped_module_is_absent_from_the_app_registry(name):
    """The most basic claim: Django never loaded it."""
    spec = mod.MODULE_REGISTRY[name]
    installed = {config.name for config in django_apps.get_app_configs()}
    installed |= {config.label for config in django_apps.get_app_configs()}
    present = [app for app in spec.apps if app in installed]
    assert not present, (
        f"Module {name!r} was dropped from OPENH2O_MODULES but its app(s) "
        f"{present} are still in the app registry."
    )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_dropped_module_registers_no_routes(name):
    """Its nav URL names do not reverse, and its prefix is a 404.

    404 specifically — not 500, and not a redirect to login. A dropped module is
    *absent*, not *protected*. A 302 here would mean the route still exists and
    is merely gated, which is a different and much weaker promise.
    """
    spec = mod.MODULE_REGISTRY[name]

    for entry in spec.nav:
        with pytest.raises(NoReverseMatch):
            reverse(entry.url_name)

    if spec.url_prefix:
        path = "/" + spec.url_prefix
        response = Client().get(path)
        assert response.status_code == 404, (
            f"{path} returned {response.status_code} with {name!r} dropped; a "
            f"module that is not installed should have no route at all."
        )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_dropped_module_owns_no_tables(name):
    """None of its tables exist in the database.

    ``setup`` and ``infrastructure`` own zero models, so for them this assertion
    is vacuous — and a test that cannot fail must say so out loud rather than
    contribute a silent pass to the count.
    """
    spec = mod.MODULE_REGISTRY[name]
    expected = tuple(
        table for app in spec.apps for table in _tables_from_migrations(app)
    )
    if not expected:
        pytest.skip(
            f"{name!r} owns zero models, so there is no table to be absent — "
            f"this assertion is vacuous for this module by construction."
        )

    with connection.cursor() as cursor:
        live = set(connection.introspection.table_names(cursor))

    leaked = sorted(set(expected) & live)
    assert not leaked, (
        f"Module {name!r} was dropped but its tables still exist: {leaked}."
    )


@pytest.mark.parametrize("path", KEPT_PAGES)
def test_kept_page_renders_on_a_fresh_instance(auth_client, path):
    """Zero rows anywhere → ``needs_setup`` is True → the wizard branch renders.

    This is the branch of ``_empty_onboarding.html`` that links to ``setup``.
    """
    response = auth_client.get(path)
    assert response.status_code == 200, (
        f"{path} returned {response.status_code} with {list(DROPPED_NAMES)} dropped."
    )


@pytest.mark.parametrize("path", KEPT_PAGES)
def test_kept_page_renders_on_a_configured_but_empty_instance(auth_client, path):
    """A boundary exists but the lists are still empty.

    ``needs_setup`` flips to False the moment a ``Boundary`` row appears, which
    swings ``_empty_onboarding.html`` to its *other* branch — the one linking to
    ``infrastructure``. A harness that only ever ran against a pristine database
    would exercise exactly one of those two branches and let a broken guard in
    the other sail straight through. That is the specific hole this closes.
    """
    from tests.factories import BoundaryFactory

    BoundaryFactory()
    response = auth_client.get(path)
    assert response.status_code == 200, (
        f"{path} returned {response.status_code} with {list(DROPPED_NAMES)} "
        f"dropped and a configured-but-empty database."
    )


def test_both_empty_state_branches_are_actually_reached(auth_client):
    """Prove the two DB states above render DIFFERENT branches.

    The two tests above only assert 200, and 200 is cheap — if ``needs_setup``
    were somehow pinned False, both would render the same branch and the pair
    would look like coverage while testing one path twice. (That is not a
    hypothetical: ``needs_setup`` is gated on ``can_run_setup``, so a non-admin
    user on a deployment with ``ACCESS_CONTROL_ENFORCED=True`` never sees the
    wizard branch at all. This harness logs in a superuser specifically so the
    branch is reachable.)

    Fetched with the HTMX header so the response is the list partial alone,
    without the page toolbar, which carries its own infrastructure links.
    """
    from tests.factories import BoundaryFactory

    fresh = auth_client.get("/wells/", HTTP_HX_REQUEST="true").content.decode()
    BoundaryFactory()
    configured = auth_client.get("/wells/", HTTP_HX_REQUEST="true").content.decode()

    if "setup" in ENABLED_NAMES:
        assert "/setup/" in fresh, (
            "A pristine database should render the Setup Wizard branch of "
            "_empty_onboarding.html, and it did not — so the 'fresh instance' "
            "state above is not exercising the branch it claims to."
        )
    else:
        assert "/setup/" not in fresh

    if "infrastructure" in ENABLED_NAMES:
        assert "/infrastructure/" in configured, (
            "A configured-but-empty database should render the Add/Import branch "
            "of _empty_onboarding.html, and it did not."
        )
    else:
        assert "/infrastructure/" not in configured


@pytest.mark.parametrize("path,factory_name", LIST_PAGES)
def test_kept_list_page_renders_with_rows(auth_client, path, factory_name):
    """The populated path: the empty-state partial is gone and rows render."""
    from tests import factories

    getattr(factories, factory_name)()
    response = auth_client.get(path)
    assert response.status_code == 200, (
        f"{path} returned {response.status_code} with {list(DROPPED_NAMES)} "
        f"dropped and one {factory_name} row present."
    )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_nav_carries_no_link_into_a_dropped_module(auth_client, name):
    """The rendered sidebar contains no href into a dropped module's prefix.

    A page can return 200 and still be wrong: a guard that hides a link's *label*
    but leaves its ``href`` in the markup gives a 200 and a dead click. This
    reads the actual rendered HTML rather than the registry that produced it.
    """
    spec = mod.MODULE_REGISTRY[name]
    if not spec.url_prefix:
        pytest.skip(f"{name!r} contributes no URL prefix, so there is no href to find.")

    needle = f'href="/{spec.url_prefix}'
    for path in KEPT_PAGES:
        body = auth_client.get(path).content.decode()
        assert needle not in body, (
            f"{path} rendered a link into dropped module {name!r} "
            f"(found {needle!r} in the markup)."
        )
