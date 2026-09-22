# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-04 Task 2 (D7, ISS-184): the SystemProduction model itself -- the shape,
the save-time conversions, and the uniqueness rule -- separate from the
import service, which has its own test file (``test_production_import.py``).
"""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from drinking.models import SystemFacility, SystemProduction, WaterSystem

pytestmark = pytest.mark.django_db


@pytest.fixture
def system():
    return WaterSystem.objects.create(pwsid="CA9999001", name="Test System")


def test_gallons_unit_is_a_straight_carry(system):
    record = SystemProduction.objects.create(
        system=system, year=2024, month=6, type_code="GW",
        volume_as_reported=Decimal("1234.50"), unit_as_reported="G",
        provenance="typed",
    )
    assert record.volume_gallons == Decimal("1234.50")


def test_ccf_converts_at_748_05_gallons(system):
    record = SystemProduction.objects.create(
        system=system, year=2024, month=6, type_code="GW",
        volume_as_reported=Decimal("10"), unit_as_reported="CCF",
        provenance="typed",
    )
    assert record.volume_gallons == Decimal("7480.50")


def test_af_converts_at_325851_gallons(system):
    record = SystemProduction.objects.create(
        system=system, year=2024, month=6, type_code="GW",
        volume_as_reported=Decimal("1"), unit_as_reported="AF",
        provenance="typed",
    )
    assert record.volume_gallons == Decimal("325851.00")
    assert record.volume_acre_feet == Decimal("1.00")


def test_month_nullable_means_the_year_reported_as_one_figure(system):
    record = SystemProduction.objects.create(
        system=system, year=2024, month=None, type_code="GW",
        volume_as_reported=Decimal("100"), unit_as_reported="G",
        provenance="typed",
    )
    assert record.month is None


def test_unique_together_refuses_a_second_row_for_the_same_key(system):
    """With a facility attached, the DB constraint fires directly.

    Postgres treats NULL as distinct from NULL, so a facility-less pair
    (the common case -- neither import layout names one) is NOT caught by
    this constraint; that case is guarded by the importer's own dedup query
    instead (``drinking/production_import.py::commit_rows``,
    ``test_production_import.py::test_ear_reimport_creates_nothing``).
    """
    facility = SystemFacility.objects.create(system=system, facility_id="001")
    SystemProduction.objects.create(
        system=system, year=2024, month=3, type_code="GW", facility=facility,
        volume_as_reported=Decimal("100"), unit_as_reported="G",
        provenance="typed",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SystemProduction.objects.create(
                system=system, year=2024, month=3, type_code="GW", facility=facility,
                volume_as_reported=Decimal("999"), unit_as_reported="G",
                provenance="typed",
            )


def test_str_names_the_system_year_month_and_type(system):
    record = SystemProduction.objects.create(
        system=system, year=2024, month=3, type_code="GW",
        volume_as_reported=Decimal("100"), unit_as_reported="G",
        provenance="typed",
    )
    text = str(record)
    assert system.pwsid in text
    assert "2024" in text
    assert "GW" in text
