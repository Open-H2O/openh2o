# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 77 — the module-configuration contract.

The point of these tests is to make "the default configuration behaves exactly
as it did before the registry existed" a regression-tested property rather than
a hope. Phase 78 adds a module to this registry; if that work accidentally
reorders ``INSTALLED_APPS``, drops a URL prefix, or typos a nav ``url_name``,
these tests fail here instead of as a 500 on a live sidebar render.

They also pin the *honest* promise of ``OPENH2O_MODULES``: which modules a
deployment can genuinely omit today, and which fail closed at startup because
they are not yet decoupled.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.urls import NoReverseMatch, reverse

from core import modules as mod

# The local tail of INSTALLED_APPS exactly as it was hand-written before the
# registry existed (HEAD bfa6c04). Order is load-bearing: first app wins for
# duplicate template and static-file paths. Written as a literal on purpose —
# deriving it from the registry would make this test tautological.
HISTORICAL_LOCAL_APPS = [
    "core",
    "geography",
    "parcels",
    "wells",
    "measurements",
    "standards",
    "accounting",
    "surface",
    "recharge",
    "datasync",
    "reporting",
    "health",
    "setup",
    "infrastructure",
    "feedback",
]

# Today's default local tail. The historical list is kept above, unedited, as
# the parity baseline; every module added since is appended here explicitly so
# the diff of a phase that adds a domain shows the addition as one line rather
# than as an edit to the historical record.
#
# Phase 78 appends `drinking` — last in app order, so a new domain cannot
# displace an existing app on a duplicate template or static-file path.
DEFAULT_LOCAL_APPS = HISTORICAL_LOCAL_APPS + ["drinking"]

# The 13 local URL includes, in the prefix order config/urls.py used before the
# registry composed them.
HISTORICAL_URL_SPECS = [
    ("accounting/", "accounting.urls"),
    ("parcels/", "parcels.urls"),
    ("wells/", "wells.urls"),
    ("surface/", "surface.urls"),
    ("recharge/", "recharge.urls"),
    ("map/", "geography.urls"),
    ("datasync/", "datasync.urls"),
    ("reporting/", "reporting.urls"),
    ("health/", "health.urls"),
    ("setup/", "setup.urls"),
    ("infrastructure/", "infrastructure.urls"),
    ("users/", "core.urls"),
    ("feedback/", "feedback.urls"),
]


class TestDefaultParity:
    """The default module list must reproduce the pre-registry behavior."""

    def test_local_apps_match_historical_list(self):
        assert mod.local_apps_for(mod.enabled_modules()) == DEFAULT_LOCAL_APPS
        # The pre-registry list is still a prefix: nothing was reordered.
        assert DEFAULT_LOCAL_APPS[: len(HISTORICAL_LOCAL_APPS)] == HISTORICAL_LOCAL_APPS

    def test_installed_apps_ends_with_historical_local_tail(self, settings):
        tail = settings.INSTALLED_APPS[-len(DEFAULT_LOCAL_APPS) :]
        assert list(tail) == DEFAULT_LOCAL_APPS

    def test_url_specs_match_historical_order(self):
        assert mod.url_specs_for(mod.enabled_modules()) == HISTORICAL_URL_SPECS

    def test_model_only_modules_contribute_no_urls(self):
        for name in ("measurements", "standards", "drinking"):
            spec = mod.MODULE_REGISTRY[name]
            assert spec.url_prefix is None
            assert spec.url_module is None
            assert spec.nav == ()

    def test_every_registered_app_belongs_to_exactly_one_module(self):
        owners = [app for spec in mod.MODULE_REGISTRY.values() for app in spec.apps]
        assert sorted(owners) == sorted(set(owners))


