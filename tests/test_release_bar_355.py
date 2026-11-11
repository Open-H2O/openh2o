# SPDX-License-Identifier: AGPL-3.0-or-later
"""A voided use area reaches only the years it has a record in.

A use area carries no date of its own. When it is voided, the corrections listed for a
finalized year (the Figures as filed card and Check for changes) must name it only in a year
where it has a ledger row or a calculation. Named in a year it never touched, the void would
explain away any change in that year's figures, including one nobody recorded.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from accounting.fingerprints import check_fingerprint, take_fingerprint
from accounting.locks import override
from accounting.models import ReportingPeriod
from accounting.statements import corrections_since
from core import corrections
from tests.factories import ParcelFactory, ParcelLedgerFactory

pytestmark = pytest.mark.django_db

REASON = "drawn twice by mistake"


@pytest.fixture
def operator():
    return get_user_model().objects.create_user(
        username="operator", email="operator@example.org", password="a-good-passw0rd",
        is_active=True, first_name="Jose", last_name="Lopez",
    )


@pytest.fixture
def two_years():
    """WY 2024 finalized with its code taken; WY 2025 open; a use area recorded only in WY 2025."""
    kept = ParcelFactory(parcel_number="KEPT-1")
    ParcelLedgerFactory(parcel=kept, effective_date=dt.date(2024, 3, 1), amount_acre_feet=D("5"))
    only_later = ParcelFactory(parcel_number="LATER-1")
    ParcelLedgerFactory(parcel=only_later, effective_date=dt.date(2025, 3, 1), amount_acre_feet=D("7"))
    first = ReportingPeriod.objects.create(
        name="WY 2023-2024", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30),
    )
    ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30),
    )
    take_fingerprint(first)
    first.is_finalized = True
    first.save()
    return first, only_later


def test_the_finalized_year_does_not_list_a_use_area_it_never_held(two_years, operator):
    first, only_later = two_years
    corrections.void(only_later, user=operator, reason=REASON)
    first.refresh_from_db()

    found = corrections_since(first, first.fingerprint_at, all_records=True)

    assert [line.kind_label for line in found] == []


def test_an_unrecorded_change_in_the_year_is_not_explained_by_that_void(two_years, operator):
    first, only_later = two_years
    corrections.void(only_later, user=operator, reason=REASON)
    with override("a test of an unrecorded change"):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE parcels_parcelledger SET amount_acre_feet = 6 WHERE effective_date = '2024-03-01'"
            )
    first.refresh_from_db()

    answer = check_fingerprint(first)

    assert answer.state == "differs"
    assert answer.corrections == []
    assert "use ledger" in answer.unexplained
