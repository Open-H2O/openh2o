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
``core.modules.ALL_MODULE_NAMES`` against ``settings.OPENH2O_MODULES``. No
assertion hardcodes a module name. That genericity is the deliverable: Phases
82-85 flip ``required=False`` in ``core/modules.py`` and inherit this coverage
without editing a line of test logic here.

The one place module names do appear is ``_PAGES``/``_LIST_PAGES`` below, which
pair each page with the module that OWNS it. That is data, not logic, and it is
what lets the harness stop demanding a dropped module's own page render 200
(Phase 82). Adding a module to the gate means appending a row, never editing an
assertion.
"""

import ast
import html as html_lib
import importlib.util
import re
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

#: A dropped module falls into exactly one of two classes, and they get DIFFERENT
#: assertion sets — which is the whole reason this split exists.
#:
#: *Truly removed* modules are gone in every sense: no apps in the registry, no
#: tables in the database. *Schema-resident* modules are switched off but still
#: installed model-only — their tables exist and sit empty, deliberately, so the
#: eight relationships that point into them cannot dangle. Everything the
#: operator can SEE is gone either way, and the route/nav assertions below are
#: shared because that half of the promise is identical.
#:
#: Which set a module gets is read off ``spec.schema_resident``, not decided
#: here. Same discipline as ``_PAGES``: declared by the owner, never derived.
DROPPED_ABSENT_NAMES = tuple(
    n for n in DROPPED_NAMES if not mod.MODULE_REGISTRY[n].schema_resident
)

DROPPED_RESIDENT_NAMES = tuple(
    n for n in DROPPED_NAMES if mod.MODULE_REGISTRY[n].schema_resident
)

#: Every page the harness knows about, paired with the module that OWNS it.
#:
#: ``None`` means no module owns the page — it is served by ``config`` or a
#: template with no module behind it, so it must render in *every* configuration.
#: A named owner means the page only exists when that module is installed, so the
#: harness must stop demanding it the moment that module is the one being dropped.
#:
#: **The owner is declared, not derived.** Matching a path against
#: ``spec.url_prefix`` would work today (every prefix in ``core/modules.py`` is
#: currently unique — checked), but it is a rule that holds by luck rather than by
#: construction: it silently mis-attributes the day two modules share a prefix, or
#: the day a module serves a page outside its own prefix. An explicit table costs
#: one line per page and cannot mis-attribute. Phases 83-85 add a page by
#: appending a row here, never by editing test logic below.
_PAGES = (
    ("/", None),
    ("/about/", None),
    ("/help/getting-started/", None),
    ("/help/glossary/", None),
    ("/map/", "geography"),
    ("/wells/", "wells"),
    # Phase 88: `datasync` became droppable, so its own landing page joins the
    # table. Declared, like every other row here.
    ("/datasync/stations/", "datasync"),
    ("/parcels/", "parcels"),
    ("/recharge/", "recharge"),
    ("/surface/", "surface"),
    ("/surface/rights/", "surface"),
    ("/accounting/dashboard/", "accounting"),
)

#: Pages that must keep rendering given what THIS process booted with. Measured,
#: not assumed: every one of these returns 200 with all optional modules absent.
KEPT_PAGES = tuple(
    path for path, owner in _PAGES if owner is None or owner in ENABLED_NAMES
)

#: The kept list screens, paired with the factory that puts a row on them and the
#: module that owns the page. These are the pages that render
#: ``templates/partials/_empty_onboarding.html`` when empty, which is where the
#: interesting guards live. Filtered by owner for the same reason as ``_PAGES`` —
#: and note the factory disappears with its module too (see ``tests/factories.py``),
#: so an unfiltered row here would fail on the lookup, not on the render.
_LIST_PAGES = (
    ("/wells/", "WellFactory", "wells"),
    ("/datasync/stations/", "MonitoredStationFactory", "datasync"),
    ("/parcels/", "ParcelFactory", "parcels"),
    ("/recharge/", "RechargeSiteFactory", "recharge"),
    ("/surface/", "PointOfDiversionFactory", "surface"),
    ("/surface/rights/", "WaterRightFactory", "surface"),
)

LIST_PAGES = tuple(
    (path, factory_name)
    for path, factory_name, owner in _LIST_PAGES
    if owner is None or owner in ENABLED_NAMES
)

#: Pages that render ``templates/partials/_empty_onboarding.html``, paired with
#: their owner. Declared, not derived, for the same reason as ``_PAGES``.
#:
#: ``test_both_empty_state_branches_are_actually_reached`` probes one of these.
#: It used to probe a hardcoded ``/wells/``, which was safe only while ``wells``
#: was ``required=True``: Phase 88 made it droppable and the literal 404'd in
#: exactly the case the assertion exists to cover. The first candidate that
#: survives this configuration is used, so a full deployment still probes
#: ``/wells/`` and the run is unchanged. Note this is NOT ``LIST_PAGES`` — the
#: datasync station list has its own empty state and never includes the shared
#: onboarding partial, so it cannot answer this question.
_ONBOARDING_PAGES = (
    ("/wells/", "wells"),
    ("/parcels/", "parcels"),
    ("/surface/", "surface"),
    ("/recharge/", "recharge"),
)

ONBOARDING_PAGES = tuple(
    path for path, owner in _ONBOARDING_PAGES
    if owner is None or owner in ENABLED_NAMES
)

#: Pages a visitor who is NOT signed in actually reaches, paired with their owner.
#:
#: Every render assertion in this file used ``auth_client`` until Plan 88-01.
#: That left a real hole rather than a theoretical one: ``config/views.py::index``
#: serves ``templates/home.html`` to a signed-in user and
#: ``templates/index.html`` to an anonymous one, so **the public landing page had
#: never been rendered under any drop configuration.** Two different templates
#: live at the same URL and the harness only ever saw one of them.
#:
#: That gap has a name. ``/`` fails for ``wells`` via ``home.html``'s link, but
#: NOT for ``datasync`` — even though ``index.html`` reverses
#: ``datasync:station_list`` with no guard at all. The 88-02 failure list is
#: understated by one page for exactly this reason.
#:
#: **Declared, and deliberately short.** Re-running every ``KEPT_PAGES`` entry
#: anonymously would look like coverage and prove nothing: measured 2026-07-21,
#: every other page 302s to login, and asserting a redirect proves the login
#: wall works rather than that the page is honest. These three are the ones that
#: return 200 without a session.
_ANON_PAGES = (
    ("/", None),
    ("/about/", None),
    # Public by design since Phase 7 — the health dashboard needs no login so an
    # operator can check a sick instance they cannot sign in to.
    ("/health/", "health"),
)

ANON_PAGES = tuple(
    path for path, owner in _ANON_PAGES if owner is None or owner in ENABLED_NAMES
)

#: Words a kept page must not say when the owning module is dropped.
#:
#: This is the class ISS-082 named and nothing in this harness could see. 87-02
#: booted staging without ``surface`` and got zero ``NoReverseMatch``, zero 500s,
#: zero dead links — every assertion in this file green — while the home page
#: said "every well, parcel, and *diversion*" and Getting Started promised
#: *recharge basins*. Status codes and link targets cannot detect a sentence. A
#: dropped module leaks through PROSE, and until this table existed the leak had
#: no gate at all.
#:
#: **Declared per module, exactly like ``_PAGES``. Never derived.** Deriving the
#: vocabulary from ``spec.label`` or the module docstring would be a rule that
#: holds by luck: ``datasync`` is labelled "Data Sync" and its prose noun is
#: "monitoring station", and ``parcels`` is labelled "Use Areas" while its
#: models and half its copy say "parcel". A derived list would miss both. One
#: declared row per module costs a line and cannot mis-attribute.
#:
#: **Rows exist for modules that are not droppable yet**, and that is deliberate
#: — ``test_every_dropped_module_declares_a_vocabulary`` below fails if a module
#: ever becomes optional without one, so 88-02 and Phase 89 cannot flip a flag
#: and silently skip this gate. Until then those rows are dormant: they generate
#: no parameters, because the module is never in ``DROPPED_NAMES``.
#:
#: Keep entries specific. A word this table forbids must be one whose appearance
#: on a page really does mean the copy is claiming a domain the deployment does
#: not have — otherwise the gate cries wolf and someone weakens it, which is
#: worse than not having it.
_FORBIDDEN_VOCABULARY = (
    # Live from 88-02 onward.
    ("wells", ("well", "wells", "groundwater extraction", "GEARS")),
    ("datasync", ("monitoring station", "monitoring stations")),
    # Live today.
    ("surface", ("diversion", "diversions", "CalWATRS", "water right", "water rights")),
    ("recharge", ("recharge", "recharge basin", "recharge basins")),
    ("drinking", ("drinking water", "sampling point", "sampling points")),
    # Owns no user-facing vocabulary of its own: `reporting` is the container for
    # GEARS and CalWATRS, and both of those belong to the domains whose water
    # they report (wells and surface), not to reporting. Forbidding "report"
    # here would fire on every page that mentions reporting periods, which
    # `accounting` owns. An empty tuple is a real answer, not a gap.
    ("reporting", ()),
    ("health", ()),
    ("setup", ()),
    ("infrastructure", ()),
    ("feedback", ()),
    # Standard set — these can never be dropped, so these rows can never run.
    # Present so the completeness test below has an answer for every module.
    ("core", ()),
    ("geography", ()),
    ("measurements", ()),
    ("standards", ()),
    # Phase 89 flips these. The entries are deliberately narrow: `parcels` is
    # labelled "Use Areas" but its copy says both, and `accounting`'s nouns
    # ("allocation", "ledger", "water year") are everywhere in a deployment that
    # HAS accounting. Phase 89 owns widening these, with the same measure-first
    # discipline used here — do not widen them speculatively.
    ("parcels", ("use area", "use areas")),
    ("accounting", ("allocation ceiling", "allocation ceilings")),
)

FORBIDDEN_VOCABULARY = dict(_FORBIDDEN_VOCABULARY)

#: English idioms that contain a forbidden word without meaning it.
#:
#: "as well as" is the one that matters: ``\bwell\b`` matches inside it, so on a
#: wells-less deployment an ordinary sentence would fail a test about water. The
#: current copy contains none of these — measured on 2026-07-21 across every
#: kept page rather than assumed — so this list is prophylactic, and it is
#: deliberately tiny.
#:
#: **This is for English, never for excusing a real leak.** If a page genuinely
#: names a domain the deployment does not have, the fix is the copy, not a new
#: entry here. Anything added to this tuple should be a phrase whose words mean
#: something other than water.
_IDIOMS = (
    "as well as",
    "well-known",
    "well known",
    "may as well",
    "well under way",
    # Phase 88, and these are the first entries added by a measurement rather
    # than by prophylaxis. "Injection Well" and "ASR Well" are two of
    # `recharge.RechargeSite`'s four site TYPES — recharge vocabulary that
    # happens to contain the word "well", not a claim that this deployment runs
    # a groundwater extraction section. A district that recharges through an
    # injection well and buys the rest of its water genuinely has one and
    # genuinely has no Wells module, so the sentence is true and it is the
    # matcher that is wrong.
    #
    # This is NOT the widening the notes above warn against: both phrases are
    # model `choices` labels owned by `recharge`, so they disappear with
    # `recharge` and can never excuse a real `wells` leak. Narrowing them in the
    # model instead would be an AlterField migration on a display label.
    "injection well",
    "asr well",
)

#: Pages that DEFINE water vocabulary rather than describe this deployment.
#:
#: Exactly one page qualifies, and the bar for adding a second is high enough
#: that it should be argued in a plan rather than added in passing. An exemption
#: list is how a gate rots, so this one is deliberately awkward: each row carries
#: its reason, ``test_vocabulary_exemptions_still_describe_real_pages`` fails if
#: a row stops matching a real page, and the reason has to survive being read
#: aloud.
#:
#: The distinction that earns the exemption is whether the page makes a CLAIM
#: about the agency's water. The three defects ISS-082 was opened for all did:
#: "every well, parcel, and diversion on one basin view" says the map shows your
#: diversions; "it populates your recharge basins" says the wizard will import
#: them; a live CalWATRS Generate control invites a filing. The glossary's
#: "Managed Aquifer Recharge — intentionally adding water to an aquifer through
#: spreading basins or injection wells" claims nothing about this agency. It
#: defines an industry term, the way a dictionary does.
#:
#: Whether an operator's glossary SHOULD narrow to the terms their deployment
#: uses is a real product question with a defensible answer either way, and it is
#: not one a harness task gets to decide by accident. Logged as ISS-085.
_VOCABULARY_EXEMPT_PAGES = (
    (
        "/help/glossary/",
        "A dictionary of water-data terms. It defines vocabulary rather than "
        "describing what this deployment manages, so naming a domain here is "
        "not a claim that the agency has it. See ISS-085.",
    ),
)

VOCABULARY_EXEMPT_PAGES = frozenset(path for path, _ in _VOCABULARY_EXEMPT_PAGES)

#: The kept pages this assertion actually reads.
VOCABULARY_CHECKED_PAGES = tuple(
    path for path in KEPT_PAGES if path not in VOCABULARY_EXEMPT_PAGES
)

#: The same, for the anonymous list. Declared here rather than beside
#: ``_ANON_PAGES`` only because the exemption set has to exist first.
ANON_VOCABULARY_PAGES = tuple(
    path for path in ANON_PAGES if path not in VOCABULARY_EXEMPT_PAGES
)

_SCRIPT_OR_STYLE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_HTML_COMMENT = re.compile(r"(?s)<!--.*?-->")
_ANY_TAG = re.compile(r"(?s)<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

#: Attributes whose VALUE is prose a human reads, so they are harvested before
#: the tags are stripped. Stripping tags is right for ``class`` and ``id``; it
#: was wrong for these four, and 88-03 found the gap on staging rather than in
#: this suite: ``_header.html`` carried
#: ``placeholder="Search parcels, wells, accounts…"`` unguarded, so every page of
#: a wells-less deployment invited a search for a record type it does not have,
#: and the gate could not see it. Keep the set to attributes a user actually
#: reads — adding ``class`` or ``data-*`` here is the "cries wolf" failure the
#: vocabulary table's own note warns about.
_PROSE_ATTRIBUTES = re.compile(
    r"""(?is)\b(?:placeholder|title|aria-label|alt)\s*=\s*(?:"([^"]*)"|'([^']*)')"""
)


