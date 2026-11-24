# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GEARS by-ET file reads a month's net calculated figure where there is one.

Where a ``calculated`` ledger row exists for a use area and month, the file reports its
net volume; where none does, it reports the recorded crop ET. Rows are built directly
(no GEE/cache): pure arithmetic, fast and deterministic.
"""
import csv as csv_mod
from datetime import date
from decimal import Decimal

import pytest

from reporting.generators import generate_gears_csv
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
)

JUNE = date(2024, 6, 1)


def _recorded(parcel, amount, month=JUNE):
    """The month's recorded crop ET, as a depth that is ``abs(amount)`` acre-feet over the use area's acres."""
    from datasync.models import CropETFigure

    return CropETFigure.objects.create(
        parcel=parcel, month=month, variable="ET", model_name="Ensemble",
        depth_mm=abs(Decimal(amount)) * Decimal("304.8") / parcel.area_acres,
    )


def _calc(parcel, amount, effective_date=JUNE):
    """A netted calculation-engine row (stored negative)."""
    return ParcelLedgerFactory(
        parcel=parcel,
        source_type="calculated",
        effective_date=effective_date,
        amount_acre_feet=Decimal(amount),
    )


@pytest.mark.django_db
class TestGearsByEtReconcile:
    def _period(self):
        return ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

    def _rows(self, content):
        reader = csv_mod.reader(content.splitlines())
        header = next(reader)
        return header, [r for r in reader if r]

    def test_by_et_uses_calculated_and_leaves_out_the_uncalculated_month(self):
        """A calculated use area reports its calculated figure, never its gross crop ET;
        a use area with crop ET and no calculation puts no line in the file."""
        from tests.factories import WellFactory, WellIrrigatedParcelFactory

        period = self._period()
        p_calc = ParcelFactory()
        p_fallback = ParcelFactory()
        WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-CALC"), parcel=p_calc)
        WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-FALLBACK"), parcel=p_fallback)
        # gross 11, net 9: distinct so we can prove the netted number is used
        _recorded(p_calc, "-11")
        _calc(p_calc, "-9")
        _recorded(p_fallback, "-14")

        content = generate_gears_csv(period, method="by_et").read()
        _, rows = self._rows(content)

        # The by-well columns: Well Registration ID, ..., Extraction Volume (AF), Measurement Method
        assert [(r[0], Decimal(r[5]), r[6]) for r in rows] == [
            ("REG-CALC", Decimal("9"), "Unmetered/Estimated"),
        ]

    def test_by_et_calculated_gross_not_duplicated(self):
        """The calculated parcel's gross recorded crop ET must not appear."""
        from tests.factories import WellFactory, WellIrrigatedParcelFactory

        period = self._period()
        p_calc = ParcelFactory()
        WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-CALC"), parcel=p_calc)
        _recorded(p_calc, "-11")
        _calc(p_calc, "-9")

        content = generate_gears_csv(period, method="by_et").read()
        _, rows = self._rows(content)
        assert len(rows) == 1
        assert rows[0][6] == "Unmetered/Estimated"
        assert Decimal(rows[0][5]) == Decimal("9")
