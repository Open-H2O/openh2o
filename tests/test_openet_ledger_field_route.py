# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GEARS by-ET file on OpenET's field-list route.

A use area on the field-list route may have no OpenET cache rows at all: its month's
figure is recorded from OpenET's fields. The by-ET file must still carry that month,
from the recorded figure, exactly as it does for a cached one.

**Every number in this file is made up.** The use area (parcel number "MADEUP-LEDGER-1",
100.00 acres), the OpenET field number (99000000011, 100.00 acres inside the use area)
and the July 2025 depth (304.8 mm, chosen so the line is exactly 100 acre-feet) are
invented for the arithmetic; none is OpenET's.
"""

import datetime as dt
from decimal import Decimal as D

import pytest

from parcels.models import Parcel

pytestmark = pytest.mark.django_db


def test_a_use_area_with_field_shares_and_no_cache_row_gets_its_by_et_line():
    from datasync import crop_et
    from datasync.models import OpenETCache, OpenETField, OpenETFieldMonth, OpenETFieldShare

    parcel = Parcel.objects.create(parcel_number="MADEUP-LEDGER-1", area_acres=D("100.00"))
    field = OpenETField.objects.create(
        field_id=99000000011, area_acres=D("100.00"), received_on=dt.date(2025, 8, 6)
    )
    OpenETFieldShare.objects.create(parcel=parcel, field=field, overlap_acres=D("100.00"))
    OpenETFieldMonth.objects.create(
        field=field,
        month=dt.date(2025, 7, 1),
        et_mm=D("304.8"),
        pr_mm=D("0"),
        received_on=dt.date(2025, 8, 6),
    )
    crop_et.record_fetched_months(parcel, ["2025-07"])
    assert not OpenETCache.objects.exists()

    rows = [
        r for r in crop_et.recorded_acre_feet(dt.date(2024, 10, 1), dt.date(2025, 9, 30))
        if r.parcel_number == "MADEUP-LEDGER-1"
    ]
    assert [(r.month.strftime("%Y-%m"), r.acre_feet) for r in rows] == [("2025-07", D("100.0000"))]
