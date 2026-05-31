# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the conformance ObservedProperty registry (Phase 31-01).

Covers the publish-gate predicate, seed idempotency, full crosswalk coverage
against the live adapter PARAMETER_MAPs, and the check_conformance gate's
exit-code contract (gate on UCUM for all, treat a blank pcode as a known
non-blocking exception).

DB access is auto-enabled for all tests via the root conftest.py.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from datasync.adapters import registry
from measurements.models import SensorMeasurement
from standards.models import ObservedProperty, SourceParameter


class TestIsPublishable:
    """is_publishable() is True only when BOTH pcode and UCUM are non-empty."""

    def test_both_present_is_publishable(self):
        op = ObservedProperty(key="x", name="X", usgs_pcode="00060", ucum_unit="[cft_i]/s")
        assert op.is_publishable() is True

    def test_missing_pcode_not_publishable(self):
        op = ObservedProperty(key="x", name="X", usgs_pcode="", ucum_unit="mm")
        assert op.is_publishable() is False

    def test_missing_ucum_not_publishable(self):
        op = ObservedProperty(key="x", name="X", usgs_pcode="00060", ucum_unit="")
        assert op.is_publishable() is False

    def test_both_missing_not_publishable(self):
        op = ObservedProperty(key="x", name="X", usgs_pcode="", ucum_unit="")
        assert op.is_publishable() is False


class TestSeedCommand:
    def test_seed_creates_registry(self):
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        assert ObservedProperty.objects.exists()
        assert SourceParameter.objects.exists()

    def test_seed_is_idempotent(self):
        """Running the seed twice yields identical row counts (no duplicates)."""
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        op_count = ObservedProperty.objects.count()
        sp_count = SourceParameter.objects.count()

        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        assert ObservedProperty.objects.count() == op_count
        assert SourceParameter.objects.count() == sp_count

    def test_every_adapter_code_resolves(self):
        """
        Every (source, code) the adapters emit must crosswalk to an
        ObservedProperty. This locks the registry against drift: if an adapter
        gains a PARAMETER_MAP entry without a CODE_TO_KEY mapping, this fails.
        """
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        for (source_code, parameter_code) in registry.get_all_parameter_maps():
            sp = SourceParameter.objects.filter(
                source_code=source_code, parameter_code=parameter_code
            ).first()
            assert sp is not None, f"no crosswalk for {source_code}:{parameter_code}"
            assert sp.observed_property_id is not None

    def test_blank_pcode_concepts_present(self):
        """Reservoir/ET concepts correctly carry a blank USGS pcode."""
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        storage = ObservedProperty.objects.get(key="reservoir_storage")
        assert storage.usgs_pcode == ""
        assert storage.ucum_unit  # but it DOES carry a UCUM unit

    def test_all_seeded_properties_have_ucum(self):
        """Every seeded concept carries a UCUM unit (the conformance contract)."""
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        assert not ObservedProperty.objects.filter(ucum_unit="").exists()


class TestCheckConformance:
    def test_passes_on_clean_seeded_registry(self):
        """The seeded registry is UCUM-complete → gate exits zero (no raise)."""
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        # Should not raise SystemExit.
        call_command("check_conformance", stdout=StringIO(), stderr=StringIO())

    def test_fails_when_missing_ucum(self):
        """A property missing a UCUM unit is a blocking gap → non-zero exit."""
        ObservedProperty.objects.create(
            key="broken", name="Broken", usgs_pcode="99999", ucum_unit=""
        )
        with pytest.raises(SystemExit):
            call_command("check_conformance", stdout=StringIO(), stderr=StringIO())

    def test_missing_pcode_only_is_not_blocking(self):
        """A blank pcode (with UCUM present) is a known exception, not a failure."""
        ObservedProperty.objects.create(
            key="et_only", name="ET", usgs_pcode="", ucum_unit="mm"
        )
        # Should not raise — pcode-less is reported as pending, not blocking.
        call_command("check_conformance", stdout=StringIO(), stderr=StringIO())

    def test_null_measurement_fk_is_not_blocking(self):
        """A measurement with a null observed_property FK is reported, not blocking."""
        from measurements.models import Sensor

        sensor = Sensor.objects.create(name="S1", sensor_type="level")
        SensorMeasurement.objects.create(
            sensor=sensor,
            measurement_date="2024-06-01T00:00:00Z",
            value="1.0",
            unit="ft",
        )
        call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())
        # Null FK present but registry is UCUM-complete → still passes.
        call_command("check_conformance", stdout=StringIO(), stderr=StringIO())
