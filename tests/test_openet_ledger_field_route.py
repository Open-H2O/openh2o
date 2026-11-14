# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger copy of crop ET on OpenET's field-list route.

A use area on the field-list route may have no OpenET cache rows at all: its month's
figure is recorded from OpenET's fields. ``sync_openet_to_ledger`` must still write that
month's ET estimate entry, from the recorded figure, exactly as it does for a cached one.

**Every number in this file is made up.** The use area (parcel number "MADEUP-LEDGER-1",
100.00 acres), the OpenET field number (99000000011, 100.00 acres inside the use area)
and the July 2025 depth (304.8 mm, chosen so the entry is exactly 100 acre-feet) are
invented for the arithmetic; none is OpenET's.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.management import call_command

from parcels.models import Parcel, ParcelLedger

pytestmark = pytest.mark.django_db


def test_a_use_area_with_field_shares_and_no_cache_row_gets_its_ledger_entry():
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

    call_command("sync_openet_to_ledger", "--start-date", "2025-07-01", "--end-date", "2025-07-31")

    entries = ParcelLedger.objects.current().filter(parcel=parcel, source_type="et_estimate")
    assert entries.count() == 1
    entry = entries.get()
    assert entry.effective_date == dt.date(2025, 7, 1)
    assert entry.amount_acre_feet == D("-100.0000")
    assert "304.80mm" in entry.description
