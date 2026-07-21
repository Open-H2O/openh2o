# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan 88-01 — a state filing belongs to the domain whose water it reports.

ISS-082's seeded-reference-data half. A GEARS filing reports groundwater
extraction and a CalWATRS filing reports surface diversions, so neither means
anything in a deployment that does not run the matching module. 87-02 measured
the consequence live: with ``surface`` dropped, ``seed_report_templates`` still
created both CalWATRS rows and ``/reporting/reports/generate/?type=calwatrs``
still returned 200.

Two halves are pinned here and they carry different weight:

* **The zero-behavior-change pin.** On a full deployment the seeded set is still
  exactly the four templates it has always been. Every gate this plan adds is
  ``True`` when every module is enabled; if one is not, this is what says so.
* **The gate actually withholding.** With ``surface`` omitted the CalWATRS pair
  is skipped, the reason is printed, and an already-seeded row is left alone.

The GEARS half is exercised against a *hypothetical* module list rather than a
real one, because ``wells`` is still ``required=True`` today -- Plan 88-02 is
what makes it droppable. ``validate_module_names`` correctly refuses a list that
omits a required module, so the only honest way to test the branch before the
flip is to substitute the enablement predicate itself. That is dormant
machinery being unit tested before its first real user, the same discipline
Phase 86 applied to ``schema_resident``.
"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from core import modules as mod
from reporting import report_types as rt
from reporting.management.commands.seed_report_templates import REPORT_TEMPLATES
from reporting.models import ReportTemplate

#: Every module except the surface-water pair. ``recharge`` has to go too --
#: it declares ``requires=("...", "surface")``, so a list holding recharge
#: without surface is rejected at validation and would fail these tests for a
#: reason that has nothing to do with report templates. 87-01 proved that edge
#: is load-bearing rather than decorative.
WITHOUT_SURFACE = [
    name for name in mod.ALL_MODULE_NAMES if name not in ("surface", "recharge")
]

GEARS_TYPES = ("gears_by_well", "gears_by_et")
CALWATRS_TYPES = ("calwatrs_a1", "calwatrs_a2")


class TestOwnerMapping:
    """The declarative half: one mapping, no second copy to drift from it."""

    def test_every_seeded_template_declares_its_owner(self):
        declared = {row["report_type"]: row["owner"] for row in REPORT_TEMPLATES}
        assert declared == rt.REPORT_TYPE_OWNER, (
            "The seed command's rows and REPORT_TYPE_OWNER disagree. They are "
            "meant to be the same mapping read once, not two lists kept in step "
            "by hand."
        )

    def test_gears_belongs_to_wells_and_calwatrs_to_surface(self):
        for report_type in GEARS_TYPES:
            assert rt.owner_of(report_type) == "wells"
        for report_type in CALWATRS_TYPES:
            assert rt.owner_of(report_type) == "surface"

    def test_families_are_derived_and_agree_with_their_types(self):
        assert rt.REPORT_FAMILY_OWNER == {"gears": "wells", "calwatrs": "surface"}
        # A family whose two types named different owners would silently lose
        # one of them to the dict comprehension. Nothing can produce that today;
        # this is what notices if a fifth report type ever tries.
        for report_type, owner in rt.REPORT_TYPE_OWNER.items():
            family = report_type.split("_", 1)[0]
            assert rt.REPORT_FAMILY_OWNER[family] == owner

    def test_an_unclaimed_report_type_is_never_gated(self):
        """A deployment's own template is not a claim about wells or surface."""
        assert rt.owner_of("custom_district_thing") is None
        assert rt.report_type_is_available("custom_district_thing") is True
        assert rt.report_family_is_available("custom") is True


class TestFullDeploymentIsUnchanged:
    """The pin the milestone constraint actually rests on."""

    def test_nothing_is_withheld_when_every_module_is_enabled(self):
        assert rt.unavailable_report_types() == ()
        for report_type in rt.REPORT_TYPE_OWNER:
            assert rt.report_type_is_available(report_type) is True
        for family in rt.REPORT_FAMILY_OWNER:
            assert rt.report_family_is_available(family) is True

    @pytest.mark.django_db
    def test_the_seeded_set_is_still_exactly_the_four_templates(self):
        out = StringIO()
        call_command("seed_report_templates", stdout=out)

        seeded = set(ReportTemplate.objects.values_list("report_type", flat=True))
        assert seeded == set(GEARS_TYPES) | set(CALWATRS_TYPES)
        assert "Seeded 4 report templates" in out.getvalue()
        assert "skipped" not in out.getvalue()

    @pytest.mark.django_db
    def test_reseeding_a_full_deployment_creates_nothing(self):
        call_command("seed_report_templates", stdout=StringIO())
        out = StringIO()
        call_command("seed_report_templates", stdout=out)
        assert "(0 created, 4 existing)" in out.getvalue()