class TestDisabledModule:
    """A module left out of OPENH2O_MODULES contributes nothing.

    Asserted on the resolver output rather than on a live re-import: Django's
    app registry is populated once at startup, so ``INSTALLED_APPS`` cannot be
    meaningfully overridden after the fact. ``reporting`` is used because it is
    genuinely droppable — see TestDroppabilityPromise.
    """

    @property
    def without_reporting(self):
        return [n for n in mod.ALL_MODULE_NAMES if n != "reporting"]

    def test_dropped_module_leaves_installed_apps(self):
        apps = mod.local_apps_for(mod.enabled_modules(self.without_reporting))
        assert "reporting" not in apps
        # Every other app survives, in order.
        assert apps == [a for a in DEFAULT_LOCAL_APPS if a != "reporting"]

    def test_dropped_module_registers_no_urls(self):
        specs = mod.url_specs_for(mod.enabled_modules(self.without_reporting))
        assert ("reporting/", "reporting.urls") not in specs
        assert len(specs) == len(HISTORICAL_URL_SPECS) - 1

    def test_dropped_module_contributes_no_nav(self):
        sections = mod.nav_sections_for(mod.enabled_modules(self.without_reporting))
        names = {e.url_name for s in sections for e in s.entries}
        assert "reporting:report_list" not in names
        # The now-empty Reporting section is omitted rather than left blank.
        assert "reporting" not in {s.key for s in sections}

    def test_is_enabled_reflects_the_list(self):
        assert mod.is_enabled("reporting") is True
        assert mod.is_enabled("reporting", self.without_reporting) is False


class TestValidation:
    """Bad configuration fails closed, loudly, naming the offender.

    A silent fallback would let one typo quietly drop a domain from a production
    deployment, discovered weeks later as a missing nav link.
    """

    def test_unknown_module_raises(self):
        with pytest.raises(ImproperlyConfigured) as exc:
            mod.validate_module_names(list(mod.ALL_MODULE_NAMES) + ["notamodule"])
        assert "notamodule" in str(exc.value)

    def test_omitted_required_module_raises_with_reason(self):
        names = [n for n in mod.ALL_MODULE_NAMES if n != "geography"]
        with pytest.raises(ImproperlyConfigured) as exc:
            mod.validate_module_names(names)
        message = str(exc.value)
        assert "geography" in message
        # The operator is told WHY, not left to reverse-engineer it.
        assert mod.MODULE_REGISTRY["geography"].required_reason in message

    def test_unmet_dependency_raises_naming_both_modules(self):
        # `drinking`-style case: a module whose dependency is absent. Built from
        # a synthetic registry entry so the test does not depend on which
        # optional modules happen to have dependencies today.
        spec = mod.ModuleSpec(
            name="ghost", label="Ghost", apps=("ghost",), requires=("reporting",)
        )
        original = dict(mod.MODULE_REGISTRY)
        mod.MODULE_REGISTRY["ghost"] = spec
        try:
            names = [n for n in mod.ALL_MODULE_NAMES if n != "reporting"] + ["ghost"]
            with pytest.raises(ImproperlyConfigured) as exc:
                mod.validate_module_names(names)
            message = str(exc.value)
            assert "ghost" in message and "reporting" in message
        finally:
            mod.MODULE_REGISTRY.clear()
            mod.MODULE_REGISTRY.update(original)

    def test_duplicate_module_raises(self):
        with pytest.raises(ImproperlyConfigured) as exc:
            mod.validate_module_names(list(mod.ALL_MODULE_NAMES) + ["core"])
        assert "core" in str(exc.value)

    def test_validation_normalises_to_registry_order(self):
        shuffled = list(reversed(mod.ALL_MODULE_NAMES))
        assert mod.validate_module_names(shuffled) == mod.ALL_MODULE_NAMES


