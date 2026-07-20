# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module registry: which domains a deployment runs, and what each one contributes.

A "flavor" of OpenH2O — a district that carries drinking water but not recharge,
say — used to be expressible only by editing code, which forks that district's
install and breaks ``git pull``. This module makes the flavor a *setting*: the
``OPENH2O_MODULES`` list names the enabled modules, and ``INSTALLED_APPS``, the
URL map, and the sidebar are all composed from the registry below.

**This file is imported from ``config/settings/base.py``.** It therefore must not
import Django models, apps, or anything that touches the app registry — doing so
deadlocks app loading. Only ``dataclasses``, ``typing``, and
``django.core.exceptions`` are safe here, and ``import core.modules`` must
succeed with ``DJANGO_SETTINGS_MODULE`` unset.

Three orderings are encoded, and they are genuinely different from one another:

* **App order** — the order of ``MODULE_REGISTRY`` itself, which becomes the
  local tail of ``INSTALLED_APPS``. Load-bearing: first app wins for duplicate
  template and static-file paths.
* **URL order** — ``ModuleSpec.url_order``. Load-bearing in principle (first
  matching pattern wins), though today's 13 prefixes are disjoint.
* **Nav order** — ``NavEntry.order``, scoped within a section. Purely
  presentational, but it is what the sidebar reads top to bottom.

Order values are spaced by 10 so a later module can be inserted without
renumbering its neighbours.

**Not every module is droppable yet, and the registry says so out loud.** Two
different reasons put a module in the ``required`` set:

* *Structural* — ``core`` owns ``AUTH_USER_MODEL``; ``geography`` owns the
  boundary/zone spine; ``measurements`` and ``standards`` are vocabulary tables
  other modules FK into. These are required by design.
* *Not yet decoupled* — ``parcels``, ``wells``, ``accounting``, ``surface``,
  ``recharge`` and ``datasync`` are imported at module scope by roughly a
  hundred call sites in apps that stay enabled (``config/views.py``,
  ``geography/views.py``, ``reporting/generators.py``, the seed commands, and
  the accounting/surface calculation services). Omitting one does remove it from
  ``INSTALLED_APPS``, and then the very next model import raises. They are
  marked required so that misconfiguration fails at startup with an explanation
  instead of an opaque ``app_label`` RuntimeError. Making them genuinely
  optional is a decoupling job, tracked separately and deliberately out of scope
  for v2.1.

