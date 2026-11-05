# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-352: a row stamped "today" carries the site's date, not UTC's.

``timezone.now().date()`` is the UTC date, and the site's time zone is America/Los_Angeles,
so after 4 PM Pacific it stamped tomorrow. ``timezone.localdate()`` is right.

**The clock.** The project has no freezegun (pyproject.toml lists none) and its tests mock
by ``unittest.mock.patch``, so the clock is held by patching ``django.utils.timezone.now``,
which ``timezone.localdate()`` itself reads. It is held at 2026-11-04 21:05 PST, which is
2026-11-05 05:05 UTC: the two readings of "today" differ, so a test passes only on the
site's date. Each test drives the real function and reads the actual row's
``transaction_date``.
"""
import datetime as dt
import re
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounting.models import CalculationRun
from accounting.services import create_diversion_ledger_entries
from datasync.models import OpenETCache
from parcels.models import Parcel, ParcelLedger
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterRightParcelFactory,
)

pytestmark = pytest.mark.django_db

PACIFIC_EVENING = dt.datetime(2026, 11, 5, 5, 5, tzinfo=dt.timezone.utc)  # 2026-11-04 21:05 PST
SITE_DAY = dt.date(2026, 11, 4)
UTC_DAY = dt.date(2026, 11, 5)
JAN = dt.date(2024, 1, 1)
ROOT = Path(__file__).resolve().parent.parent


def held_clock():
    return mock.patch("django.utils.timezone.now", return_value=PACIFIC_EVENING)


def test_the_held_clock_really_splits_the_two_dates():
    with held_clock():
        assert timezone.now().date() == UTC_DAY
        assert timezone.localdate() == SITE_DAY


def _two_parcel_pod():
    rp = ReportingPeriodFactory()
    a = ParcelFactory(parcel_number="APN-A")
    b = ParcelFactory(parcel_number="APN-B")
    pod = PointOfDiversionFactory(division_method="crop_need", evaporation_fraction=Decimal("0"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.5"))
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.5"))
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN, volume_acre_feet=Decimal("100"),
    )
    return rp, a, b, pod, record


def _dates(qs):
    return sorted(set(qs.values_list("transaction_date", flat=True)))


# --------------------------------------------------------------- surface/services.py
def test_surface_demand_weighted_rows_are_stamped_with_the_site_date():  # line 171
    rp, a, b, pod, _ = _two_parcel_pod()
    for parcel in (a, b):
        CalculationRun.objects.create(
            parcel=parcel, period="2024-01", gross_et_af=Decimal("50"),
            net_consumptive_use_af=Decimal("50"), final_af=Decimal("0"),
        )
    with held_clock():
        rows = allocate_district_delivery(pod, rp, efficiency=Decimal("0.75"))
    assert len(rows) == 2
    assert [r.transaction_date for r in rows] == [SITE_DAY, SITE_DAY]
    assert _dates(ParcelLedger.objects.filter(source_type="surface_diversion")) == [SITE_DAY]


def test_surface_static_fraction_rows_are_stamped_with_the_site_date():  # line 227
    rp, a, b, pod, _ = _two_parcel_pod()  # no CalculationRun: the fraction fallback
    with held_clock():
        rows = allocate_district_delivery(pod, rp, efficiency=Decimal("0.75"))
    assert len(rows) == 2
    assert [r.transaction_date for r in rows] == [SITE_DAY, SITE_DAY]
    assert _dates(ParcelLedger.objects.filter(source_type="surface_diversion")) == [SITE_DAY]


def test_a_dry_run_hands_back_unsaved_rows_with_the_site_date():  # lines 171 and 227, unsaved
    rp, a, b, pod, _ = _two_parcel_pod()
    with held_clock():
        rows = allocate_district_delivery(pod, rp, efficiency=Decimal("0.75"), dry_run=True)
    assert rows and all(r.pk is None for r in rows)
    assert {r.transaction_date for r in rows} == {SITE_DAY}


# --------------------------------------------------------------- accounting/services.py
def test_fraction_split_entries_are_stamped_with_the_site_date():  # line 283 (`today` is each row's transaction_date)
    _, a, b, pod, record = _two_parcel_pod()
    with held_clock():
        entries = create_diversion_ledger_entries(record)
    assert len(entries) == 2
    assert [e.transaction_date for e in entries] == [SITE_DAY, SITE_DAY]
    assert _dates(ParcelLedger.objects.filter(source_type="surface_diversion")) == [SITE_DAY]


def test_the_explicit_parcel_entry_is_stamped_with_the_site_date():  # line 340
    _, a, _, _, record = _two_parcel_pod()
    with held_clock():
        entries = create_diversion_ledger_entries(record, parcel=a)
    assert [e.transaction_date for e in entries] == [SITE_DAY]
    assert ParcelLedger.objects.get(pk=entries[0].pk).transaction_date == SITE_DAY


def test_the_water_right_fallback_entry_is_stamped_with_the_site_date():  # line 375
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory()
    pod = PointOfDiversionFactory(evaporation_fraction=Decimal("0"))
    WaterRightParcelFactory(water_right=pod.water_right, parcel=parcel)
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=JAN, volume_acre_feet=Decimal("100"),
    )
    with held_clock():
        entries = create_diversion_ledger_entries(record)
    assert [e.transaction_date for e in entries] == [SITE_DAY]
    assert ParcelLedger.objects.get(pk=entries[0].pk).transaction_date == SITE_DAY


# --------------------------------------------------------------- sync_openet_to_ledger
def test_the_openet_sync_stamps_its_rows_with_the_site_date():  # command line 145
    parcel = ParcelFactory(parcel_number="APN-ET")
    Parcel.objects.filter(pk=parcel.pk).update(area_acres=Decimal("100"))
    OpenETCache.objects.create(
        parcel=parcel, geometry=parcel.geometry, start_date=dt.date(2025, 1, 1), end_date=dt.date(2025, 12, 31),
        variable="ET", model_name="Ensemble", et_data=[{"date": "2025-07", "et": 30.48, "unit": "mm"}],
    )
    with held_clock():
        call_command("sync_openet_to_ledger", start_date="2025-01-01", end_date="2025-12-31")
    rows = ParcelLedger.objects.filter(source_type="et_estimate", parcel=parcel)
    assert rows.count() == 1
    row = rows.get()
    assert row.transaction_date == SITE_DAY
    assert row.effective_date == dt.date(2025, 7, 1)


# --------------------------------------------------------------- the guard
GUARDED = ("accounting", "surface", "parcels", "wells", "datasync", "core")


def test_no_product_code_stamps_a_date_from_the_utc_clock():
    pattern = re.compile(r"timezone\.now\(\)\.date\(\)")
    hits = []
    for app in GUARDED:
        for path in sorted((ROOT / app).rglob("*.py")):
            if "migrations" in path.relative_to(ROOT).parts:
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{number}")
    assert hits == [], f"timezone.now().date() is the UTC date; use timezone.localdate(): {hits}"
