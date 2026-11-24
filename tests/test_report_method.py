# SPDX-License-Identifier: AGPL-3.0-or-later
"""A report records the calculation method and settings code behind its figures.

A report marked filed on an open water year can have its figures recalculated
under a new method later. So the report keeps the method name and the
12-character settings code of the runs of its water year, taken when the file is
made and kept when it is marked filed, and the report page shows them. Runs of
more than one method leave both blank and count the methods, the rule the filed
figures use (``accounting.statements._method``).
"""

from decimal import Decimal

import pytest
from django.test import Client

from accounting.models import CalculationRun
from reporting.models import ReportSubmission, ReportTemplate
from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory, WellFactory, WellIrrigatedParcelFactory

pytestmark = pytest.mark.django_db


def _run(parcel, month, name, code):
    return CalculationRun.objects.create(
        parcel=parcel, period=month, gross_et_af=Decimal("1"), net_consumptive_use_af=Decimal("1"),
        effective_precip_af=Decimal("0"), surface_water_af=Decimal("0"), final_af=Decimal("1"),
        methodology_plan_name=name, config_hash=code,
    )


def _year_with_runs(*methods):
    period = ReportingPeriodFactory()
    field = ParcelFactory()
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-M"), parcel=field)
    from datetime import date

    ParcelLedgerFactory(
        parcel=field, source_type="calculated", amount_acre_feet=-Decimal("4"),
        effective_date=date(2024, 1, 1), transaction_date=date(2024, 1, 1),
    )
    for month, (name, code) in zip(("2024-01", "2024-02", "2024-03"), methods):
        _run(field, month, name, code)
    return period


@pytest.fixture
def client():
    from core.models import User

    c = Client()
    c.force_login(User.objects.create(username="method-reader", email="method@example.com", is_active=True))
    return c


def _generate(client, period):
    template, _ = ReportTemplate.objects.get_or_create(
        report_type="gears_by_et", defaults={"name": "GEARS by ET", "is_active": True},
    )
    response = client.post(
        "/reporting/reports/generate/",
        {"report_template": template.pk, "reporting_period": period.pk, "force": "1"},
    )
    assert response.status_code == 302
    return ReportSubmission.objects.latest("created_at")


def test_generating_a_report_stores_its_method_and_settings_code(client):
    period = _year_with_runs(("District plan", "a582bd80c59b"), ("District plan", "a582bd80c59b"))
    submission = _generate(client, period)
    assert (submission.method_name, submission.settings_code, submission.method_count) == (
        "District plan", "a582bd80c59b", 1,
    )


def test_runs_of_more_than_one_method_leave_the_method_blank_and_count_them(client):
    period = _year_with_runs(("District plan", "a582bd80c59b"), ("Second plan", "0123456789ab"))
    submission = _generate(client, period)
    assert (submission.method_name, submission.settings_code, submission.method_count) == ("", "", 2)


def test_a_filed_report_keeps_the_method_its_file_was_made_under(client):
    period = _year_with_runs(("District plan", "a582bd80c59b"))
    submission = _generate(client, period)
    CalculationRun.objects.update(methodology_plan_name="New plan", config_hash="fedcba987654")
    submission.status = "exported"
    submission.save(update_fields=["status"])
    client.post(
        f"/reporting/reports/{submission.pk}/transition/",
        {"action": "mark_filed", "state_confirmation_number": "GEARS-123"},
    )
    submission.refresh_from_db()
    assert submission.status == "filed"
    assert (submission.method_name, submission.settings_code) == ("District plan", "a582bd80c59b")


def test_the_report_page_shows_the_method_and_settings_code(client):
    period = _year_with_runs(("District plan", "a582bd80c59b"))
    submission = _generate(client, period)
    body = client.get(f"/reporting/reports/{submission.pk}/").content.decode()
    assert "District plan" in body
    assert "a582bd80c59b" in body