class TestSurfaceDropped:
    """ISS-082's measured case, now closed.

    ``OPENH2O_MODULES`` is swapped via pytest-django's ``settings`` fixture
    rather than an ``override_settings`` class decorator, which only works on
    ``SimpleTestCase`` subclasses. The resolvers in ``core.modules`` read the
    live setting on every call, so this is enough to change the answer -- what
    it does NOT do is recompose ``INSTALLED_APPS``, which is why proving a
    module can actually be dropped still needs the subprocess harness in
    ``tests/droppability/``.
    """

    @pytest.fixture(autouse=True)
    def _surface_is_off(self, settings):
        settings.OPENH2O_MODULES = WITHOUT_SURFACE

    def test_calwatrs_is_unavailable_and_gears_is_not(self):
        assert set(rt.unavailable_report_types()) == set(CALWATRS_TYPES)
        assert rt.report_family_is_available("calwatrs") is False
        assert rt.report_family_is_available("gears") is True

    @pytest.mark.django_db
    def test_the_calwatrs_pair_is_withheld_with_a_visible_reason(self):
        out = StringIO()
        call_command("seed_report_templates", stdout=out)
        output = out.getvalue()

        seeded = set(ReportTemplate.objects.values_list("report_type", flat=True))
        assert seeded == set(GEARS_TYPES), (
            "A deployment with no surface water was still seeded a surface-water "
            "filing template."
        )
        assert output.count("skipped (module 'surface' not enabled)") == 2
        assert "Seeded 2 report templates" in output

    @pytest.mark.django_db
    def test_an_already_seeded_row_is_skipped_but_never_deleted(self):
        """Switching a module off must not be a data-loss event.

        ``ReportSubmission`` carries an FK to ``ReportTemplate``, so deleting a
        template here would cascade into an agency's filing history. Withholding
        a new row and destroying an existing one are different promises.
        """
        ReportTemplate.objects.create(
            report_type="calwatrs_a1",
            name="CalWATRS — Direct Use",
            description="seeded before the module was switched off",
        )
        call_command("seed_report_templates", stdout=StringIO())
        assert ReportTemplate.objects.filter(report_type="calwatrs_a1").exists()


class TestSeedDataUmbrella:
    """The command has to be gated on its OWN module too, not just its rows.

    Found while executing 88-01 and fixed under deviation rule 1.
    ``seed_report_templates`` is owned by ``reporting``, optional since Phase 77,
    but it sat in ``seed_data``'s ungated list -- so ``make seed`` on a
    deployment that dropped reporting died with ``CommandError: Unknown command:
    'seed_report_templates'``. Measured on main 2026-07-21. Identical in shape to
    the ``surface`` defect Phase 87 fixed one line above it.
    """

    def test_report_templates_is_gated_on_reporting(self):
        from core.management.commands.seed_data import (
            OPTIONAL_SEED_COMMANDS,
            SEED_COMMANDS,
        )

        assert ("reporting", "seed_report_templates") in OPTIONAL_SEED_COMMANDS
        assert "seed_report_templates" not in SEED_COMMANDS

    def test_every_ungated_seed_command_belongs_to_a_module_nobody_can_omit(self):
        """The rule the two fixes above were each a one-off application of.

        A seed command may sit in the ungated list only if its owning module is
        in every valid configuration. Anything else is the same defect waiting
        for the next module to become optional -- which, given 88-02 and Phase
        89, is a thing that is about to keep happening.
        """
        from core.management.commands.seed_data import SEED_COMMANDS

        owner_of_command = {
            command: name
            for name, spec in mod.MODULE_REGISTRY.items()
            for command in spec.seed_commands
        }
        offenders = [
            (command, owner_of_command[command])
            for command in SEED_COMMANDS
            if command in owner_of_command
            and owner_of_command[command] not in mod.REQUIRED_MODULE_NAMES
        ]
        assert not offenders, (
            f"These seed commands run unconditionally but are owned by a module "
            f"a deployment can switch off, so `make seed` dies on a missing "
            f"command: {offenders}. Move them to OPTIONAL_SEED_COMMANDS."
        )


class TestWellsDroppedHypothetically:
    """The GEARS half, dormant until 88-02 flips ``wells`` optional.

    ``wells`` is ``required=True`` today, so ``is_enabled("wells")`` cannot
    return False and no real module list can reach this branch. Substituting the
    predicate is what lets the branch be tested before the flip rather than
    after -- so 88-02 lands a behavior change against a gate that has already
    been proven, instead of shipping both at once.
    """

    @staticmethod
    def _without(*disabled):
        return lambda name, names=None: name not in disabled

    def test_gears_is_withheld_when_wells_is_not_enabled(self):
        with patch.object(rt, "is_enabled", self._without("wells")):
            assert set(rt.unavailable_report_types()) == set(GEARS_TYPES)
            assert rt.report_family_is_available("gears") is False
            assert rt.report_family_is_available("calwatrs") is True

    @pytest.mark.django_db
    def test_the_seed_command_withholds_the_gears_pair(self):
        with patch.object(rt, "is_enabled", self._without("wells")):
            out = StringIO()
            call_command("seed_report_templates", stdout=out)

        seeded = set(ReportTemplate.objects.values_list("report_type", flat=True))
        assert seeded == set(CALWATRS_TYPES)
        assert out.getvalue().count("skipped (module 'wells' not enabled)") == 2

    @pytest.mark.django_db
    def test_a_deployment_with_neither_domain_seeds_nothing(self):
        with patch.object(rt, "is_enabled", self._without("wells", "surface")):
            out = StringIO()
            call_command("seed_report_templates", stdout=out)

        assert not ReportTemplate.objects.exists()
        assert "Seeded 0 report templates" in out.getvalue()