def visible_text(markup: str) -> str:
    """The words a human actually reads on the page.

    Prose-bearing attribute values are harvested FIRST (see
    ``_PROSE_ATTRIBUTES``), because the tag strip below would otherwise take them
    with the markup. Then four things are removed, each for a measured reason
    rather than a general tidiness instinct:

    * ``<script>`` and ``<style>`` bodies — they are code, and the inline JS on
      these pages contains selector strings that would read as prose.
    * HTML comments — they ship to the browser but nobody reads them, so a
      ``<!-- CalWATRS -->`` marker is a markup problem and not a copy problem.
      (One such comment survives in ``base.html``; see ISS-084. Stripping
      comments is what keeps this assertion about words rather than about it.)
    * All tags, which takes every remaining attribute with them. This is the trap
      the plan called out: ``class="well-card"`` must not fail a test about
      prose. That reasoning holds for markup attributes and only for those — a
      ``placeholder`` is read by a person, so it is prose and is kept.
    * HTML entities are unescaped LAST, after the tags are gone — do it first and
      an escaped ``&lt;`` turns into a ``<`` that the tag regex then eats along
      with the real text after it.

    The tag regex is deliberately simple and would mis-handle a ``>`` inside a
    quoted attribute value. No template in this codebase has one (checked), and a
    real HTML parser here would trade a dependency for a case that does not
    occur.
    """
    body = _SCRIPT_OR_STYLE.sub(" ", markup)
    body = _HTML_COMMENT.sub(" ", body)
    attrs = " ".join(
        double or single for double, single in _PROSE_ATTRIBUTES.findall(body)
    )
    text = _ANY_TAG.sub(" ", body) + " " + attrs
    text = html_lib.unescape(text)
    for idiom in _IDIOMS:
        text = re.sub(re.escape(idiom), " ", text, flags=re.I)
    return _WHITESPACE.sub(" ", text)


