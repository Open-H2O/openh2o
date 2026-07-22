# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 78-01 — the drinking water spine's invariants.

Three of these are load-bearing enough to be worth stating plainly.

**A presence/absence result must be unrepresentable as a number.** Total
coliform is reported present or absent; if that can be stored as a
concentration, or as a non-detect, the data silently changes meaning. The rule
is asserted twice — through ``full_clean()`` (forms, admin) and through a raw
``.save()`` that bypasses validation entirely (bulk import), because only the
second proves the database itself refuses.

**Results are evidence.** Deleting an Analyte with results attached must raise,
not cascade lab data out of existence.

**``drinking`` is droppable.** It is the first module that is optional from the
day it lands rather than pending decoupling, so the promise gets a regression
test here as well as in tests/test_modules.py.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from core import modules as mod
from drinking.models import Analyte, RegulatoryLimit, SampleResult, WaterSystem
from tests.factories import (
    AnalyteFactory,
    RegulatoryLimitFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    WellFactory,
)


class TestIdentityUniqueness:
    """The two persistent identifiers, and the one composite key."""

    def test_pwsid_is_unique(self):
        WaterSystemFactory(pwsid="CA1910067")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                WaterSystemFactory(pwsid="CA1910067")

    def test_ps_code_is_unique(self):
        SamplingPointFactory(ps_code="CA1910067_001_001")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SamplingPointFactory(ps_code="CA1910067_001_001")

    def test_facility_id_is_unique_within_a_system(self):
        system = WaterSystemFactory()
        SystemFacilityFactory(system=system, facility_id="001")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SystemFacilityFactory(system=system, facility_id="001")

    def test_the_same_facility_id_may_repeat_across_systems(self):
        """State facility IDs are only unique within their own PWS."""
        SystemFacilityFactory(system=WaterSystemFactory(), facility_id="001")
        SystemFacilityFactory(system=WaterSystemFactory(), facility_id="001")
        assert WaterSystem.objects.count() == 2


