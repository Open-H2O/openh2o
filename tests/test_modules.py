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

# Today's default URL includes. Same discipline as DEFAULT_LOCAL_APPS above: the
# historical 13 stay unedited as the parity baseline, and 78-02 appends
# `drinking` at url_order 140 — the next free value after feedback's 130.
DEFAULT_URL_SPECS = HISTORICAL_URL_SPECS + [("drinking/", "drinking.urls")]


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
        specs = mod.url_specs_for(mod.enabled_modules())
        assert specs == DEFAULT_URL_SPECS
        # The pre-registry order is still a prefix: drinking was appended, and
        # no existing include was reordered or re-prefixed around it.
        assert specs[: len(HISTORICAL_URL_SPECS)] == HISTORICAL_URL_SPECS

    def test_model_only_modules_contribute_no_urls(self):
        # `drinking` was model-only in 78-01 and is deliberately NOT in this
        # list any more — 78-02 gave it three pages, a URL module and nav.
        for name in ("measurements", "standards"):
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
        assert len(specs) == len(DEFAULT_URL_SPECS) - 1

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

    Six modules are required. Four structurally (core owns AUTH_USER_MODEL,
    geography owns the boundary spine, measurements and standards are FK'd
    vocabularies). Two — `parcels` and `accounting` — because of database
    arrows, not imports: `geography.ParcelZone.parcel` reaches into `parcels`
    from a module everybody gets, and the two are migration-entangled in both
    directions. Phase 89 owns them.

    **The counts in this docstring are prose, and prose is not enforced by the
    assertions below** (Phase 87's warning). Read them as commentary; the two
    tests are the contract.

    The "not yet decoupled" group was six until Phase 82 moved `recharge` out,
    five until Phase 87 removed `surface`, and Phase 88 demoted `wells` and
    `datasync` model-only — leaving two.

    If a later phase decouples one, this test is where the promise changes.
    """

    def test_optional_modules_are_exactly_the_droppable_leaves(self):
        assert mod.OPTIONAL_MODULE_NAMES == (
            # Phase 88 (2026-07-21). DEMOTED, not removed: optional AND
            # schema-resident, so the app stays installed and the tables stay
            # empty. Four SCHEMA_EXCEPTIONS records point into it, which is what
            # makes removal unavailable and residency necessary.
            "wells",
            # Phase 87 (2026-07-21). Sixteen cross-app model imports moved to
            # function scope, five kept templates guarded (plus one reasoned
            # exemption), `seed_water_right_types` module-gated, six test
            # factories guarded, and seven view-side couplings closed. Truly
            # removable, not merely hidden: no SCHEMA_EXCEPTIONS record targets
            # it. Dropping it drags `recharge` out too, via `recharge.requires`.
            "surface",
            # Phase 82 (2026-07-20). The first module to earn its slot here by
            # decoupling rather than by never having been coupled: eight
            # cross-app model imports moved to function scope, five templates
            # and two view-side couplings guarded.
            "recharge",
            # Phase 88 (2026-07-21). Demoted alongside `wells`, pinned by
            # `standards.Datastream.monitored_station`.
            "datasync",
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
            "measurements",
            "standards",
            "accounting",
            # `surface` sat here until Phase 87 removed it; `wells` and
            # `datasync` until Phase 88 demoted them model-only.
        )

    def test_every_required_module_explains_itself(self):
        for name in mod.REQUIRED_MODULE_NAMES:
            assert mod.MODULE_REGISTRY[name].required_reason, name

    def test_dropping_every_optional_module_at_once_validates(self):
        names = [n for n in mod.ALL_MODULE_NAMES if n in mod.REQUIRED_MODULE_NAMES]
        assert mod.validate_module_names(names) == mod.REQUIRED_MODULE_NAMES


@pytest.fixture
def hypothetical_registry(monkeypatch):
    """Hand the pure resolvers a registry containing a synthetic module.

    The schema-resident tier is DORMANT today: no module is both optional and
    schema-resident, because the two that carry the flag (`measurements`,
    `standards`) are also required, and `validate_module_names` rightly refuses
    to omit a required module. So the only honest way to exercise the
    composition path before Phase 88 flips a real flag is to give the functions
    a registry that has such a module in it.

    Rebinding the module globals is enough: every resolver looks
    `MODULE_REGISTRY` and `ALL_MODULE_NAMES` up by name at call time.
    """

    def _install(**spec_kwargs):
        spec = mod.ModuleSpec(**spec_kwargs)
        registry = dict(mod.MODULE_REGISTRY)
        registry[spec.name] = spec
        monkeypatch.setattr(mod, "MODULE_REGISTRY", registry)
        monkeypatch.setattr(mod, "ALL_MODULE_NAMES", tuple(registry))
        return spec

    return _install


GHOST = dict(
    name="ghost",
    label="Ghost",
    apps=("ghost",),
    url_prefix="ghost/",
    url_module="ghost.urls",
    url_order=999,
    nav=(
        mod.NavEntry(
            url_name="ghost:list",
            label="Ghost",
            icon="ghost",
            section=mod.SECTION_WATER_DATA,
            order=999,
            active_match="/ghost/",
        ),
    ),
    seed_commands=("seed_ghost",),
)


class TestSchemaResidentTier:
    """The two-tier semantic: switched off, but still holding its tables.

    A schema-resident module that an operator leaves out of ``OPENH2O_MODULES``
    stays in ``INSTALLED_APPS`` — migrations run, tables exist and sit empty —
    while contributing no URLs, no nav, no seed commands and no pages.

    Nothing in the shipping product takes this path yet. Phase 88 is its first
    real user, when ``wells`` and ``datasync`` become optional AND
    schema-resident. These tests are what make it a working mechanism rather
    than a flag with a docstring.
    """

    def test_todays_schema_resident_set_is_pinned(self):
        # Registry order, not alphabetical: `wells` is declared before
        # `measurements` and `standards`, `datasync` after them.
        assert mod.SCHEMA_RESIDENT_MODULE_NAMES == (
            "wells",
            "measurements",
            "standards",
            "datasync",
        )
        # The two axes are independent and this set now proves it rather than
        # asserting it: `measurements` and `standards` are standard AND
        # schema-resident (nobody may omit them, and their tables would stay
        # either way); `wells` and `datasync` are optional AND schema-resident,
        # which is the combination that makes the tier do work.
        assert [
            name
            for name in mod.SCHEMA_RESIDENT_MODULE_NAMES
            if mod.MODULE_REGISTRY[name].required
        ] == ["measurements", "standards"]

    def test_the_tier_is_live_and_names_who_exercises_it(self):
        """The successor to `test_the_tier_is_dormant_today`, which fired as designed.

        That test asserted no module was both optional and schema-resident, and
        instructed whoever broke it to confirm the droppability harness had
        started running its schema-resident assertion set instead of skipping
        it. Phase 88 broke it, did that checking (88-02 Task 6: the four
        assertions were watched collecting for `wells` and `datasync`, and
        `test_schema_resident_module_tables_are_present_and_empty` was watched
        going red on a deliberately reverted seed gate), and this is its
        replacement.

        It is deliberately NOT deleted. A tier with nothing exercising it is
        indistinguishable from a tier that works, which is the failure shape
        this codebase guards against in four other places — so the assertion
        flips from "nobody" to "exactly these two, by name".
        """
        live = set(mod.OPTIONAL_MODULE_NAMES) & set(mod.SCHEMA_RESIDENT_MODULE_NAMES)
        assert live == {"wells", "datasync"}, (
            f"The optional-and-schema-resident set is {sorted(live)}, not "
            f"['datasync', 'wells']. If a module was added here, confirm "
            f"tests/droppability/checks.py generates a `without-<module>` case "
            f"for it and that the schema-resident assertion set COLLECTS rather "
            f"than skips — an empty parametrize list looks exactly like coverage "
            f"that ran and passed."
        )

    def test_default_installed_apps_are_unchanged_by_the_tier(self):
        """With everything enabled the two resolvers agree, exactly."""
        assert mod.installed_apps_for() == DEFAULT_LOCAL_APPS
        assert mod.installed_apps_for() == mod.local_apps_for(mod.enabled_modules())

    def test_disabled_schema_resident_module_keeps_its_apps(
        self, hypothetical_registry
    ):
        hypothetical_registry(schema_resident=True, **GHOST)
        without = [n for n in mod.ALL_MODULE_NAMES if n != "ghost"]

        apps = mod.installed_apps_for(without)
        assert "ghost" in apps, (
            "A disabled schema-resident module must stay in INSTALLED_APPS — "
            "that is the whole point of the tier: its tables keep existing."
        )
        # Registry order preserved: ghost was registered last, so it lands last.
        assert apps == DEFAULT_LOCAL_APPS + ["ghost"]

    def test_disabled_schema_resident_module_contributes_nothing_visible(
        self, hypothetical_registry
    ):
        hypothetical_registry(schema_resident=True, **GHOST)
        without = [n for n in mod.ALL_MODULE_NAMES if n != "ghost"]
        specs = mod.enabled_modules(without)

        assert "ghost" not in mod.enabled_module_names(without)
        assert mod.is_enabled("ghost", without) is False
        assert ("ghost/", "ghost.urls") not in mod.url_specs_for(specs)
        nav_names = {e.url_name for s in mod.nav_sections_for(specs) for e in s.entries}
        assert "ghost:list" not in nav_names
        # Seed resolution reads spec.seed_commands off the ENABLED specs, which
        # is why a disabled module's commands never run. (`seed_data.py` keeps
        # its own literal order deliberately; this is the registry-side answer.)
        seeds = [cmd for spec in specs for cmd in spec.seed_commands]
        assert "seed_ghost" not in seeds
        assert "ghost/partials/_card.html" not in mod.dashboard_cards_for(specs)

    def test_enabled_schema_resident_module_behaves_like_any_other(
        self, hypothetical_registry
    ):
        """The flag changes nothing while the module is switched ON."""
        hypothetical_registry(schema_resident=True, **GHOST)
        names = list(mod.ALL_MODULE_NAMES)
        specs = mod.enabled_modules(names)

        assert "ghost" in mod.installed_apps_for(names)
        assert ("ghost/", "ghost.urls") in mod.url_specs_for(specs)
        nav_names = {e.url_name for s in mod.nav_sections_for(specs) for e in s.entries}
        assert "ghost:list" in nav_names

    def test_disabled_plain_module_still_loses_its_apps(self, hypothetical_registry):
        """The contrast case, so the test above cannot pass for the wrong reason.

        Without ``schema_resident=True`` the identical module disappears from
        ``INSTALLED_APPS`` entirely — which is what every optional module does
        today.
        """
        hypothetical_registry(schema_resident=False, **GHOST)
        without = [n for n in mod.ALL_MODULE_NAMES if n != "ghost"]
        assert "ghost" not in mod.installed_apps_for(without)

    def test_required_check_is_not_relaxed_for_schema_resident_modules(self):
        """Schema-residency is not a licence to omit a REQUIRED module.

        ``validate_module_names`` was deliberately not relaxed when the tier was
        built (Phase 86): residency says what happens *if* a module is omitted,
        it does not say who may omit one. That is still true — but Phase 88 was
        "the first phase entitled to change that" for a different reason than
        the original wording implied. It did not relax the check; it flipped
        ``required`` on two modules that also carry residency, so the two halves
        of this test now genuinely differ and each one proves something.

        `measurements` and `standards` are required AND resident: omitting
        either is refused. `wells` and `datasync` are optional AND resident:
        omitting either is accepted, and the app stays in INSTALLED_APPS anyway,
        which is the entire mechanism.

        Dependents are dropped alongside, because omitting a module while
        something that ``requires`` it stays would raise for a reason that has
        nothing to do with residency — and that near-miss is what made the
        earlier version of this test pass for `wells` while it should not have.
        """
        for name in mod.SCHEMA_RESIDENT_MODULE_NAMES:
            spec = mod.MODULE_REGISTRY[name]
            # Only OPTIONAL dependents come out. A required dependent cannot be
            # dropped, so removing it would move the failure to a different
            # module and this test would assert the wrong name -- which is what
            # the first draft of this loop did for `standards` (it dragged
            # `measurements` out and got that name back instead).
            dropped = {name}
            changed = True
            while changed:
                changed = False
                for candidate, cspec in mod.MODULE_REGISTRY.items():
                    if candidate in dropped or cspec.required:
                        continue
                    if dropped & set(cspec.requires):
                        dropped.add(candidate)
                        changed = True
            names = [n for n in mod.ALL_MODULE_NAMES if n not in dropped]
            if spec.required:
                with pytest.raises(ImproperlyConfigured) as exc:
                    mod.validate_module_names(names)
                assert name in str(exc.value)
                continue

            assert name not in mod.validate_module_names(names), name
            still_installed = mod.installed_apps_for(names)
            assert all(app in still_installed for app in spec.apps), (
                f"{name!r} is schema-resident, so omitting it must leave "
                f"{list(spec.apps)} in INSTALLED_APPS -- got {still_installed}."
            )


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
        # 23 module-owned links: 19 through Phase 77, the three 78-02 adds to
        # Water Data, and 80-02's onboarding wizard. The sidebar also renders
        # `index`, the nav-mode toggle and six static help/about pages, none of
        # which are module-owned.
        assert len(entries) == 23

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
        """The original compound active-state case.

        Was the ONLY one through Phase 77, which is why `active_exclude` was a
        single string. 78-02's Drinking Water entry needs two exclusions, so the
        field became the tuple `active_excludes`; a one-element tuple says
        exactly what the string said, and the golden fixtures prove the rendered
        sidebar did not move.
        """
        entry = next(
            e
            for e in mod.MODULE_REGISTRY["surface"].nav
            if e.url_name == "surface:pod_list"
        )
        assert entry.active_match == "/surface/"
        assert entry.active_excludes == ("/surface/rights",)
        assert entry.is_active("/surface/") is True
        assert entry.is_active("/surface/rights/") is False

    def test_drinking_water_excludes_all_of_its_sub_pages(self):
        """The case that forced the tuple: one exclusion would not have done.

        `/drinking/` is a prefix of EVERY sub-page, so a partial set of excludes
        fixes some and leaves the rest permanently lit. 80-02 adds the third.
        """
        entry = next(
            e
            for e in mod.MODULE_REGISTRY["drinking"].nav
            if e.url_name == "drinking:overview"
        )
        assert entry.active_match == "/drinking/"
        assert len(entry.active_excludes) == 3
        assert entry.is_active("/drinking/") is True
        assert entry.is_active("/drinking/sampling-points/") is False
        assert entry.is_active("/drinking/results/") is False
        assert entry.is_active("/drinking/onboard/") is False


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