def find_forbidden_word(text: str, words):
    """The first forbidden word in ``text``, with ~60 characters around it.

    Returns ``(word, excerpt)`` or ``None``. Word boundaries and
    case-insensitive: "Well" opens a sentence, "wells" is a different string
    from "well", and neither should depend on how the copy was capitalised.
    """
    for word in words:
        match = re.search(rf"\b{re.escape(word)}\b", text, re.I)
        if match:
            start = max(0, match.start() - 30)
            excerpt = text[start:match.end() + 30].strip()
            return word, excerpt
    return None


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


@pytest.fixture
def anon_client():
    """A visitor with no session — the other half of ``config.views.index``.

    Not merely ``auth_client`` without the login. ``index`` branches on
    authentication and serves a DIFFERENT TEMPLATE to each side, so this fixture
    is the only way any assertion in this file reaches ``templates/index.html``.
    No ``nav_mode`` cookie: an anonymous visitor has not set one, and inventing
    it would test a state no real visitor is in.
    """
    return Client()


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


@pytest.mark.parametrize("name", DROPPED_ABSENT_NAMES)
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


@pytest.mark.parametrize("name", DROPPED_ABSENT_NAMES)
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


# ---------------------------------------------------------------------------
# The schema-resident assertion set
# ---------------------------------------------------------------------------
# A schema-resident module that is switched off keeps its schema and loses
# everything else. The route and nav assertions above and below already cover the
# "loses everything else" half for both classes; these three cover the half that
# is the OPPOSITE of the truly-removed set — where that one demands absence, this
# one demands presence-and-emptiness.
#
# Nothing exercises this today. No module is both optional and schema-resident,
# so `DROPPED_RESIDENT_NAMES` is empty in every case the harness currently
# generates, and these tests collect zero parameters. Phase 88 is their first
# real user, when `wells` and `datasync` are demoted model-only.


