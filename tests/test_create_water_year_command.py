# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.1 step C: ``create_water_year`` does what the Water Years create page does.

The page and the command create the same ``ReportingPeriod`` and attach the same
orphan diversion records and ledger entries, because both call one function.
Messages are copied from the approved rows in ``152-03.1-ROWS.md``: row 34 (the
success sentence) and row 35 (the refusal), plus the form's own start-date sentence.

Test data is INVENTED: an "Example Ditch Company" point of diversion
(X000001_01, "North Headgate") with records and ledger entries in 2024.
"""
from datetime import date
from io import StringIO

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import Client
from django.urls import reverse

from accounting.models import ReportingPeriod
from parcels.models import ParcelLedger
from surface.models import DiversionRecord
from tests.factories import (
    DiversionRecordFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
)

pytestmark = pytest.mark.django_db

ROW_34 = (
    "Water year created. OpenH2O attached 2 diversion records and 1 ledger entries "
    "dated inside it to this water year."
)
ROW_35 = "OpenH2O did not create the water year."
FORM_START_SENTENCE = "A water year starts on the first day of a month."


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"wyuser{n}")
    email = factory.Sequence(lambda n: f"wyuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.fixture
def orphans(db):
    """Records made BEFORE any water year exists: two inside 2024, one outside, one ledger entry each side."""
    pod = PointOfDiversionFactory(name="X000001_01")
    DiversionRecordFactory(point_of_diversion=pod, month=date(2024, 3, 1), reporting_period=None)
    DiversionRecordFactory(point_of_diversion=pod, month=date(2024, 4, 1), reporting_period=None)
    DiversionRecordFactory(point_of_diversion=pod, month=date(2025, 4, 1), reporting_period=None)
    ParcelLedgerFactory(effective_date=date(2024, 5, 1), reporting_period=None)
    ParcelLedgerFactory(effective_date=date(2026, 5, 1), reporting_period=None)
    return pod


INPUT = {
    "name": "2024 Water Year",
    "start": "2024-01-01",
    "end": "2024-12-31",
    "notes": "An invented note.",
}


def _snapshot():
    period = ReportingPeriod.objects.get()
    return {
        "period": (period.name, period.start_date, period.end_date, period.notes, period.is_finalized),
        "records": sorted(
            (r.month, r.reporting_period_id == period.pk) for r in DiversionRecord.objects.all()
        ),
        "ledger": sorted(
            (ln.effective_date, ln.reporting_period_id == period.pk) for ln in ParcelLedger.objects.all()
        ),
    }


def _via_the_page(client):
    return client.post(
        reverse("accounting:period_create"),
        {
            "name": INPUT["name"],
            "start_date": INPUT["start"],
            "end_date": INPUT["end"],
            "notes": INPUT["notes"],
        },
        follow=True,
    )


def _via_the_command(*extra, **kw):
    out = StringIO()
    call_command(
        "create_water_year",
        "--name", INPUT["name"], "--start", INPUT["start"], "--end", INPUT["end"],
        "--notes", INPUT["notes"], *extra, stdout=out, **kw,
    )
    return out.getvalue()


def test_page_and_command_create_the_same_water_year_and_attach_the_same_records(
    auth_client, orphans
):
    # Run the page, read what it left, undo it, then run the command on the same data.
    savepoint = transaction.savepoint()
    response = _via_the_page(auth_client)
    assert response.status_code == 200
    assert ROW_34 in response.content.decode()
    from_page = _snapshot()
    transaction.savepoint_rollback(savepoint)
    assert ReportingPeriod.objects.count() == 0

    out = _via_the_command()

    assert _snapshot() == from_page
    # Two records and one ledger entry inside the year attached; the rest did not.
    assert [attached for _, attached in from_page["records"]].count(True) == 2
    assert [attached for _, attached in from_page["ledger"]].count(True) == 1
    assert out.strip().splitlines()[-1] == ROW_34


def test_the_command_prints_row_34(orphans):
    out = _via_the_command()

    assert ROW_34 in out.splitlines()


def test_a_start_that_is_not_the_first_of_a_month_is_refused_and_nothing_is_created(orphans):
    with pytest.raises(CommandError) as err:
        call_command(
            "create_water_year",
            "--name", "Mid Month Year", "--start", "2024-01-15", "--end", "2024-12-31",
            stdout=StringIO(),
        )

    assert ROW_35 in str(err.value)
    assert FORM_START_SENTENCE in str(err.value)
    assert ReportingPeriod.objects.count() == 0
    assert DiversionRecord.objects.filter(reporting_period__isnull=False).count() == 0
