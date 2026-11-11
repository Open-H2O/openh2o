# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check for changes reads the same rows it read when the year's code was taken.

Carry-over and Account credits are chosen by the water year's name (the year its end month
falls in, counted from the site's start month). The start month is a setting on the site's
settings page and can be changed at any time. Changing it after a year was finalized must not
make Check report a part as changed when no record changed.
"""

import datetime as dt
from decimal import Decimal as D

import pytest

from accounting.fingerprints import check_fingerprint, take_fingerprint
from accounting.models import AccountCredit, AllocationCarryover, ReportingPeriod
from core.models import SiteConfig
from tests.factories import WaterAccountFactory, WaterTypeFactory, ZoneFactory

pytestmark = pytest.mark.django_db


def _site(month):
    config = SiteConfig.objects.first() or SiteConfig.objects.create(agency_name="Test Agency")
    config.water_year_start_month = month
    config.save()
    return config


@pytest.fixture
def filed_year():
    """WY 2024-2025 (Oct to Sep) with carry-over and account credits named 2025 and 2026."""
    _site(10)
    zone = ZoneFactory()
    water_type = WaterTypeFactory()
    account = WaterAccountFactory()
    for water_year, amount in ((2025, "10"), (2026, "20")):
        AllocationCarryover.objects.create(
            zone=zone, water_type=water_type, water_year=water_year,
            source_water_year=water_year - 1, amount_af=D(amount), origin="allocation_carryover",
        )
        AccountCredit.objects.create(
            water_account=account, water_type=water_type, water_year=water_year,
            origin=AccountCredit._meta.get_field("origin").choices[0][0],
            amount_af=D(amount), source_key=f"invented-{water_year}",
            description="Invented for this test",
        )
    period = ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30),
    )
    take_fingerprint(period)
    period.is_finalized = True
    period.save()
    assert check_fingerprint(period).state == "matches"
    return period


def test_moving_the_start_month_after_the_code_was_taken_changes_no_answer(filed_year):
    _site(9)
    filed_year.refresh_from_db()

    answer = check_fingerprint(filed_year)

    assert answer.state == "matches", answer.differing


def test_a_code_kept_before_the_name_was_stored_reads_todays_name(filed_year):
    parts = dict(filed_year.fingerprint_parts)
    assert parts.pop("water_year") == 2025
    ReportingPeriod.objects.filter(pk=filed_year.pk).update(fingerprint_parts=parts)
    filed_year.refresh_from_db()

    assert check_fingerprint(filed_year).state == "matches"
