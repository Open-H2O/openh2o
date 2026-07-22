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

The composition rule
--------------------

OpenH2O only keeps its promise — run the domains you have, leave the rest out —
if the code respects two constraints. Until v2.4 neither was written down
anywhere, which is exactly how eight of them came to be broken by people each
doing something perfectly reasonable:

1. **A module everybody gets may not point at a module they might not have.** A
   module that is standard (``required=True``) or schema-resident may never hold
   a database reference into a truly-optional one. When it does, omitting the
   optional module leaves a dangling foreign key and ``migrate`` dies building
   the migration graph, before a single table is created.
2. **Every real cross-module dependency must be declared in ``requires``.** The
   ``requires`` tuples are what tell an operator — and the droppability harness —
   that dropping X validly takes Y with it. An undeclared edge is a dependency
   nobody can see until it breaks a deployment.

``tests/test_composition_rule.py`` enforces both. It derives the real edge set
from Django's live app registry and the migration graph, never from grep — grep
has already missed a reverse accessor and a multi-line field declaration in this
codebase (Phase 82). That test lives in ``tests/`` rather than here precisely
because it needs the live registry, which this file must never touch.

The nine pre-existing violations are tolerated only as the written, reasoned
records in ``SCHEMA_EXCEPTIONS`` below. The tripwire fails on a tenth — and
equally on an exception record that has outlived the code it excused, so the
allowlist can never quietly become fiction.

Two independent axes
--------------------

A module's ``required`` flag and its ``schema_resident`` flag answer different
questions, and a module can be either, both, or neither:

* ``required`` — can an operator leave this out of ``OPENH2O_MODULES`` at all?
* ``schema_resident`` — when it IS left out, do its tables still exist?

``schema_resident=True`` means "when disabled, stay installed model-only": the
app remains in ``INSTALLED_APPS``, its migrations run and its tables sit empty,
but it contributes no URLs, no nav, no seed commands and no pages. Everything an
operator can see is gone; only the schema stays. This is the class
``measurements`` and ``standards`` have always belonged to informally, now said
out loud — and since Phase 88 it is a live mechanism rather than a dormant one:
``wells`` and ``datasync`` were the first modules that are optional AND
schema-resident at the same time, which is the combination the tier was built
for. Phase 89 added ``parcels`` and ``accounting``, which makes four. True
removal (tables gone too) stays available per section as a priced option; see
ISSUES.md.

The standard set today: ``core`` and ``geography``, plus the invisible
vocabularies ``measurements`` and ``standards``. **Every water domain is now a
choice** — Phase 89 (2026-07-21) demoted the last two, ``parcels`` and
``accounting``, which is the milestone's whole point. They are demoted as an
inseparable PAIR: ``accounting.requires`` has always named ``parcels``, and
Phase 89 added ``accounting`` to ``parcels.requires``, so turning either off
turns both off and the one-sided configuration is refused at boot. Brent's call,
on measured evidence — ``parcels/views.py`` builds the Use Areas detail page out
of Accounting, so the unpaired shape would ship a page with its content removed.

They stay schema-resident rather than being removed because the arrows point the
wrong way: ``geography.ParcelZone.parcel`` reaches into ``parcels`` from a module
everybody gets, and two ``ParcelLedger`` columns reach into ``accounting``. All
three are ``SCHEMA_EXCEPTIONS`` records that price what turning them around would
cost.

**Switching this pair off takes five more sections with it** —  ``wells``,
``datasync``, ``surface``, ``recharge`` and ``reporting`` each declare that they
need one of the two. What is left is a login, a map and Drinking Water, and that
is not a broken install: it is the drinking-water utility flavor this milestone
existed to make possible.

**"Not yet decoupled" was the wrong diagnosis, and Phase 88 measured it.** Six
modules carried a ``required_reason`` blaming module-scope imports. Demoted
model-only, the app stays in ``INSTALLED_APPS`` and every one of those imports
keeps resolving — ``manage.py check`` is clean with ``wells`` and ``datasync``
switched off (Phase 88), and equally clean with the whole seven-module
``parcels``/``accounting`` closure switched off (Phase 89), in both cases with
ZERO imports moved. The last of those six ``required_reason`` strings was deleted
by Phase 89. What breaks under demotion is what the operator can SEE: routes,
nav, seeds, counts and words. A clean ``manage.py check`` proves nothing here;
``make test-droppable`` is the only thing that looks.