def test_schema_resident_coverage_is_declared():
    """Say out loud whether this run exercises the schema-resident set.

    An empty ``parametrize`` list collects nothing and reports nothing, which is
    indistinguishable from coverage that ran and passed. A skip is visible in the
    output; silence is not. This is the same reasoning as
    ``test_this_run_has_something_to_prove`` above, applied one level down —
    and note it deliberately does NOT weaken that test, which still requires the
    run to be dropping *something*.
    """
    if not DROPPED_RESIDENT_NAMES:
        pytest.skip(
            "No dropped module is schema-resident in this configuration, so the "
            "schema-resident assertion set is dormant by construction. Phase 88 "
            "is its first user (wells and datasync, demoted model-only)."
        )


@pytest.mark.parametrize("name", DROPPED_RESIDENT_NAMES)
def test_schema_resident_module_keeps_its_app(name):
    """Switched off, still installed. This is the tier's whole mechanism.

    If the app were absent, its tables would never be migrated and the eight
    references pointing into it would dangle — which is precisely the failure
    schema-residency exists to avoid.
    """
    spec = mod.MODULE_REGISTRY[name]
    installed = {config.name for config in django_apps.get_app_configs()}
    installed |= {config.label for config in django_apps.get_app_configs()}
    missing = [app for app in spec.apps if app not in installed]
    assert not missing, (
        f"Module {name!r} is schema-resident, so being left out of "
        f"OPENH2O_MODULES must NOT remove it from INSTALLED_APPS — but "
        f"{missing} are absent from the app registry. Its tables will not exist, "
        f"and every reference into it dangles."
    )


