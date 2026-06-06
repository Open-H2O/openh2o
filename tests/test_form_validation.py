# SPDX-License-Identifier: AGPL-3.0-or-later
"""Form-level clean() guards + report_generate unknown-type guard (ISS-035).

(a) ReportingPeriodForm rejects end<=start at the form layer (never reaches the
    DB CheckConstraint → no 500).
(b) RechargeEventForm rejects negative/zero volume and end<start (a negative
    volume would fan negative supply rows across the zone — balance corruption).
(c) report_generate handles a ReportTemplate whose report_type is none of the
    four known kinds without an UnboundLocalError 500.
"""
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.forms import ReportingPeriodForm
from recharge.forms import RechargeEventForm
from reporting.models import ReportSubmission, ReportTemplate
from surface.forms import DiversionRecordForm
from tests.factories import ReportingPeriodFactory

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"formuser{n}")
    email = factory.Sequence(lambda n: f"formuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------------------
# (a) ReportingPeriodForm
# ---------------------------------------------------------------------------


class TestReportingPeriodForm:
    def test_end_before_start_is_invalid(self):
        form = ReportingPeriodForm(data={
            "name": "Backwards WY",
            "start_date": "2024-09-30",
            "end_date": "2023-10-01",
        })
        assert not form.is_valid()
        assert "end_date" in form.errors

    def test_end_equal_to_start_is_invalid(self):
        form = ReportingPeriodForm(data={
            "name": "Zero-length WY",
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
        })
        assert not form.is_valid()
        assert "end_date" in form.errors

    def test_valid_period_passes(self):
        form = ReportingPeriodForm(data={
            "name": "WY 2024",
            "start_date": "2023-10-01",
            "end_date": "2024-09-30",
        })
        assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# (b) RechargeEventForm
# ---------------------------------------------------------------------------


class TestRechargeEventForm:
    def test_negative_volume_is_rejected(self):
        form = RechargeEventForm(data={
            "start_date": "2024-01-01",
            "volume_acre_feet": "-5",
        })
        assert not form.is_valid()
        assert "volume_acre_feet" in form.errors

    def test_zero_volume_is_rejected(self):
        form = RechargeEventForm(data={
            "start_date": "2024-01-01",
            "volume_acre_feet": "0",
        })
        assert not form.is_valid()
        assert "volume_acre_feet" in form.errors

    def test_end_before_start_is_rejected(self):
        form = RechargeEventForm(data={
            "start_date": "2024-06-01",
            "end_date": "2024-01-01",
            "volume_acre_feet": "10",
        })
        assert not form.is_valid()
        assert "end_date" in form.errors

    def test_positive_volume_passes(self):
        form = RechargeEventForm(data={
            "start_date": "2024-01-01",
            "volume_acre_feet": "10.5",
        })
        assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# (c) report_generate unknown report_type
# ---------------------------------------------------------------------------


class TestReportGenerateUnknownType:
    def test_unknown_report_type_is_handled_not_500(self, auth_client):
        # report_type choices are not DB-enforced, so a template can carry a type
        # outside the four known kinds.
        template = ReportTemplate.objects.create(
            name="Legacy Template",
            report_type="legacy_unknown",
            is_active=True,
        )
        period = ReportingPeriodFactory()
        url = reverse("reporting:report_generate")

        resp = auth_client.post(url, {
            "report_template": template.pk,
            "reporting_period": period.pk,
        })

        assert resp.status_code == 200  # handled, not UnboundLocalError 500
        assert b"Unknown report type" in resp.content
        # Nothing was generated.
        assert ReportSubmission.objects.count() == 0


# ---------------------------------------------------------------------------
# Phase 67-02 — DiversionRecordForm returned_af guard
#
# The model.clean() guard (67-01) is the backstop, but Model.save() never calls
# it. The form is the operator's entry boundary, so a return larger than the
# diverted volume must surface as a readable FIELD error (not a 500), and a blank
# entry must store 0 so existing entry flows are unchanged.
# ---------------------------------------------------------------------------


class TestDiversionReturnedAfFormGuard:
    def _data(self, **overrides):
        data = {
            "month": "2024-03-01",
            "volume_acre_feet": "40",
            "diversion_type": "direct_use",
        }
        data.update(overrides)
        return data

    def test_returned_exceeding_volume_is_a_field_error_not_500(self):
        form = DiversionRecordForm(self._data(returned_af="50"))
        assert not form.is_valid()
        assert "returned_af" in form.errors
        assert "exceed" in " ".join(form.errors["returned_af"]).lower()

    def test_returned_at_or_below_volume_is_valid(self):
        form = DiversionRecordForm(self._data(returned_af="40"))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["returned_af"] == Decimal("40")

    def test_blank_returned_defaults_to_zero(self):
        form = DiversionRecordForm(self._data())  # returned_af omitted
        assert form.is_valid(), form.errors
        assert form.cleaned_data["returned_af"] == Decimal("0")
