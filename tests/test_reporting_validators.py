# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-02 Task 3, ISS-181: the CalWATRS validator's fix instruction for an
orphaned diversion record ("attached to NO reporting period") used to say
"Re-save them (or edit and save) so they attach to the period." — naming a
control (edit) the record page did not have.

Ruling (146-02 Task 3): now that a period attaches its own orphans on save
(``accounting.services.attach_orphans_to_period``) and a record can be
opened and saved on its own (``surface:diversion_record_edit``), the
sentence is retargeted to name both real paths: "Create or edit the water
year that covers these months; records attach when the year is saved, or
open each record and save it." (``reporting/validators.py``).

A repo-wide grep for the retired "Re-save" wording (``grep -rn "Re-save"
tests/``) found no prior test pinning it, so nothing else needed
retargeting; this file is the sentence's only guard.
"""
from datetime import date
from decimal import Decimal

import pytest

from reporting.validators import validate_report
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
)

pytestmark = pytest.mark.django_db


def _period():
    return ReportingPeriodFactory(
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
    )


class TestOrphanedRecordMessageIsRetargeted:
    def test_orphan_inside_the_period_names_the_year_and_the_record_paths(self):
        period = _period()
        pod = PointOfDiversionFactory(water_right=WaterRightFactory())
        # A normal, attached record so the "no records at all" error doesn't fire.
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=period,
            month=date(2024, 3, 1), volume_acre_feet=Decimal("40.0000"),
            diversion_type="direct_use",
        )
        # The orphan: dated inside the period, but reporting_period is None.
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=None,
            month=date(2024, 4, 1), volume_acre_feet=Decimal("10.0000"),
            diversion_type="direct_use",
        )

        messages = " ".join(w["message"] for w in validate_report(period, "calwatrs_a1"))

        assert (
            "Create or edit the water year that covers these months; records "
            "attach when the year is saved, or open each record and save it."
        ) in messages
        assert "Re-save them" not in messages

    def test_the_retired_sentence_is_gone_from_the_module(self):
        """A direct source guard, in case a future edit reintroduces the
        retired wording without going through validate_report's own message
        path (e.g. a second warning built from a shared string constant)."""
        import inspect

        import reporting.validators as validators_module

        source = inspect.getsource(validators_module)
        assert "Re-save" not in source