@pytest.mark.parametrize("name", DROPPED_RESIDENT_NAMES)
def test_schema_resident_module_tables_are_present_and_empty(name):
    """Present, because the schema stays. Empty, because the module is off.

    Read off the live app registry rather than parsed out of the migration
    files: the app IS installed here, so the registry is available and is the
    more direct answer. (The truly-removed set has to parse migrations precisely
    because its app is gone.)
    """
    spec = mod.MODULE_REGISTRY[name]
    tables = sorted(
        model._meta.db_table
        for app in spec.apps
        for model in django_apps.get_app_config(app).get_models()
    )
    if not tables:
        pytest.skip(f"{name!r} owns zero models, so there is no table to check.")

    with connection.cursor() as cursor:
        live = set(connection.introspection.table_names(cursor))

        absent = sorted(set(tables) - live)
        assert not absent, (
            f"Module {name!r} is schema-resident but these tables were never "
            f"created: {absent}. A disabled schema-resident module keeps its "
            f"schema — that is the difference between demoting it and removing it."
        )

        populated = []
        for table in tables:
            cursor.execute(f'SELECT EXISTS (SELECT 1 FROM "{table}")')
            if cursor.fetchone()[0]:
                populated.append(table)

    assert not populated, (
        f"Module {name!r} is switched off but these tables have rows in them: "
        f"{populated}. Something is still seeding or writing a disabled module."
    )