class TestDroppabilityPromise:
    """Pin exactly which modules a deployment can omit today.

    Ten modules are required. Four structurally (core owns AUTH_USER_MODEL,
    geography owns the boundary spine, measurements and standards are FK'd
    vocabularies). Six because they are imported at module scope by apps that
    stay enabled, so omitting one removes it from INSTALLED_APPS and the next
    model import raises. Marking them required turns that into a clear startup
    error. Decoupling them is tracked separately and is out of scope for v2.1.

    If a later phase decouples one, this test is where the promise changes.
    """

    def test_optional_modules_are_exactly_the_droppable_leaves(self):
        assert mod.OPTIONAL_MODULE_NAMES == (
            "reporting",
            "health",
            "setup",
            "infrastructure",
            "feedback",
            # Phase 78. Droppable by construction, not by later decoupling:
            # nothing outside `drinking/` imports it at module scope.
            "drinking",
        )

    def test_required_modules_are_pinned(self):
        assert mod.REQUIRED_MODULE_NAMES == (
            "core",
            "geography",
            "parcels",
            "wells",
            "measurements",
            "standards",
            "accounting",
            "surface",
            "recharge",
            "datasync",
        )

    def test_every_required_module_explains_itself(self):
        for name in mod.REQUIRED_MODULE_NAMES:
            assert mod.MODULE_REGISTRY[name].required_reason, name

    def test_dropping_every_optional_module_at_once_validates(self):
        names = [n for n in mod.ALL_MODULE_NAMES if n in mod.REQUIRED_MODULE_NAMES]
        assert mod.validate_module_names(names) == mod.REQUIRED_MODULE_NAMES


class TestNavResolution:
    """Every nav entry must reverse, so a typo fails here not on a live render."""

    def test_every_nav_url_name_reverses(self):
        failures = []
        for spec in mod.enabled_modules():
            for entry in spec.nav:
                try:
                    reverse(entry.url_name)
                except NoReverseMatch:
                    failures.append(f"{spec.name}: {entry.url_name}")
        assert not failures, f"nav entries that do not reverse: {failures}"

    def test_nav_entry_count_matches_todays_sidebar(self):
        entries = [e for s in mod.enabled_modules() for e in s.nav]
        # 19 module-owned links. The sidebar also renders `index`, the nav-mode
        # toggle and six static help/about pages, none of which are module-owned.
        assert len(entries) == 19

    def test_icon_keys_are_unique(self):
        icons = [e.icon for s in mod.enabled_modules() for e in s.nav]
        assert len(icons) == len(set(icons))

    def test_sections_and_visibilities_are_valid(self):
        for spec in mod.enabled_modules():
            for entry in spec.nav:
                assert entry.section in mod.VALID_SECTIONS, entry.url_name
                assert entry.visibility in mod.VALID_VISIBILITIES, entry.url_name

    def test_sections_resolve_in_display_order(self):
        keys = [s.key for s in mod.nav_sections_for(mod.enabled_modules())]
        assert keys == ["overview", "water_data", "administration", "reporting"]

    def test_administration_section_is_admin_mode_gated(self):
        sections = {s.key: s for s in mod.nav_sections_for(mod.enabled_modules())}
        assert sections["administration"].requires_admin_mode is True
        assert sections["water_data"].requires_admin_mode is False

    def test_surface_diversions_excludes_the_water_rights_path(self):
        """The one compound active-state case in the whole sidebar."""
        entry = next(
            e
            for e in mod.MODULE_REGISTRY["surface"].nav
            if e.url_name == "surface:pod_list"
        )
        assert entry.active_match == "/surface/"
        assert entry.active_exclude == "/surface/rights"


class TestContextProcessor:
    def test_modules_processor_exposes_names_and_nav(self, rf):
        from core.context_processors import modules

        ctx = modules(rf.get("/"))
        assert ctx["enabled_modules"] == list(mod.ALL_MODULE_NAMES)
        assert [s.key for s in ctx["nav_sections"]] == [
            "overview",
            "water_data",
            "administration",
            "reporting",
        ]

    def test_processor_is_registered(self, settings):
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        assert "core.context_processors.modules" in processors


@pytest.mark.django_db
def test_makemigrations_check_is_clean():
    """This plan adds no models and must not perturb any."""
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
