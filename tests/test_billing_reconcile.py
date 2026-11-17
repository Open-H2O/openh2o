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

    def test_by_et_uses_calculated_and_falls_back(self):
        """Calculated parcel reports its NET volume; fallback parcel reports
        gross; no duplicate row. (Both carry the state method label
        'Unmetered/Estimated' since ISS-047a — the net-vs-gross distinction is
        proven by the volume column, not the method string.)"""
        period = self._period()
        p_calc = ParcelFactory()
        p_fallback = ParcelFactory()
        # gross 11, net 9 — distinct so we can prove the netted number is used
        _recorded(p_calc, "-11")
        _calc(p_calc, "-9")
        _recorded(p_fallback, "-14")

        content = generate_gears_csv(period, method="by_et").read()
        _, rows = self._rows(content)

        # Columns: Parcel Number, Area, Month, ET Volume (AF), Measurement Method
        by_parcel = {r[0]: r for r in rows}
        assert len(rows) == 2  # exactly one row per parcel — no duplicate

        calc_row = by_parcel[p_calc.parcel_number]
        assert calc_row[4] == "Unmetered/Estimated"
        assert Decimal(calc_row[3]) == Decimal("9")  # net, not gross 11

        fb_row = by_parcel[p_fallback.parcel_number]
        assert fb_row[4] == "Unmetered/Estimated"
        assert Decimal(fb_row[3]) == Decimal("14")

    def test_by_et_calculated_gross_not_duplicated(self):
        """The calculated parcel's gross recorded crop ET must not appear."""
        period = self._period()
        p_calc = ParcelFactory()
        _recorded(p_calc, "-11")
        _calc(p_calc, "-9")

        content = generate_gears_csv(period, method="by_et").read()
        _, rows = self._rows(content)
        assert len(rows) == 1
        assert rows[0][4] == "Unmetered/Estimated"
        assert Decimal(rows[0][3]) == Decimal("9")