class TestResultKindConsistency:
    """A present/absent result must not be storable as a number.

    Each rule is checked at both layers: ``full_clean()`` for the form and
    admin path, and a bare ``.save()`` for the import path that skips
    validation. The second is the one that proves the database holds the line.
    """

    def test_numeric_result_rejects_presence_in_clean(self):
        result = SampleResultFactory.build(
            event=SampleEventFactory(),
            analyte=AnalyteFactory(),
            result_kind="numeric",
            result_value=Decimal("0.005"),
            presence=True,
        )
        with pytest.raises(ValidationError) as exc:
            result.full_clean()
        assert "presence" in exc.value.message_dict

    def test_numeric_result_rejects_presence_in_the_database(self):
        result = SampleResultFactory.build(
            event=SampleEventFactory(),
            analyte=AnalyteFactory(),
            result_kind="numeric",
            result_value=Decimal("0.005"),
            presence=False,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                result.save()

    def test_presence_result_rejects_a_numeric_value_in_clean(self):
        result = SampleResultFactory.build(
            event=SampleEventFactory(),
            analyte=AnalyteFactory(),
            result_kind="presence_absence",
            presence=True,
            result_value=Decimal("1.0"),
        )
        with pytest.raises(ValidationError) as exc:
            result.full_clean()
        assert "result_value" in exc.value.message_dict

    def test_presence_result_rejects_a_numeric_value_in_the_database(self):
        result = SampleResultFactory.build(
            event=SampleEventFactory(),
            analyte=AnalyteFactory(),
            result_kind="presence_absence",
            presence=True,
            result_value=Decimal("1.0"),
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                result.save()

    def test_presence_result_rejects_the_non_detect_flag_in_clean(self):
        """'Absent' is not 'below reporting level' — they are different claims."""
        result = SampleResultFactory.build(
            event=SampleEventFactory(),
            analyte=AnalyteFactory(),
            result_kind="presence_absence",
            presence=False,
            result_value=None,
            less_than_rl=True,
        )
        with pytest.raises(ValidationError) as exc:
            result.full_clean()
        assert "less_than_rl" in exc.value.message_dict

    def test_presence_result_rejects_the_non_detect_flag_in_the_database(self):
        result = SampleResultFactory.build(
            event=SampleEventFactory(),
            analyte=AnalyteFactory(),
            result_kind="presence_absence",
            presence=False,
            result_value=None,
            less_than_rl=True,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                result.save()

    def test_a_well_formed_presence_result_saves(self):
        result = SampleResultFactory(
            result_kind="presence_absence",
            presence=False,
            result_value=None,
            unit="",
            less_than_rl=False,
        )
        result.full_clean()
        assert SampleResult.objects.get(pk=result.pk).presence is False

    def test_a_well_formed_numeric_non_detect_saves(self):
        result = SampleResultFactory(
            result_kind="numeric",
            result_value=Decimal("0.0005"),
            less_than_rl=True,
            reporting_level=Decimal("0.001"),
        )
        result.full_clean()
        assert SampleResult.objects.get(pk=result.pk).less_than_rl is True


class TestResultsAreEvidence:
    def test_deleting_an_analyte_with_results_is_refused(self):
        analyte = AnalyteFactory()
        SampleResultFactory(analyte=analyte)
        with pytest.raises(ProtectedError):
            analyte.delete()

    def test_an_unused_analyte_deletes(self):
        analyte = AnalyteFactory()
        analyte.delete()
        assert not Analyte.objects.filter(pk=analyte.pk).exists()

    def test_deleting_an_event_takes_its_results(self):
        """Results belong to their event; the event is the parent record."""
        result = SampleResultFactory()
        result.event.delete()
        assert not SampleResult.objects.filter(pk=result.pk).exists()


class TestRegulatoryLimitVersioning:
    """Versioning is the point of this table, so overlaps must be refused."""

    def _sibling(self, first, **kwargs):
        limit = RegulatoryLimitFactory.build(
            analyte=first.analyte,
            limit_type=first.limit_type,
            jurisdiction=first.jurisdiction,
            **kwargs,
        )
        return limit

    def test_overlapping_ranges_are_rejected(self):
        first = RegulatoryLimitFactory(
            effective_start=date(2000, 1, 1), effective_end=date(2010, 12, 31)
        )
        overlapping = self._sibling(
            first, effective_start=date(2010, 1, 1), effective_end=date(2015, 12, 31)
        )
        with pytest.raises(ValidationError):
            overlapping.full_clean()

    def test_adjacent_ranges_are_accepted(self):
        first = RegulatoryLimitFactory(
            effective_start=date(2000, 1, 1), effective_end=date(2010, 12, 31)
        )
        adjacent = self._sibling(
            first, effective_start=date(2011, 1, 1), effective_end=None
        )
        adjacent.full_clean()
        adjacent.save()
        assert RegulatoryLimit.objects.filter(analyte=first.analyte).count() == 2

    def test_an_open_ended_limit_blocks_any_later_range(self):
        """`effective_end=None` means still in force, so nothing may follow it."""
        first = RegulatoryLimitFactory(
            effective_start=date(2000, 1, 1), effective_end=None
        )
        later = self._sibling(
            first, effective_start=date(2020, 1, 1), effective_end=None
        )
        with pytest.raises(ValidationError):
            later.full_clean()

    def test_a_different_jurisdiction_may_overlap(self):
        """CA's stricter limit coexists with the federal one, by design."""
        federal = RegulatoryLimitFactory(
            jurisdiction="federal", effective_start=date(2000, 1, 1)
        )
        state = self._sibling(
            federal, effective_start=date(2000, 1, 1), effective_end=None
        )
        state.jurisdiction = "CA"
        state.full_clean()
        state.save()
        assert RegulatoryLimit.objects.filter(analyte=federal.analyte).count() == 2

    def test_a_different_limit_type_may_overlap(self):
        mcl = RegulatoryLimitFactory(
            limit_type="mcl", effective_start=date(2000, 1, 1)
        )
        dlr = self._sibling(mcl, effective_start=date(2000, 1, 1), effective_end=None)
        dlr.limit_type = "dlr"
        dlr.full_clean()
        dlr.save()
        assert RegulatoryLimit.objects.filter(analyte=mcl.analyte).count() == 2

    def test_saving_an_unchanged_limit_does_not_conflict_with_itself(self):
        limit = RegulatoryLimitFactory(effective_start=date(2000, 1, 1))
        limit.full_clean()

    def test_end_before_start_is_rejected(self):
        limit = RegulatoryLimitFactory.build(
            analyte=AnalyteFactory(),
            effective_start=date(2010, 1, 1),
            effective_end=date(2009, 1, 1),
        )
        with pytest.raises(ValidationError) as exc:
            limit.full_clean()
        assert "effective_end" in exc.value.message_dict


class TestQualityQuantityJoin:
    def test_deleting_a_well_keeps_the_facility(self):
        """The sampling history outlives the well record it was drawn from."""
        well = WellFactory()
        facility = SystemFacilityFactory(well=well)
        well.delete()
        facility.refresh_from_db()
        assert facility.well is None


class TestDroppability:
    """ISS-072 discipline: `drinking` must stay omittable by construction."""

    @property
    def without_drinking(self):
        return [n for n in mod.ALL_MODULE_NAMES if n != "drinking"]

    def test_drinking_is_optional(self):
        assert "drinking" in mod.OPTIONAL_MODULE_NAMES
        assert mod.MODULE_REGISTRY["drinking"].required is False

    def test_dropping_drinking_validates(self):
        names = mod.validate_module_names(self.without_drinking)
        assert "drinking" not in names

    def test_dropped_drinking_leaves_installed_apps(self):
        apps = mod.local_apps_for(mod.enabled_modules(self.without_drinking))
        assert "drinking" not in apps

    def test_dropped_drinking_contributes_no_urls_or_nav(self):
        modules = mod.enabled_modules(self.without_drinking)
        assert all("drinking" not in url_module for _, url_module in
                   mod.url_specs_for(modules))
        names = {e.url_name for s in mod.nav_sections_for(modules) for e in s.entries}
        assert not any(n.startswith("drinking:") for n in names)

    def test_no_kept_template_links_into_drinking_unguarded(self):
        """Mirrors tests/test_module_template_guards.py's mechanism.

        That file parametrizes over OPTIONAL_MODULE_NAMES, so `drinking` is
        already covered there. Restated here so this module's own test file
        fails if the registration is ever quietly flipped to required.
        """
        from tests.test_module_template_guards import (
            test_optional_module_links_are_guarded,
        )

        test_optional_module_links_are_guarded("drinking")

    def test_drinking_requires_the_modules_it_fks_into(self):
        """`wells` came out in Phase 88; the FK did not.

        `SystemFacility.well` still points at `wells.Well`. What changed is that
        the edge is now carried by a SCHEMA_EXCEPTIONS record instead of by
        `requires` — legal because `wells` became schema-resident in the same
        phase, so its tables exist in every valid configuration and the
        reference cannot dangle.

        That is not a loosening dressed up as a decision. Declaring the edge in
        `requires` forced every drinking-water deployment to carry a groundwater
        section, and made `drop_closure('wells')` return `{wells, drinking}` —
        so demoting Wells would have dragged Drinking Water out with it. Brent's
        locked decision 3 (2026-07-21) forbids exactly that: no agency type is
        assumed in either direction, and a district that buys all its water
        wholesale still has a system to sample.
        """
        spec = mod.MODULE_REGISTRY["drinking"]
        assert set(spec.requires) == {"standards"}

    def test_the_well_edge_is_carried_by_an_exception_record_instead(self):
        """The other half: dropping it from `requires` did not drop it on the floor.

        Without this, the test above would pass just as happily if someone had
        deleted the FK, or deleted the record, or never written one — three very
        different states that all look like "requires is {'standards'}".
        """
        record = next(
            (
                r for r in mod.SCHEMA_EXCEPTIONS
                if (r.holder, r.model, r.field, r.target)
                == ("drinking", "SystemFacility", "well", "wells")
            ),
            None,
        )
        assert record is not None, (
            "drinking.SystemFacility.well points into `wells` and `drinking` no "
            "longer declares it in `requires`, so a SCHEMA_EXCEPTIONS record is "
            "the only thing holding the arrow. There isn't one."
        )
        assert "wells" in mod.SCHEMA_PRESENT_MODULE_NAMES, (
            "The record above is only legal while `wells` keeps its tables in "
            "every valid configuration."
        )


@pytest.mark.django_db
class TestSeedDrinking:
    def test_seed_creates_analytes_and_limits(self):
        call_command("seed_drinking", verbosity=0)
        assert Analyte.objects.count() >= 20
        assert RegulatoryLimit.objects.count() >= 20

    def test_seed_is_idempotent(self):
        call_command("seed_drinking", verbosity=0)
        analytes = Analyte.objects.count()
        limits = RegulatoryLimit.objects.count()
        call_command("seed_drinking", verbosity=0)
        assert Analyte.objects.count() == analytes
        assert RegulatoryLimit.objects.count() == limits

    def test_lead_and_copper_are_action_levels_not_mcls(self):
        call_command("seed_drinking", verbosity=0)
        for name in ("Lead", "Copper"):
            limits = RegulatoryLimit.objects.filter(analyte__name=name)
            assert [limit.limit_type for limit in limits] == ["action_level"], name

    def test_the_presence_absence_analytes_exist(self):
        """Coliform work needs analyte rows even where EPA sets no number."""
        call_command("seed_drinking", verbosity=0)
        assert Analyte.objects.filter(name="Total Coliforms").exists()
        ecoli = Analyte.objects.get(name="E. coli")
        # No numeric MCL is published for E. coli, so none is invented.
        assert ecoli.limits.count() == 0

    def test_no_seeded_analyte_carries_a_fabricated_ddw_code(self):
        """No published DDW code list is in hand; every code must stay NULL."""
        call_command("seed_drinking", verbosity=0)
        assert not Analyte.objects.exclude(ddw_code=None).exists()

    def test_seed_data_umbrella_includes_drinking_when_enabled(self):
        from core.management.commands.seed_data import OPTIONAL_SEED_COMMANDS

        assert ("drinking", "seed_drinking") in OPTIONAL_SEED_COMMANDS
        assert mod.is_enabled("drinking")
