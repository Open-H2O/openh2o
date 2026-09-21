# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-02 Task 3, ISS-181: a diversion record can be edited and deleted.

Three doors proven here, each RED against the unfixed tree (the exact quotes
live in 146-02-EVIDENCE.md):

  1. GET/POST diversion/<pk>/record/<rpk>/edit/: edit changes a field and the
     page shows the new value; an edit re-runs the reporting-period lookup
     for the (possibly changed) month; an invalid submit keeps the row in
     edit mode with the error visible, never a silent reset.
  2. POST diversion/<pk>/record/<rpk>/delete/: removes the row.
  3. A unique-constraint violation on (point_of_diversion, month,
     diversion_type) -- on create or on edit -- renders as a form error, not
     a 500 (before this task, point_of_diversion is excluded from the form's
     fields, so Django's own ModelForm unique_together check never ran it,
     and the raw database constraint hit as an uncaught IntegrityError).
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.models import DiversionRecord
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"editrecuser{n}")
    email = factory.Sequence(lambda n: f"editrecuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. Edit
# ---------------------------------------------------------------------------


class TestDiversionRecordEdit:
    def test_get_shows_a_bound_edit_form(self, auth_client):
        pod = PointOfDiversionFactory()
        record = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1),
            volume_acre_feet=Decimal("33.0000"),
        )

        resp = auth_client.get(
            reverse("surface:diversion_record_edit", args=[pod.pk, record.pk])
        )

        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Edit diversion record" in body
        assert "33" in body

    def test_post_changes_the_volume_and_the_page_shows_it(self, auth_client):
        pod = PointOfDiversionFactory()
        record = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1),
            volume_acre_feet=Decimal("33.0000"), diversion_type="direct_use",
        )

        resp = auth_client.post(
            reverse("surface:diversion_record_edit", args=[pod.pk, record.pk]),
            {
                "month": "2024-03-15",
                "volume_acre_feet": "99.5",
                "returned_af": "0",
                "diversion_type": "direct_use",
            },
        )

        assert resp.status_code == 200
        record.refresh_from_db()
        assert record.volume_acre_feet == Decimal("99.5000")
        assert "99.50" in resp.content.decode()

    def test_post_normalizes_the_month_to_the_first(self, auth_client):
        """clean_month (surface/forms.py): a season is a month, not a date --
        the widget is a full date picker, but a picked day always collapses
        to the 1st, matching the plan's own create-form rule for edit too."""
        pod = PointOfDiversionFactory()
        record = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1),
            volume_acre_feet=Decimal("33.0000"), diversion_type="direct_use",
        )

        auth_client.post(
            reverse("surface:diversion_record_edit", args=[pod.pk, record.pk]),
            {
                "month": "2024-04-17",
                "volume_acre_feet": "51",
                "returned_af": "0",
                "diversion_type": "direct_use",
            },
        )

        record.refresh_from_db()
        assert record.month == date(2024, 4, 1)

    def test_edit_re_runs_the_period_lookup_for_the_new_month(self, auth_client):
        """A record made when no period covered it, then edited into a month
        a period DOES cover, must pick that period up -- the same lookup
        diversion_record_create runs at save time, just run again at edit
        time (146-02 context, "Diversion records" ruling)."""
        pod = PointOfDiversionFactory()
        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )
        record = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2023, 3, 1),
            volume_acre_feet=Decimal("33.0000"), diversion_type="direct_use",
            reporting_period=None,
        )
        assert record.reporting_period_id is None

        auth_client.post(
            reverse("surface:diversion_record_edit", args=[pod.pk, record.pk]),
            {
                "month": "2024-03-01",
                "volume_acre_feet": "33",
                "returned_af": "0",
                "diversion_type": "direct_use",
            },
        )

        record.refresh_from_db()
        assert record.reporting_period_id == period.pk

    def test_invalid_edit_submit_keeps_the_row_in_edit_mode_with_the_error(self, auth_client):
        pod = PointOfDiversionFactory()
        record = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1),
            volume_acre_feet=Decimal("33.0000"), diversion_type="direct_use",
        )

        resp = auth_client.post(
            reverse("surface:diversion_record_edit", args=[pod.pk, record.pk]),
            {
                "month": "2024-03-01",
                "volume_acre_feet": "not-a-number",
                "returned_af": "0",
                "diversion_type": "direct_use",
            },
        )

        assert resp.status_code == 200
        assert "Enter a number" in resp.content.decode()
        record.refresh_from_db()
        assert record.volume_acre_feet == Decimal("33.0000"), "invalid submit must not save"


# ---------------------------------------------------------------------------
# 2. Delete
# ---------------------------------------------------------------------------


class TestDiversionRecordDelete:
    def test_delete_removes_the_row(self, auth_client):
        pod = PointOfDiversionFactory()
        record = DiversionRecordFactory(point_of_diversion=pod, month=date(2024, 3, 1))
        other = DiversionRecordFactory(point_of_diversion=pod, month=date(2024, 4, 1))

        resp = auth_client.post(
            reverse("surface:diversion_record_delete", args=[pod.pk, record.pk])
        )

        assert resp.status_code == 200
        assert not DiversionRecord.objects.filter(pk=record.pk).exists()
        assert DiversionRecord.objects.filter(pk=other.pk).exists()
        body = resp.content.decode()
        assert "Mar 2024" not in body, "the deleted row's month must not still render"
        assert "Apr 2024" in body, "the surviving row must still render"


# ---------------------------------------------------------------------------
# 3. The unique-constraint violation is a form error, never a 500
# ---------------------------------------------------------------------------


class TestDuplicateRecordIsAFormError:
    def test_create_duplicate_month_and_type_is_a_form_error_not_a_500(self, auth_client):
        pod = PointOfDiversionFactory()
        DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1),
            diversion_type="direct_use",
        )

        resp = auth_client.post(
            reverse("surface:diversion_record_create", args=[pod.pk]),
            {
                "month": "2024-03-15",  # same calendar month, different day
                "volume_acre_feet": "10",
                "returned_af": "0",
                "diversion_type": "direct_use",
            },
        )

        assert resp.status_code == 200
        assert "a record for that month and type exists" in resp.content.decode().lower()
        assert DiversionRecord.objects.filter(point_of_diversion=pod).count() == 1

    def test_edit_into_a_duplicate_month_and_type_is_a_form_error_not_a_500(self, auth_client):
        pod = PointOfDiversionFactory()
        DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1),
            diversion_type="direct_use",
        )
        movable = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 4, 1),
            diversion_type="direct_use",
        )

        resp = auth_client.post(
            reverse("surface:diversion_record_edit", args=[pod.pk, movable.pk]),
            {
                "month": "2024-03-01",
                "volume_acre_feet": "10",
                "returned_af": "0",
                "diversion_type": "direct_use",
            },
        )

        assert resp.status_code == 200
        assert "a record for that month and type exists" in resp.content.decode().lower()
        movable.refresh_from_db()
        assert movable.month == date(2024, 4, 1), "the move must not have been saved"