@pytest.mark.parametrize("name", DROPPED_RESIDENT_NAMES)
def test_schema_resident_module_contributes_no_seed_commands(name):
    """Its tables exist; nothing fills them.

    ``spec.seed_commands`` is resolved off the ENABLED specs, so a disabled
    module's commands are simply never reached. This asserts the outcome rather
    than trusting the mechanism.
    """
    spec = mod.MODULE_REGISTRY[name]
    enabled_seeds = [
        cmd for enabled in mod.enabled_modules(list(ENABLED_NAMES))
        for cmd in enabled.seed_commands
    ]
    still_running = [cmd for cmd in spec.seed_commands if cmd in enabled_seeds]
    assert not still_running, (
        f"Module {name!r} is switched off but its seed command(s) "
        f"{still_running} are still in the resolved set."
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

    The probe page is the first surviving entry of ``ONBOARDING_PAGES`` rather
    than a hardcoded ``/wells/``. That literal was written while ``wells`` was
    ``required=True`` and could not be the module under test; Phase 88 made it
    droppable, and the hardcoded path then 404'd in exactly the case this
    assertion is supposed to cover. On a full deployment it still resolves to
    ``/wells/``, so this run is unchanged.
    """
    from tests.factories import BoundaryFactory

    if not ONBOARDING_PAGES:
        pytest.skip(
            "No page in this configuration renders _empty_onboarding.html, so "
            "there is no screen to probe for its two branches."
        )
    probe = ONBOARDING_PAGES[0]

    fresh = auth_client.get(probe, HTTP_HX_REQUEST="true").content.decode()
    BoundaryFactory()
    configured = auth_client.get(probe, HTTP_HX_REQUEST="true").content.decode()

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


def test_pod_detail_renders_with_a_row(auth_client):
    """A *detail* page, which no list-page case reaches.

    ``/surface/diversion/<pk>/`` renders
    ``templates/surface/partials/_detail_pane.html``, and that partial reaches
    into other modules — it reverses ``recharge:detail`` for the recharge areas a
    diversion fills. None of the list pages above render it, so a broken guard in
    a detail pane was invisible to this harness until now. It needs a row to have
    a pk at all, which is why it is its own case rather than a ``_PAGES`` row.
    """
    if "surface" not in ENABLED_NAMES:
        pytest.skip("surface is the module that owns this page, and it is dropped.")

    from tests import factories

    pod = factories.PointOfDiversionFactory()
    path = f"/surface/diversion/{pod.pk}/"
    response = auth_client.get(path)
    assert response.status_code == 200, (
        f"{path} returned {response.status_code} with {list(DROPPED_NAMES)} "
        f"dropped and one PointOfDiversion row present."
    )


# ---------------------------------------------------------------------------
# The vocabulary gate (ISS-082)
# ---------------------------------------------------------------------------
# Everything above this line checks structure: does the app load, does the route
# 404, is the href gone. None of it can read. These two tests are the first in
# this harness that look at what a page SAYS.


def test_every_dropped_module_declares_a_vocabulary():
    """A module cannot become optional and skip this gate by omission.

    ``FORBIDDEN_VOCABULARY`` is a lookup, and a missing key would make the
    assertion below silently check nothing for that module — a green run that
    proved less than the run before it. This is the same failure shape
    ``test_this_run_has_something_to_prove`` guards at the file level: an empty
    check that looks exactly like a passing one.
    """
    undeclared = [name for name in DROPPED_NAMES if name not in FORBIDDEN_VOCABULARY]
    assert not undeclared, (
        f"These modules were dropped but declare no forbidden vocabulary: "
        f"{undeclared}. Add a row to _FORBIDDEN_VOCABULARY in this file — an "
        f"empty tuple is a valid answer for a module that owns no user-facing "
        f"nouns, but it has to be written down rather than left out."
    )


def test_vocabulary_exemptions_still_describe_real_pages():
    """An exemption cannot outlive the page it excuses.

    A row naming a path this harness no longer serves would sit here looking
    like a considered decision while excusing nothing — and would go on
    excusing nothing after someone re-added a page at that path for a different
    reason. Same discipline as ``SCHEMA_EXCEPTIONS`` in ``core/modules.py``,
    where a record that stops matching real code fails the build rather than
    becoming folklore.
    """
    known = {path for path, _ in _PAGES}
    stale = sorted(VOCABULARY_EXEMPT_PAGES - known)
    assert not stale, (
        f"These pages are exempted from the vocabulary check but are not in "
        f"_PAGES: {stale}. Remove the exemption or restore the page."
    )


def test_the_vocabulary_check_still_reads_most_pages():
    """Guard against the exemption list quietly swallowing the assertion.

    If exemptions ever outnumbered the pages actually checked, this test would
    still be green while proving nothing — the same shape as
    ``test_this_run_has_something_to_prove``, one level down.
    """
    if not KEPT_PAGES:
        pytest.skip("Nothing is kept in this configuration.")
    assert len(VOCABULARY_CHECKED_PAGES) > len(VOCABULARY_EXEMPT_PAGES), (
        f"Only {len(VOCABULARY_CHECKED_PAGES)} of {len(KEPT_PAGES)} kept pages "
        f"are read by the vocabulary check, against "
        f"{len(VOCABULARY_EXEMPT_PAGES)} exemptions. The gate is being hollowed "
        f"out by its own exception list."
    )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_kept_pages_never_name_a_dropped_module(auth_client, name):
    """No kept page says a word that belongs to a domain this deployment lacks.

    The assertion ISS-082 asks for. A page can return 200, carry no dead link,
    reverse no dropped route — and still tell the operator about water they do
    not have. 87-02 measured exactly that on three pages at once.

    Failures name the page, the word and the surrounding text on purpose. A
    Phase-89 failure should be diagnosable from the pytest output without
    re-running anything, the same discipline ``tests/droppability/README.md``
    documents for the spawner.
    """
    words = FORBIDDEN_VOCABULARY.get(name, ())
    if not words:
        pytest.skip(
            f"{name!r} declares no user-facing vocabulary of its own, so this "
            f"assertion is vacuous for it by construction — see the notes on "
            f"_FORBIDDEN_VOCABULARY."
        )

    for path in VOCABULARY_CHECKED_PAGES:
        text = visible_text(auth_client.get(path).content.decode())
        found = find_forbidden_word(text, words)
        assert found is None, (
            f"{path} still says {found[0]!r} with module {name!r} dropped.\n"
            f"  ...{found[1]}...\n"
            f"That page is describing water this deployment does not have. Fix "
            f"the copy — rewrite it module-neutrally if the sentence survives "
            f"it, or guard the noun on core.modules.is_enabled if it enumerates."
        )


# ---------------------------------------------------------------------------
# The anonymous half (Plan 88-01 Task 5)
# ---------------------------------------------------------------------------
# Everything above renders as a signed-in superuser. `config/views.py::index`
# serves a different template to a visitor with no session, so until now the
# public landing page had never been rendered under any drop configuration at
# all — not "tested weakly", never rendered.


def test_anonymous_coverage_is_declared():
    """Say out loud which pages the anonymous cases cover.

    ``ANON_PAGES`` is filtered by owner, so a configuration that drops enough
    could shrink it. An empty list would collect nothing and report nothing,
    which looks exactly like coverage that ran — the failure shape this file
    guards against in three other places already.
    """
    assert ANON_PAGES, (
        "No page in this configuration is reachable without signing in, so the "
        "anonymous assertion set is dormant. That is almost certainly wrong: "
        "'/' and '/about/' have no owner and should always be here."
    )


@pytest.mark.parametrize("path", ANON_PAGES)
def test_anonymous_page_renders(anon_client, path):
    """200, not a redirect. These pages are public and must stay public.

    A 302 here would mean the page still exists but has quietly grown a login
    wall, which is a different regression from the one this file is about and
    equally worth catching.
    """
    response = anon_client.get(path)
    assert response.status_code == 200, (
        f"{path} returned {response.status_code} to an anonymous visitor with "
        f"{list(DROPPED_NAMES)} dropped."
    )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_anonymous_pages_carry_no_link_into_a_dropped_module(anon_client, name):
    """The gap this task exists to close.

    ``templates/index.html`` reverses ``wells:list``, ``parcels:list`` and
    ``datasync:station_list`` with no guard on any of them. Today all three
    modules are ``required=True``, so none can be dropped and this assertion
    generates no case for them — dormant by construction, exactly like the
    schema-resident set above.

    **88-02 is its first real user, and it will go red there until the guards
    land.** That is the point rather than a problem: without this test the
    demotion's failure list is short by one page, and the missing page is the
    public one.

    Not marked xfail. An xfail needs a case to attach to, and there is no case
    to attach one to until ``wells``/``datasync`` are optional — the parametrize
    list simply does not include them yet.
    """
    spec = mod.MODULE_REGISTRY[name]
    if not spec.url_prefix:
        pytest.skip(f"{name!r} contributes no URL prefix, so there is no href to find.")

    needle = f'href="/{spec.url_prefix}'
    for path in ANON_PAGES:
        body = anon_client.get(path).content.decode()
        assert needle not in body, (
            f"{path}, rendered for an ANONYMOUS visitor, carries a link into "
            f"dropped module {name!r} (found {needle!r}). Note this is a "
            f"different template from the signed-in render of the same URL — "
            f"guarding home.html does not guard index.html."
        )


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_anonymous_pages_never_name_a_dropped_module(anon_client, name):
    """The vocabulary gate, over the pages the public actually sees.

    ``/about/`` is the reason this matters and not a formality: it is a public
    page that enumerates the domains the platform manages, and the signed-in
    vocabulary check reads it only because it happens to also be in ``_PAGES``.
    The anonymous render is a different response object built from a different
    session state, and this is what reads it.
    """
    words = FORBIDDEN_VOCABULARY.get(name, ())
    if not words:
        pytest.skip(
            f"{name!r} declares no user-facing vocabulary of its own — see the "
            f"notes on _FORBIDDEN_VOCABULARY."
        )

    for path in ANON_VOCABULARY_PAGES:
        text = visible_text(anon_client.get(path).content.decode())
        found = find_forbidden_word(text, words)
        assert found is None, (
            f"{path}, rendered for an ANONYMOUS visitor, says {found[0]!r} with "
            f"module {name!r} dropped.\n"
            f"  ...{found[1]}...\n"
            f"This is the public face of the deployment describing water it "
            f"does not have. Note it is a different template from the signed-in "
            f"render of the same URL."
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