Droppable today — all ten of them: ``reporting``, ``health``, ``setup``,
``infrastructure``, ``feedback``, ``drinking`` — ``recharge``, which Phase 82
(2026-07-20) decoupled as the pilot — ``surface``, removed outright by Phase 87
— ``wells`` and ``datasync``, demoted model-only by Phase 88 — and ``parcels``
and ``accounting``, demoted as a pair by Phase 89. The four demoted ones are the
distinction the two-tier semantic exists for: switched off but schema-resident,
because nine backwards arrows point into them.

**Keep these paragraphs current.** A stale docstring here does not throw; it just
gets believed. The predecessor of this text drifted exactly that way, still
routing work to phases that had been retired.
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
    #: Stay installed model-only when disabled. A schema-resident module that is
    #: NOT in ``OPENH2O_MODULES`` keeps its apps in ``INSTALLED_APPS`` — its
    #: migrations run and its tables exist and sit empty — while contributing no
    #: URLs, no nav entries, no seed commands and no pages. Everything the
    #: operator can see is gone; only the schema stays.
    #:
    #: **Independent of ``required``.** ``measurements`` and ``standards`` are
    #: both: standard (nobody may omit them) AND schema-resident, so the flag
    #: does no work on either. It starts doing work when a module is optional
    #: and schema-resident at the same time — which since Phase 88 (2026-07-21)
    #: ``wells`` and ``datasync`` are. The composition path below is live, and
    #: ``make test-droppable`` exercises it in the ``without-wells`` and
    #: ``without-datasync`` cases.
    schema_resident: bool = False