Everything else — ``reporting``, ``health``, ``setup``, ``infrastructure``,
``feedback``, and every module added from Phase 78 onward — is droppable today.
"""

from dataclasses import dataclass
from typing import Optional

from django.core.exceptions import ImproperlyConfigured

# -- Nav sections ------------------------------------------------------------
# Display order of the sidebar's section headings. `requires_admin_mode` mirrors
# the template's outer `{% if nav_mode == 'admin' %}` wrapper: the whole
# Administration block is hidden in Operations mode regardless of who is looking.
# An entry's own `visibility` is an ADDITIONAL predicate applied inside its
# section, never a replacement for the section gate.

SECTION_OVERVIEW = "overview"
SECTION_WATER_DATA = "water_data"
SECTION_ADMINISTRATION = "administration"
SECTION_REPORTING = "reporting"
SECTION_HELP = "help"

# Per-entry visibility predicates, mirroring the four the sidebar uses today.
VISIBILITY_ALWAYS = "always"  # no extra predicate
VISIBILITY_ADMIN_MODE = "admin_mode"  # nothing beyond the section gate
VISIBILITY_AGENCY_ADMIN = "agency_admin"  # {% if user_is_admin %}
VISIBILITY_SETUP_GATE = "setup_gate"  # {% if not access_enforced or user_is_admin %}

VALID_VISIBILITIES = frozenset(
    {
        VISIBILITY_ALWAYS,
        VISIBILITY_ADMIN_MODE,
        VISIBILITY_AGENCY_ADMIN,
        VISIBILITY_SETUP_GATE,
    }
)


@dataclass(frozen=True)
class NavSection:
    """A sidebar section heading plus the entries resolved into it."""

    key: str
    label: str
    requires_admin_mode: bool = False
    entries: tuple = ()

    def with_entries(self, entries) -> "NavSection":
        return NavSection(
            key=self.key,
            label=self.label,
            requires_admin_mode=self.requires_admin_mode,
            entries=tuple(entries),
        )


# Ordered. `overview` deliberately carries an empty label — it renders with no
# section heading today.
NAV_SECTIONS: tuple = (
    NavSection(SECTION_OVERVIEW, ""),
    NavSection(SECTION_WATER_DATA, "Water Data"),
    NavSection(SECTION_ADMINISTRATION, "Administration", requires_admin_mode=True),
    NavSection(SECTION_REPORTING, "Reporting"),
    NavSection(SECTION_HELP, "Help"),
)

VALID_SECTIONS = frozenset(s.key for s in NAV_SECTIONS)


@dataclass(frozen=True)
class NavEntry:
    """One sidebar link contributed by a module.

    `active_match` / `active_excludes` reproduce today's path-substring active
    state. An exclude is needed whenever a section landing page's prefix is also
    a prefix of its own sub-pages: Surface Diversions matches ``/surface/`` but
    must NOT light up on ``/surface/rights``, which is its own entry.

    **`active_excludes` is a tuple, not a single string.** 77-02 had exactly one
    exclusion to express and a lone string covered it. Phase 78's Drinking Water
    entry needs two — ``/drinking/`` is a prefix of both ``/drinking/results/``
    and ``/drinking/sampling-points/`` — and there is no single substring that
    covers both. A one-element tuple is exactly as expressive as the old string,
    so the existing entry's rendered output is unchanged; the golden fixtures
    are what prove that rather than assert it.

    `icon` is a short stable key that `_nav_icon.html` maps to an icon partial.
    """

    url_name: str
    label: str
    icon: str
    section: str
    order: int
    active_match: str
    active_excludes: tuple = ()
    visibility: str = VISIBILITY_ALWAYS

    def is_active(self, path: str) -> bool:
        """Whether this entry should render as the active link for `path`.

        Pure string work on purpose — no request object, no reverse(), nothing
        that would drag Django's app registry into a module imported from
        settings. `core/templatetags/nav.py` is the thin filter that lets a
        template ask this question.
        """
        if self.active_match not in path:
            return False
        return not any(exclude in path for exclude in self.active_excludes)


@dataclass(frozen=True)
class ModuleSpec:
    """One domain a deployment can switch on or off.

    `url_prefix` and `url_module` are both None for model-only apps (today:
    `measurements` and `standards`, which are vocabulary tables other modules FK
    into and own no views).
    """

    name: str
    label: str
    apps: tuple
    url_prefix: Optional[str] = None
    url_module: Optional[str] = None
    url_order: int = 0
    nav: tuple = ()
    #: Template partial paths this module contributes to the overview dashboard,
    #: e.g. ``("drinking/partials/_dashboard_card.html",)``. Empty for every
    #: module today — see `dashboard_cards_for` for why that is the right answer
    #: and not an omission.
    dashboard_cards: tuple = ()
    seed_commands: tuple = ()
    required: bool = False
    #: Why this module cannot be disabled. Surfaced verbatim in the startup
    #: error, so an operator is told the actual reason rather than left to
    #: reverse-engineer it.
    required_reason: str = ""
    requires: tuple = ()


# -- The registry ------------------------------------------------------------
# Ordered by app order. The concatenated `apps` values MUST reproduce today's
# 15-entry local block of INSTALLED_APPS exactly — tests/test_modules.py asserts
# this against a literal.
#
# `seed_commands` records only the six commands that core's `seed_data` umbrella
# actually runs today. `standards` also ships `seed_observed_properties`, but it
# is deliberately NOT listed: it is not part of the umbrella seed, and listing it
# would change behavior the moment a consumer composes `seed_data` from the
# registry. This plan changes no seeding behavior.

MODULE_REGISTRY: dict = {
    "core": ModuleSpec(
        name="core",
        label="Core",
        apps=("core",),
        url_prefix="users/",
        url_module="core.urls",
        url_order=120,
        nav=(
            NavEntry(
                url_name="core:users_list",
                label="Users",
                icon="users",
                section=SECTION_ADMINISTRATION,
                order=60,
                active_match="/users/",
                visibility=VISIBILITY_AGENCY_ADMIN,
            ),
        ),
        seed_commands=("seed_roles",),
        # AUTH_USER_MODEL = 'core.User'. Disabling core is not a configuration,
        # it is a broken install.
        required=True,
        required_reason=(
            "core owns AUTH_USER_MODEL; disabling it is a broken install, not a configuration"
        ),
    ),
    "geography": ModuleSpec(
        name="geography",
        label="Geography",
        apps=("geography",),
        url_prefix="map/",
        url_module="geography.urls",
        url_order=60,
        nav=(
            NavEntry(
                url_name="geography:map",
                label="Map",
                icon="map",
                section=SECTION_OVERVIEW,
                order=30,
                active_match="/map/",
            ),
            NavEntry(
                url_name="geography:zone_list",
                label="Zones",
                icon="zone",
                section=SECTION_ADMINISTRATION,
                order=50,
                active_match="/map/zones",
                visibility=VISIBILITY_ADMIN_MODE,
            ),
        ),
        # Owns the boundary/zone spine every spatial model and the map lean on.
        required=True,
        required_reason=(
            "geography owns the boundary/zone spine the map and every spatial model lean on"
        ),
    ),
    "parcels": ModuleSpec(
        name="parcels",
        label="Use Areas",
        apps=("parcels",),
        url_prefix="parcels/",
        url_module="parcels.urls",
        url_order=20,
        nav=(
            NavEntry(
                url_name="parcels:list",
                label="Use Areas",
                icon="parcel",
                section=SECTION_WATER_DATA,
                order=20,
                active_match="/parcels/",
            ),
        ),
        requires=("geography",),
        required=True,
        required_reason=(
            "not yet decoupled: parcels.models is imported at module scope by accounting, reporting, geography, surface, setup, infrastructure and config views"
        ),
    ),
    "wells": ModuleSpec(
        name="wells",
        label="Wells",
        apps=("wells",),
        url_prefix="wells/",
        url_module="wells.urls",
        url_order=30,
        nav=(
            NavEntry(
                url_name="wells:list",
                label="Wells",
                icon="well",
                section=SECTION_WATER_DATA,
                order=30,
                active_match="/wells/",
            ),
        ),
        seed_commands=("seed_well_types",),
        requires=("geography",),
        required=True,
        required_reason=(
            "not yet decoupled: wells.models is imported at module scope by reporting, geography, infrastructure and config views"
        ),
    ),
    "measurements": ModuleSpec(
        name="measurements",
        label="Measurements",
        apps=("measurements",),
        # Model-only: no views, no nav.
        required=True,
        required_reason=(
            "measurements is a vocabulary table other modules FK into"
        ),
    ),
    "standards": ModuleSpec(
        name="standards",
        label="Standards",
        apps=("standards",),
        # Model-only: the observed-property vocabulary other modules FK into.
        required=True,
        required_reason=(
            "standards is the observed-property vocabulary other modules FK into"
        ),
    ),
    "accounting": ModuleSpec(
        name="accounting",
        label="Accounting",
        apps=("accounting",),
        url_prefix="accounting/",
        url_module="accounting.urls",
        url_order=10,
        nav=(
            NavEntry(
                url_name="accounting:dashboard",
                label="Dashboard",
                icon="grid",
                section=SECTION_OVERVIEW,
                order=20,
                active_match="/accounting/dashboard",
            ),
            NavEntry(
                url_name="accounting:ledger_list",
                label="Use Ledger",
                icon="ledger",
                section=SECTION_WATER_DATA,
                order=10,
                active_match="/accounting/ledger",
            ),
            NavEntry(
                url_name="accounting:accounts_list",
                label="Accounts",
                icon="account",
                section=SECTION_ADMINISTRATION,
                order=20,
                active_match="/accounting/accounts",
                visibility=VISIBILITY_ADMIN_MODE,
            ),
            NavEntry(
                url_name="accounting:periods_list",
                label="Water Years",
                icon="calendar",
                section=SECTION_ADMINISTRATION,
                order=30,
                active_match="/accounting/reporting-periods",
                visibility=VISIBILITY_ADMIN_MODE,
            ),
            NavEntry(
                url_name="accounting:allocations_list",
                label="Allocations",
                icon="allocation",
                section=SECTION_ADMINISTRATION,
                order=40,
                active_match="/accounting/allocations",
                visibility=VISIBILITY_ADMIN_MODE,
            ),
            NavEntry(
                url_name="accounting:methodology_settings",
                label="Methodology",
                icon="methodology",
                section=SECTION_ADMINISTRATION,
                order=70,
                active_match="/accounting/methodology",
                visibility=VISIBILITY_AGENCY_ADMIN,
            ),
            NavEntry(
                url_name="accounting:delivery_settings",
                label="Delivery Settings",
                icon="delivery",
                section=SECTION_ADMINISTRATION,
                order=80,
                active_match="/accounting/delivery-settings",
                visibility=VISIBILITY_AGENCY_ADMIN,
            ),
        ),
        seed_commands=("seed_water_types",),
        requires=("parcels",),
        required=True,
        required_reason=(
            "not yet decoupled: accounting models and services are imported at module scope by reporting, parcels, surface and geography views"
        ),
    ),
    "surface": ModuleSpec(
        name="surface",
        label="Surface Water",
        apps=("surface",),
        url_prefix="surface/",
        url_module="surface.urls",
        url_order=40,
        nav=(
            NavEntry(
                url_name="surface:pod_list",
                label="Surface Diversions",
                icon="diversion",
                section=SECTION_WATER_DATA,
                order=40,
                active_match="/surface/",
                # Must not light up on the Water Rights page, which lives under
                # the same prefix and owns its own entry.
                active_excludes=("/surface/rights",),
            ),
            NavEntry(
                url_name="surface:water_rights_list",
                label="Water Rights",
                icon="water-right",
                section=SECTION_ADMINISTRATION,
                order=10,
                active_match="/surface/rights",
                visibility=VISIBILITY_ADMIN_MODE,
            ),
        ),
        seed_commands=("seed_water_right_types",),
        requires=("parcels",),
        required=True,
        required_reason=(
            "not yet decoupled: surface.models is imported at module scope by accounting, reporting, geography, infrastructure and config views"
        ),
    ),
    "recharge": ModuleSpec(
        name="recharge",
        label="Recharge",
        apps=("recharge",),
        url_prefix="recharge/",
        url_module="recharge.urls",
        url_order=50,
        nav=(
            NavEntry(
                url_name="recharge:list",
                label="Recharge Areas",
                icon="recharge",
                section=SECTION_WATER_DATA,
                order=50,
                active_match="/recharge/",
            ),
        ),
        requires=("parcels",),
        required=True,
        required_reason=(
            "not yet decoupled: recharge models and geometry are imported at module scope by config views, infrastructure views and geography.placement"
        ),
    ),
    "datasync": ModuleSpec(
        name="datasync",
        label="Data Sync",
        apps=("datasync",),
        url_prefix="datasync/",
        url_module="datasync.urls",
        url_order=70,
        nav=(
            NavEntry(
                url_name="datasync:station_list",
                label="Monitoring Stations",
                icon="station",
                section=SECTION_WATER_DATA,
                order=60,
                active_match="/datasync/stations",
            ),
        ),
        seed_commands=("seed_data_sources",),
        requires=("geography",),
        required=True,
        required_reason=(
            "not yet decoupled: datasync models, freshness and adapters are imported at module scope by accounting, health, setup, standards, geography and config views"
        ),
    ),
    "reporting": ModuleSpec(
        name="reporting",
        label="Reporting",
        apps=("reporting",),
        url_prefix="reporting/",
        url_module="reporting.urls",
        url_order=80,
        nav=(
            NavEntry(
                url_name="reporting:report_list",
                label="Reports",
                icon="report",
                section=SECTION_REPORTING,
                order=10,
                active_match="/reporting/",
            ),
        ),
        seed_commands=("seed_report_templates",),
        requires=("accounting",),
    ),
    "health": ModuleSpec(
        name="health",
        label="Site Health",
        apps=("health",),
        url_prefix="health/",
        url_module="health.urls",
        url_order=90,
        nav=(
            NavEntry(
                url_name="health:dashboard",
                label="Site Health",
                icon="health",
                section=SECTION_ADMINISTRATION,
                order=90,
                active_match="/health/",
                visibility=VISIBILITY_ADMIN_MODE,
            ),
        ),
    ),
    "setup": ModuleSpec(
        name="setup",
        label="Setup",
        apps=("setup",),
        url_prefix="setup/",
        url_module="setup.urls",
        url_order=100,
        nav=(
            NavEntry(
                url_name="setup:wizard",
                label="Setup Wizard",
                icon="setup",
                section=SECTION_ADMINISTRATION,
                order=100,
                active_match="/setup/",
                visibility=VISIBILITY_SETUP_GATE,
            ),
        ),
        requires=("geography",),
    ),
    "infrastructure": ModuleSpec(
        name="infrastructure",
        label="Infrastructure",
        apps=("infrastructure",),
        url_prefix="infrastructure/",
        url_module="infrastructure.urls",
        url_order=110,
        # Has views (bulk import) but no sidebar entry today.
    ),
    "feedback": ModuleSpec(
        name="feedback",
        label="Feedback",
        apps=("feedback",),
        url_prefix="feedback/",
        url_module="feedback.urls",
        url_order=130,
        # Widget-driven; reached from the docked bar, not the sidebar.
    ),
    "drinking": ModuleSpec(
        name="drinking",
        label="Drinking Water",
        apps=("drinking",),
        # Registered last in app order deliberately — a new domain must not
        # displace an existing app on a duplicate template or static path.
        url_prefix="drinking/",
        url_module="drinking.urls",
        # 140: the next free value after feedback's 130, spaced by 10.
        url_order=140,
        nav=(
            NavEntry(
                url_name="drinking:overview",
                label="Drinking Water",
                icon="drinking",
                section=SECTION_WATER_DATA,
                order=70,
                active_match="/drinking/",
                # Three excludes, not two: `/drinking/` is a prefix of every
                # sub-page, each of which owns its own entry below. Adding a
                # sub-route without adding its exclusion leaves Overview lit
                # while the operator is somewhere else.
                active_excludes=(
                    "/drinking/sampling-points",
                    "/drinking/results",
                    "/drinking/onboard",
                ),
            ),
            NavEntry(
                url_name="drinking:sampling_points",
                label="Sampling Points",
                icon="sampling-point",
                section=SECTION_WATER_DATA,
                order=80,
                active_match="/drinking/sampling-points",
            ),
            NavEntry(
                url_name="drinking:results",
                label="Sample Results",
                icon="sample-result",
                section=SECTION_WATER_DATA,
                order=90,
                active_match="/drinking/results",
            ),
            NavEntry(
                url_name="drinking:onboard",
                label="Onboard System",
                # Its own icon key, not a reuse: `test_icon_keys_are_unique`
                # holds one glyph to one destination, so a shared icon would
                # make two different nav rows look like the same place.
                icon="onboard",
                section=SECTION_WATER_DATA,
                order=100,
                active_match="/drinking/onboard",
            ),
        ),
        # The first module to ship a dashboard card. It renders only when a
        # WaterSystem exists, so a deployment that carries the module but has
        # not started using it still sees the pre-78 dashboard.
        dashboard_cards=("drinking/partials/_dashboard_card.html",),
        seed_commands=("seed_drinking",),
        requires=("wells", "standards"),
        # The first Phase-78-era module, and droppable by construction: nothing
        # outside `drinking/` imports it at module scope. ISS-072 discipline.
        required=False,
    ),
}

#: Every module name, in app order. The default value of ``OPENH2O_MODULES``.
ALL_MODULE_NAMES: tuple = tuple(MODULE_REGISTRY.keys())

#: Modules that cannot be switched off — some structurally, some because they
#: are not yet decoupled. See the module docstring for the distinction.
REQUIRED_MODULE_NAMES: tuple = tuple(
    name for name, spec in MODULE_REGISTRY.items() if spec.required
)

#: Modules a deployment can genuinely omit today. This is the honest promise of
#: OPENH2O_MODULES, and tests/test_modules.py pins it.
OPTIONAL_MODULE_NAMES: tuple = tuple(
    name for name, spec in MODULE_REGISTRY.items() if not spec.required
)


# -- Validation --------------------------------------------------------------


def validate_module_names(names) -> tuple:
    """Validate a module-name list, returning it normalised to registry order.

    Fails closed, loudly, at import time. A silent fallback here would let a
    single typo quietly drop a whole domain from a production deployment — the
    operator would find out weeks later via a missing nav link, not at startup.
    """
    names = tuple(names)
    valid = ", ".join(ALL_MODULE_NAMES)

    seen = set()
    for name in names:
        if name not in MODULE_REGISTRY:
            raise ImproperlyConfigured(
                f"OPENH2O_MODULES names an unknown module {name!r}. "
                f"Valid modules are: {valid}."
            )
        if name in seen:
            raise ImproperlyConfigured(
                f"OPENH2O_MODULES lists module {name!r} more than once."
            )
        seen.add(name)

    for required in REQUIRED_MODULE_NAMES:
        if required not in seen:
            reason = MODULE_REGISTRY[required].required_reason
            because = f" ({reason})" if reason else ""
            raise ImproperlyConfigured(
                f"OPENH2O_MODULES omits required module {required!r}, which "
                f"cannot be disabled{because}. Modules that CAN be omitted: "
                f"{', '.join(OPTIONAL_MODULE_NAMES)}."
            )

    for name in names:
        for dependency in MODULE_REGISTRY[name].requires:
            if dependency not in seen:
                raise ImproperlyConfigured(
                    f"Module {name!r} requires module {dependency!r}, which is "
                    f"not in OPENH2O_MODULES. Valid modules are: {valid}."
                )

    # Normalise to registry order so callers never depend on the order an
    # operator happened to type into the env var.
    return tuple(n for n in ALL_MODULE_NAMES if n in seen)


# -- Resolvers ---------------------------------------------------------------
# All pure functions over a module list. `names=None` reads the live setting,
# which is correct at runtime but NOT during settings import — base.py passes
# its local list explicitly, because `settings.OPENH2O_MODULES` does not exist
# yet while base.py is still executing.


def _read_setting() -> tuple:
    from django.conf import settings

    return tuple(getattr(settings, "OPENH2O_MODULES", ALL_MODULE_NAMES))


def enabled_module_names(names=None) -> tuple:
    """Validated, registry-ordered module names."""
    return validate_module_names(_read_setting() if names is None else names)


def enabled_modules(names=None) -> tuple:
    """The ``ModuleSpec`` objects for the enabled modules, in registry order."""
    return tuple(MODULE_REGISTRY[n] for n in enabled_module_names(names))


def is_enabled(name: str, names=None) -> bool:
    return name in enabled_module_names(names)


def local_apps_for(modules) -> list:
    """The local tail of ``INSTALLED_APPS``, in app order."""
    apps: list = []
    for spec in modules:
        apps.extend(spec.apps)
    return apps


def url_specs_for(modules) -> list:
    """``(prefix, url_module)`` pairs in today's URL order.

    Model-only modules contribute nothing. A disabled module's routes are simply
    never registered, so its paths 404 for free — no catch-all, no "module
    disabled" page. A route that does not exist should not exist.
    """
    routed = [m for m in modules if m.url_prefix and m.url_module]
    routed.sort(key=lambda m: m.url_order)
    return [(m.url_prefix, m.url_module) for m in routed]


def dashboard_cards_for(modules) -> list:
    """Template partials the enabled modules contribute to the overview dashboard.

    Flat, in registry order, so the dashboard renders them with a plain
    ``{% include %}`` loop and never names a module.

    Empty on a default deployment, and that is the correct answer rather than a
    gap: the overview's existing panels — the supply-vs-use rollup, the account
    table, the zone table — are accounting-domain summaries that belong to
    ``accounting``, not per-module tiles wearing a shared costume. Manufacturing
    a card for every module to make the list look populated would invent UI
    nobody asked for. Phase 78 adds the first genuine one.
    """
    cards: list = []
    for spec in modules:
        cards.extend(spec.dashboard_cards)
    return cards


def nav_sections_for(modules) -> list:
    """Sidebar sections in display order, each carrying its ordered entries.

    Sections with no entries are omitted. Visibility is NOT evaluated here —
    each entry carries its predicate key and the template applies it, which
    keeps this file free of any request or Django-model dependency.
    """
    by_section: dict = {}
    for spec in modules:
        for entry in spec.nav:
            by_section.setdefault(entry.section, []).append(entry)

    sections = []
    for section in NAV_SECTIONS:
        entries = by_section.get(section.key, [])
        if not entries:
            continue
        entries.sort(key=lambda e: (e.order, e.url_name))
        sections.append(section.with_entries(entries))
    return sections
