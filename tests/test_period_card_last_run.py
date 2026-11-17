# SPDX-License-Identifier: AGPL-3.0-or-later
"""The water year card's "Last calculation run" is the night the calculation last ran.

The calculation keeps a stored figure that came out the same, with its
creation time, so the newest figure no longer says when the calculation last
ran. The card reads the newest finished calculation request whose months fall
in the year instead.
"""
import datetime as dt
import re

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import CalculationRequest, CalculationRun
from core.models import User
from tests.factories import ParcelFactory, ReportingPeriodFactory

pytestmark = pytest.mark.django_db


def _at(day):
    return timezone.make_aware(dt.datetime(day.year, day.month, day.day, 12, 0))


@pytest.fixture
def year():
    period = ReportingPeriodFactory(
        name="WY 2025-2026", start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30)
    )
    run = CalculationRun.objects.create(
        parcel=ParcelFactory(), period="2025-11", gross_et_af=0, net_consumptive_use_af=0,
        residual_disposition="unmet_demand", unmet_demand_af=0,
        final_af=0, breakdown=[],
    )
    CalculationRun.objects.filter(pk=run.pk).update(created_at=_at(dt.date(2025, 11, 3)))
    return period


def _card(period):
    admin = User.objects.create(
        username="card-admin@example.com", email="card-admin@example.com",
        is_active=True, agency_admin=True,
    )
    client = Client()
    client.force_login(admin)
    body = client.get(reverse("accounting:dashboard"), {"period": period.pk}).content.decode()
    found = re.search(r"<span>Last calculation run</span><b>([^<]*)</b>", body)
    assert found, "the card has no Last calculation run line"
    return found.group(1)


def _request(period, finished, status="succeeded", months=("2025-10", "2025-11")):
    return CalculationRequest.objects.create(
        trigger="schedule", reporting_period=period, months=list(months), status=status,
        started_at=_at(finished), finished_at=_at(finished), months_done=len(months),
    )


def test_the_card_shows_the_day_the_calculation_last_ran_not_the_newest_figure(year):
    _request(year, dt.date(2025, 11, 9))
    assert _card(year) == "Nov 9, 2025"


def test_a_run_finished_with_notes_counts(year):
    _request(year, dt.date(2025, 11, 10), status="finished_with_notes")
    assert _card(year) == "Nov 10, 2025"


def test_a_stopped_run_does_not_count(year):
    _request(year, dt.date(2025, 11, 9))
    _request(year, dt.date(2025, 11, 12), status="failed")
    assert _card(year) == "Nov 9, 2025"


def test_a_run_of_named_months_in_the_year_counts(year):
    _request(None, dt.date(2025, 11, 14), months=("2025-12",))
    assert _card(year) == "Nov 14, 2025"


def test_a_run_of_months_in_another_year_does_not_count(year):
    _request(year, dt.date(2025, 11, 9))
    _request(None, dt.date(2025, 11, 20), months=("2024-12",))
    assert _card(year) == "Nov 9, 2025"


def test_with_no_finished_request_the_card_falls_back_to_the_newest_figure(year):
    assert _card(year) == "Nov 3, 2025"