@dataclass(frozen=True)
class SchemaException:
    """One tolerated violation of rule 1, with its reasoning and its price.

    A record here says: *this* module holds *this* database reference into a
    module that is supposed to be optional, we know, here is why we are living
    with it, and here is what turning the arrow around would actually cost.

    It is not a comment. ``tests/test_composition_rule.py`` matches every record
    against the live relation graph, so a record that stops describing real code
    fails the build rather than sitting there as folklore — and an arrow with no
    record fails it too.
    """

    #: Registry module that holds the reference.
    holder: str
    #: Model class name inside that module.
    model: str
    #: Field name on that model.
    field: str
    #: Registry module the reference points at.
    target: str
    #: ``app/models.py:LINE`` of the field declaration. Verified against the live
    #: tree by the tripwire, so it cannot rot into a wrong number quietly.
    where: str
    #: Why this is tolerated, in product terms.
    why: str
    #: What turning the arrow around would actually take.
    reversing_it: str


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
        # `core` for ParcelLedger.created_by.
        #
        # `accounting` was deliberately absent here until Phase 89 (2026-07-21),
        # and the note that used to sit in this spot said declaring it "would
        # force `accounting` permanently enabled, which is the opposite of what
        # Phase 89 needs." That was true while `parcels` was `required=True`: a
        # requires-edge from a module nobody may omit pins its target on
        # forever. Once `parcels` itself became optional the statement inverted
        # — the edge no longer pins anything, it makes the pair inseparable,
        # which is exactly what Phase 89 needs. `accounting.requires` already
        # named `parcels`; this completes the cycle, so turning either off turns
        # both off and the one-sided configuration is refused at boot.
        #
        # Brent's decision, 2026-07-21, on measured evidence: `parcels/views.py`
        # builds the Use Areas detail page out of Accounting (water balance,
        # recent ledger, resolved reporting period). Shipping `parcels` without
        # `accounting` would ship a page with its content removed.
        #
        # The two ParcelLedger arrows into `accounting` keep their
        # SCHEMA_EXCEPTIONS records. Those document the schema shape; `requires`
        # documents the operator contract. They are different claims about the
        # same code and neither substitutes for the other.
        requires=("core", "geography", "accounting"),
        # DEMOTED model-only in Phase 89 (2026-07-21), not removed — the same
        # call Phase 88 made for `wells` and `datasync`, for the same measured
        # reason. The old `required_reason` blamed module-scope imports; Phase 88
        # measured that diagnosis false and this phase re-confirmed it, because a
        # schema-resident module stays in INSTALLED_APPS and every one of those
        # imports keeps resolving. `manage.py check` is clean with the whole
        # seven-module closure omitted and ZERO imports moved.
        #
        # What actually pinned `parcels` is the other direction, and it is the
        # one arrow that cannot be turned around cheaply:
        # `geography.ParcelZone.parcel` reaches in from a module EVERYBODY gets
        # (SCHEMA_EXCEPTIONS records it, and prices the fix at moving the
        # ParcelZone model itself into `parcels`). Its tables therefore stay in
        # every configuration so that reference cannot dangle; everything the
        # operator can see goes.
        required=False,
        schema_resident=True,
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
        # `parcels` for WellIrrigatedParcel.parcel, `measurements` for
        # WellMeter.meter — both measured, both undeclared before v2.4.
        requires=("geography", "parcels", "measurements"),
        # DEMOTED model-only in Phase 88 (2026-07-21), not removed. The old
        # `required_reason` claimed module-scope imports were the barrier; that
        # was measured and found false — `manage.py check` is clean with `wells`
        # demoted and ZERO imports moved, because a schema-resident module stays
        # in INSTALLED_APPS. What actually pinned it is the other direction:
        # three SCHEMA_EXCEPTIONS records point INTO `wells`
        # (measurements.Sensor.well, measurements.WaterMeasurement.well,
        # standards.Datastream.well), plus drinking.SystemFacility.well added by
        # this phase. Its tables therefore stay in every configuration so those
        # references cannot dangle; everything the operator can see goes.
        required=False,
        schema_resident=True,
    ),
    "measurements": ModuleSpec(
        name="measurements",
        label="Measurements",
        apps=("measurements",),
        # Model-only: no views, no nav.
        # `standards` for the three observed_property FKs, `core` for the two
        # user stamps. The arrows into `wells` and `parcels` are
        # SCHEMA_EXCEPTIONS, not requires — see the module docstring.
        requires=("core", "standards"),
        required=True,
        required_reason=(
            "measurements is a vocabulary table other modules FK into"
        ),
        schema_resident=True,
    ),
    "standards": ModuleSpec(
        name="standards",
        label="Standards",
        apps=("standards",),
        # Model-only: the observed-property vocabulary other modules FK into.
        # `measurements` for Datastream.sensor. That makes standards and
        # measurements mutually requiring, which is honest — they genuinely
        # reference each other, both are standard AND schema-resident, so
        # neither can ever be the one that is missing. Any code walking
        # `requires` transitively must therefore carry a visited set.
        requires=("measurements",),
        required=True,
        required_reason=(
            "standards is the observed-property vocabulary other modules FK into"
        ),
        schema_resident=True,
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
        # `geography` for the two AllocationPlan/AllocationCarryover zone FKs,
        # `core` for ReportingPeriod.finalized_by.
        requires=("core", "geography", "parcels"),
        # DEMOTED model-only in Phase 89 (2026-07-21), inseparably with
        # `parcels` — see that module's `requires` for the cycle and the reason
        # Brent asked for it. The old `required_reason` blamed module-scope
        # imports and was wrong in the same way `parcels`' was.
        #
        # What keeps it schema-resident: two SCHEMA_EXCEPTIONS records point
        # INTO it from `parcels` (ParcelLedger.water_type and
        # ParcelLedger.reporting_period), and `parcels` is itself schema-resident
        # — so its tables exist in every configuration and those columns would
        # dangle if `accounting`'s did not.
        required=False,
        schema_resident=True,
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
        # `accounting` for the two reporting_period FKs, `geography` for
        # PointOfDiversion.source_flowline.
        requires=("geography", "parcels", "accounting"),
        # Decoupled in Phase 87 (2026-07-21). Every cross-app `surface.models`
        # import now runs at function scope, the kept templates that reach into
        # it are guarded, `seed_water_right_types` is module-gated, and
        # `make test-droppable` covers it. `surface` is TRULY removable — no
        # SCHEMA_EXCEPTIONS record targets it — so `schema_resident` stays at its
        # default False and its tables actually go, rather than merely hiding.
        # Dropping it validly drags `recharge` out too; see `recharge.requires`.
        required=False,
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
        # `surface` for RechargeSitePOD.point_of_diversion, `accounting` for
        # RechargeEvent.water_type, `geography` for RechargeSite.zone. The
        # `surface` entry is the load-bearing one: it is what makes dropping
        # `surface` validly drag `recharge` out with it once Phase 87 flips
        # surface optional, and the droppability harness computes that closure
        # from exactly this tuple.
        requires=("geography", "parcels", "accounting", "surface"),
        # Decoupled in Phase 82 (2026-07-20). Every cross-app `recharge.models`
        # import now runs at function scope, the templates that reach into it are
        # guarded, and `make test-droppable` covers it.
        required=False,
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
        # `parcels` for OpenETCache.parcel.
        requires=("geography", "parcels"),
        # DEMOTED model-only in Phase 88 (2026-07-21), same shape as `wells`
        # above. The retired `required_reason` blamed module-scope imports;
        # demotion keeps the app installed, so those imports never break. The
        # real pin is `standards.Datastream.monitored_station`, a
        # SCHEMA_EXCEPTIONS record pointing into it from a module every
        # deployment carries — so the tables stay and the routes, nav, seeds and
        # pages go.
        required=False,
        schema_resident=True,
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
        # `core` for ReportSubmission.certified_by, `geography` for
        # ReportingProfile.boundary.
        requires=("core", "geography", "accounting"),
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
        # `core` for Feedback.user.
        requires=("core",),
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
        # `wells` came OUT in Phase 88 (2026-07-21), on Brent's locked decision
        # 3: no agency type is assumed in either direction. A district can buy
        # every drop wholesale and still have a drinking-water system to track,
        # so the module must not force a groundwater section on. The one thing
        # that stood in the way — `drinking.SystemFacility.well` and its
        # matching migration dependency — is now the ninth SCHEMA_EXCEPTIONS
        # record instead, which is legal because `wells` became schema-resident
        # in the same phase and therefore keeps its tables in every valid
        # configuration.
        #
        # This is also what stops `drop_closure('wells')` returning
        # `{wells, drinking}`: while the edge was declared here, demoting Wells
        # would have dragged Drinking Water out with it.
        requires=("standards",),
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

#: Modules whose tables exist whether or not the module is switched on.
SCHEMA_RESIDENT_MODULE_NAMES: tuple = tuple(
    name for name, spec in MODULE_REGISTRY.items() if spec.schema_resident
)

#: Modules whose schema is present in EVERY valid configuration — either because
#: nobody may omit them, or because omitting them leaves the tables behind. A
#: reference into one of these can never dangle, which is what makes it a legal
#: target for a ``SchemaException``.
SCHEMA_PRESENT_MODULE_NAMES: tuple = tuple(
    name
    for name, spec in MODULE_REGISTRY.items()
    if spec.required or spec.schema_resident
)


# -- The tolerated backwards arrows ------------------------------------------
# Nine relationships run the wrong way: a module a deployment always gets holds
# a database reference into a module that is meant to be optional. Every one was
# added by someone doing something reasonable, with no rule to stop them — which
# is the whole reason rule 1 in the module docstring now exists.
#
# They are not being turned around. Each record says why, and prices the
# reversal so a future decision is made on numbers rather than vibes. The
# mechanism that makes them survivable is schema-residency: the target keeps its
# tables in every configuration, so the reference cannot dangle. That is why the
# tripwire refuses an exception whose target is truly removable — such a record
# would be a contradiction wearing an excuse.
#
# `where` was re-verified against the live tree on 2026-07-21. The line numbers
# in 83-DISCOVERY's table point one line further down (at the quoted target
# rather than the field name); these point at the field declaration itself.

SCHEMA_EXCEPTIONS: tuple = (
    SchemaException(
        holder="measurements",
        model="Sensor",
        field="well",
        target="wells",
        where="measurements/models.py:109",
        why=(
            "A sensor is physically installed in a well. Recording which one on "
            "the sensor is the natural place for it, and measurements is a "
            "vocabulary every deployment carries."
        ),
        reversing_it=(
            "Move the join to the optional side — a wells.WellSensor link table "
            "instead of measurements.Sensor.well — which costs a schema change "
            "plus a data migration over live staging and production rows."
        ),
    ),
    SchemaException(
        holder="measurements",
        model="WaterMeasurement",
        field="well",
        target="wells",
        where="measurements/models.py:175",
        why=(
            "A water measurement records where it was taken; for groundwater "
            "that is a well. Dropping the link would leave readings that cannot "
            "be attributed to anything."
        ),
        reversing_it=(
            "A wells.WellMeasurement link table plus a data migration over the "
            "largest table in the schema — the same shape as Sensor.well but on "
            "far more rows."
        ),
    ),
    SchemaException(
        holder="measurements",
        model="WaterMeasurement",
        field="parcel",
        target="parcels",
        where="measurements/models.py:172",
        why=(
            "The surface-water counterpart of the arrow above: a measurement "
            "taken on a use area rather than at a well."
        ),
        reversing_it=(
            "A parcels.ParcelMeasurement link table plus a data migration, on "
            "the same table as WaterMeasurement.well — so the two are one job, "
            "not two."
        ),
    ),
    SchemaException(
        holder="standards",
        model="Datastream",
        field="well",
        target="wells",
        where="standards/models.py:143",
        why=(
            "In the SensorThings mapping the platform adopted in v1.3, a "
            "Datastream names the Thing it observes. For a groundwater series "
            "that Thing is a well."
        ),
        reversing_it=(
            "A wells.WellDatastream link table, which also means the "
            "SensorThings serializer has to name the join in two places instead "
            "of following one field."
        ),
    ),
    SchemaException(
        holder="standards",
        model="Datastream",
        field="monitored_station",
        target="datasync",
        where="standards/models.py:151",
        why=(
            "The same Thing slot as the arrow above, for an external or surface "
            "telemetry series instead of a well. One of the two is populated "
            "per Datastream."
        ),
        reversing_it=(
            "A datasync.StationDatastream link table, with the same "
            "double-naming cost in the serializer — and it only makes sense "
            "done together with Datastream.well, not alone."
        ),
    ),
    SchemaException(
        holder="geography",
        model="ParcelZone",
        field="parcel",
        target="parcels",
        where="geography/models.py:106",
        why=(
            "ParcelZone is the use-area-to-zone join, and zoning is geography's "
            "job. geography is standard, so this arrow is what pins parcels "
            "into every deployment."
        ),
        reversing_it=(
            "Move the ParcelZone model itself into parcels — a table rename and "
            "an FK repoint on the spine every allocation calculation reads. "
            "This is the single arrow that pins parcels permanently; "
            "83-DISCOVERY names it as the reason 'any subset of the six' was "
            "never achievable."
        ),
    ),
    SchemaException(
        holder="parcels",
        model="ParcelLedger",
        field="water_type",
        target="accounting",
        where="parcels/models.py:89",
        why=(
            "A ledger row has to say which kind of water it moved, and that "
            "vocabulary belongs to accounting."
        ),
        reversing_it=(
            "Nothing on its own: parcels and accounting are migration-entangled "
            "in BOTH directions (parcels/0001 depends on accounting/0001_initial "
            "while accounting/0002 depends on parcels/0001), so neither arrow "
            "turns without moving models across both apps. The pair can only "
            "ever be demoted or enabled together."
        ),
    ),
    SchemaException(
        holder="drinking",
        model="SystemFacility",
        field="well",
        target="wells",
        where="drinking/models.py:280",
        why=(
            "A drinking-water facility very often IS a well — the same physical "
            "hole in the ground that the extraction ledger meters — so "
            "recording which one on the facility is the natural place for it. "
            "But a district can buy all of its water wholesale and own no wells "
            "at all, and it still has a system to sample and report on. The "
            "arrow has to be tolerated rather than declared, because declaring "
            "it in `requires` would force every drinking-water deployment to "
            "carry a groundwater section it may never use — which is exactly "
            "the assumption v2.4 exists to remove."
        ),
        reversing_it=(
            "A wells.WellFacility link table plus a data migration over the "
            "existing SystemFacility rows, and the drinking overview's supply "
            "table would then have to join through it rather than follow one "
            "field. Same shape as measurements.Sensor.well, on far fewer rows — "
            "but it buys nothing while wells is schema-resident, because the "
            "reference cannot dangle."
        ),
    ),
    SchemaException(
        holder="parcels",
        model="ParcelLedger",
        field="reporting_period",
        target="accounting",
        where="parcels/models.py:94",
        why=(
            "A ledger row falls in a water year, and the water-year calendar "
            "belongs to accounting."
        ),
        reversing_it=(
            "Same entanglement as ParcelLedger.water_type above — the two are "
            "one job, and that job is a paired model move, not an FK edit."
        ),
    ),
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
    """The apps contributed by a given set of specs, in the order given.

    Takes specs rather than names, so it says nothing about schema-residency —
    ``installed_apps_for`` below is what settings actually calls.
    """
    apps: list = []
    for spec in modules:
        apps.extend(spec.apps)
    return apps


def installed_apps_for(names=None) -> list:
    """The local tail of ``INSTALLED_APPS`` for a module list, in app order.

    This is where the two tiers diverge, and it is the ONLY resolver where they
    do. A disabled schema-resident module still contributes its apps — that is
    what "stay installed model-only" means: migrations run, tables exist and sit
    empty. Every other resolver (``url_specs_for``, ``nav_sections_for``,
    ``dashboard_cards_for``, and anything reading ``spec.seed_commands``) is fed
    ``enabled_modules()``, which excludes it, so a disabled schema-resident
    module contributes no routes, no nav, no cards and no seeds.

    Registry order is preserved by iterating the registry rather than the caller's
    list, because app order is load-bearing: the first app wins for duplicate
    template and static-file paths.

    With every module enabled — the default deployment — this returns exactly what
    ``local_apps_for(enabled_modules())`` returns. ``tests/test_modules.py`` pins
    both against the same literal.
    """
    enabled = set(enabled_module_names(names))
    apps: list = []
    for name, spec in MODULE_REGISTRY.items():
        if name in enabled or spec.schema_resident:
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
