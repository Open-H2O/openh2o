# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-02 Task 3, ISS-181: a diversion record gets its water year only at
creation; a period made LATER never attached it, and the product's own fix
instruction ("Re-save them") named a control the record page did not have.

``accounting.services.attach_orphans_to_period`` closes the gap: every
DiversionRecord, UnallocatedDelivery and ParcelLedger row with
``reporting_period IS NULL`` and a date inside the new period's dates is
attached the moment the period is saved. Proven here, each RED against the
unfixed tree (the exact quotes live in 146-02-EVIDENCE.md):

  1. The service itself: idempotent, one count per model, only touches rows
     genuinely inside the period's dates and genuinely orphaned.
  2. ``accounting:period_create`` calls it and reports the counts once, in
     the page's success message.
  3. The shape-1 scenario named in the plan: seven 2024 monthly records (the
     dataset's own shape-1 values, Mar-Sep) entered with no period on
     record, then a period made THROUGH THE VIEW -- all seven attach and the
     POD page's lead panel reads the state's exact 2024 figure, 2,045.00 AF.
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.models import ReportingPeriod
from accounting.services import attach_orphans_to_period
from surface.models import DiversionRecord, UnallocatedDelivery
from tests.factories import (
    DiversionRecordFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"attachuser{n}")
    email = factory.Sequence(lambda n: f"attachuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. The service function
# ---------------------------------------------------------------------------


class TestAttachOrphansToPeriodService:
    def test_attaches_diversion_records_inside_the_period(self):
        pod = PointOfDiversionFactory()
        inside = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 6, 1), reporting_period=None,
        )
        outside = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2025, 6, 1), reporting_period=None,
        )
        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

        counts = attach_orphans_to_period(period)

        assert counts["diversion_records"] == 1
        inside.refresh_from_db()
        outside.refresh_from_db()
        assert inside.reporting_period_id == period.pk
        assert outside.reporting_period_id is None

    def test_attaches_unallocated_deliveries_inside_the_period(self):
        pod = PointOfDiversionFactory()
        UnallocatedDelivery.objects.create(
            point_of_diversion=pod, month=date(2024, 6, 1),
            amount_acre_feet=Decimal("5.0000"), delivery_acre_feet=Decimal("50.0000"),
        )
        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

        counts = attach_orphans_to_period(period)

        assert counts["unallocated_deliveries"] == 1
        row = UnallocatedDelivery.objects.get(point_of_diversion=pod)
        assert row.reporting_period_id == period.pk

    def test_attaches_ledger_rows_inside_the_period(self):
        row = ParcelLedgerFactory(
            effective_date=date(2024, 6, 15), reporting_period=None,
        )
        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

        counts = attach_orphans_to_period(period)

        assert counts["ledger_rows"] == 1
        row.refresh_from_db()
        assert row.reporting_period_id == period.pk

    def test_never_reassigns_a_row_that_already_has_a_period(self):
        pod = PointOfDiversionFactory()
        already = ReportingPeriodFactory(
            start_date=date(2023, 1, 1), end_date=date(2023, 12, 31)
        )
        record = DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 6, 1),
            reporting_period=already,
        )
        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

        counts = attach_orphans_to_period(period)

        assert counts["diversion_records"] == 0
        record.refresh_from_db()
        assert record.reporting_period_id == already.pk

    def test_idempotent_second_call_is_a_no_op(self):
        pod = PointOfDiversionFactory()
        DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 6, 1), reporting_period=None,
        )
        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )

        first = attach_orphans_to_period(period)
        second = attach_orphans_to_period(period)

        assert first["diversion_records"] == 1
        assert second["diversion_records"] == 0


# ---------------------------------------------------------------------------
# 2. period_create reports the counts
# ---------------------------------------------------------------------------


class TestPeriodCreateAttachesAndReports:
    def test_creating_a_period_through_the_view_attaches_and_reports_counts(self, auth_client):
        pod = PointOfDiversionFactory()
        DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 3, 1), reporting_period=None,
        )
        DiversionRecordFactory(
            point_of_diversion=pod, month=date(2024, 4, 1), reporting_period=None,
        )
        ParcelLedgerFactory(effective_date=date(2024, 5, 1), reporting_period=None)

        resp = auth_client.post(
            reverse("accounting:period_create"),
            {
                "name": "Report year 2024",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
            follow=True,
        )

        assert resp.status_code == 200
        body = resp.content.decode()
        assert "2 diversion records" in body
        assert "1 ledger rows attached" in body
        assert DiversionRecord.objects.filter(reporting_period__isnull=True).count() == 0


# ---------------------------------------------------------------------------
# 3. The shape-1 scenario: seven 2024 records, entered with no period, then
#    a period made through the view -- the state's exact 2024 figure files.
# ---------------------------------------------------------------------------


SHAPE_1_2024_MONTHS = [
    (date(2024, 3, 1), Decimal("33")),
    (date(2024, 4, 1), Decimal("51")),
    (date(2024, 5, 1), Decimal("156")),
    (date(2024, 6, 1), Decimal("393")),
    (date(2024, 7, 1), Decimal("490")),
    (date(2024, 8, 1), Decimal("473")),
    (date(2024, 9, 1), Decimal("449")),
]


def _budget_panel(html):
    start = html.index('class="budget-panel"')
    return html[start:start + 2000]


class TestShape1SevenMonthsThenAPeriod:
    def test_seven_records_with_no_period_read_2045_once_the_year_is_saved(self, auth_client):
        pod = PointOfDiversionFactory()
        for month, volume in SHAPE_1_2024_MONTHS:
            DiversionRecordFactory(
                point_of_diversion=pod, month=month, volume_acre_feet=volume,
                diversion_type="direct_use", reporting_period=None,
            )
        assert DiversionRecord.objects.filter(
            point_of_diversion=pod, reporting_period__isnull=True
        ).count() == 7

        # Before any period exists: no water year on record, and the
        # "No water year assigned" group carries the full total -- exactly
        # the ISS-181 shape (also proven directly in test_diversion_record_edit
        # and the _detail_pane fix: no bare "Diverted less returned, .").
        before = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
        assert "Diverted less returned, ." not in before, "the bare trailing comma is the ISS-181 defect"
        assert "Diverted less returned." in before
        assert "No water year assigned" in before

        resp = auth_client.post(
            reverse("accounting:period_create"),
            {
                "name": "Report year 2024",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )
        assert resp.status_code == 302
        period = ReportingPeriod.objects.get(name="Report year 2024")

        for month, _ in SHAPE_1_2024_MONTHS:
            record = DiversionRecord.objects.get(point_of_diversion=pod, month=month)
            assert record.reporting_period_id == period.pk

        after = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
        assert "No water year assigned" not in after
        panel = _budget_panel(after)
        assert "2,045.00" in panel, "33+51+156+393+490+473+449 AF must read as one figure"
        assert "Report year 2024" in after
