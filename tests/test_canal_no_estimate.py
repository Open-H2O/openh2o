# SPDX-License-Identifier: AGPL-3.0-or-later
"""No meter reading and no entered delivery means no canal water.

OpenH2O no longer makes up a canal delivery for a point of diversion from the
crop need of the fields it serves. A point with no measuring device in service
and no volume a person typed for a month writes no diversion record, and each
field it serves shows 0 AF of canal delivery for that month. Because the old
estimate was never subtracted from a field's groundwater, no charge moves.

Also here: the importer's "rows combined into one month" count, and the
Finalized word that replaces Edit and Delete on a record in a finalized year.

Every expected figure is a literal worked by hand.
"""

import datetime as dt
from decimal import Decimal as D
from importlib import import_module

import pytest
from django.apps import apps
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun, ReportingPeriod
from core.models import User
from parcels.models import ParcelLedger
from surface import diversion_import
from surface.models import DiversionRecord

from . import ledger_districts as ld
from .factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def ref():
    ld.seed_reference()


def _reader():
    client = Client()
    client.force_login(User.objects.create_user(username="reader", password="x", is_active=True))
    return client


def _two_fields(with_point):
    """Two well fields with no meter; optionally both on one point that has no record.

    X1: 100 acres, 26.99522 mm in July 2025 -> 100 x 26.99522 / 304.8 = 8.8567 AF of crop use.
    X2: 50 acres, 30 mm -> 50 x 30 / 304.8 = 4.9213 AF.
    Both at the default efficiency of 0.75: 8.8567 / 0.75 = 11.8089 and 4.9213 / 0.75 = 6.5617.
    """
    well1 = ld.make_well("W1", -120.55, 37.2)
    well2 = ld.make_well("W2", -120.45, 37.2)
    f1 = ld.add_field("X1", 100, "Alfalfa", None, [], -120.55, 37.2, [{"2025-07": "26.99522"}], well1)
    f2 = ld.add_field("X2", 50, "Alfalfa", None, [], -120.45, 37.2, [{"2025-07": "30"}], well2)
    point = None
    if with_point:
        point = ld.make_point("Unmetered headgate", -120.5, 37.15, None, "0.01", "0.12", "0.02", [(f1, "0.5"), (f2, "0.5")])
    return f1, f2, point


def _pumped(parcel):
    return CalculationRun.objects.get(parcel=parcel, period="2025-07").gw_extracted_af


# ------------------------------------------------------------------ row 1


def test_a_point_with_no_device_and_no_typed_volume_writes_no_record_and_delivers_nothing(ref):
    f1, f2, point = _two_fields(with_point=True)
    ld.run_months(["2025-07"])
    assert DiversionRecord.objects.filter(point_of_diversion=point).count() == 0
    for field in (f1, f2):
        delivered = ParcelLedger.objects.filter(parcel=field, source_type="surface_diversion")
        assert sum((abs(r.amount_acre_feet) for r in delivered), D("0")) == D("0")


@pytest.mark.parametrize("with_point", [True, False])
def test_the_groundwater_charge_is_the_same_with_the_unmetered_point_as_without_it(ref, with_point):
    f1, f2, _ = _two_fields(with_point=with_point)
    ld.run_months(["2025-07"])
    assert _pumped(f1) == D("11.8089")
    assert _pumped(f2) == D("6.5617")


def test_a_typed_delivery_still_comes_off_the_charge(ref):
    # 4 AF typed at a lossless point x 0.75 = 3.0000 AF used; (8.8567 - 3.0000) / 0.75 = 7.8089
    well = ld.make_well("WX", -120.55, 37.2)
    field = ld.add_field("X1", 100, "Alfalfa", None, [], -120.55, 37.2, [{"2025-07": "26.99522"}], well)
    point = ld.make_point("Typed headgate", -120.5, 37.15, None, "0", "0", "0", [(field, "1")])
    ld.typed_record(point, ld.JUL, "4.0000")
    ld.run_months(["2025-07"])
    assert _pumped(field) == D("7.8089")


def test_an_old_estimate_in_an_open_month_is_gone_after_the_month_runs_and_a_finalized_one_stays(ref):
    _, _, point = _two_fields(with_point=True)

    def estimate(month):
        return DiversionRecord.objects.create(
            point_of_diversion=point, month=month, volume_acre_feet=D("20.0000"),
            diversion_type="direct_use", method="estimated_from_use", data_state="provisional",
            reporting_period=ld.period_of(month),
        )

    open_month = estimate(dt.date(2025, 7, 1))
    other_open_month = estimate(dt.date(2025, 8, 1))
    finalized_month = estimate(dt.date(2025, 11, 1))
    ReportingPeriod.objects.filter(name="WY 2025-2026").update(is_finalized=True)

    ld.run_months(["2025-07"])

    assert not DiversionRecord.objects.filter(pk=open_month.pk).exists()
    assert DiversionRecord.objects.filter(pk=other_open_month.pk).exists()  # that month has not run
    assert DiversionRecord.objects.filter(pk=finalized_month.pk).exists()


def test_the_field_page_says_no_canal_delivery_is_recorded_and_never_says_estimated(ref):
    f1, _, _ = _two_fields(with_point=True)
    ld.run_months(["2025-07"])
    body = _reader().get(reverse("parcels:detail", args=[f1.pk])).content.decode()
    assert "No canal delivery is recorded for this use area." in body
    assert "AF estimated" not in body


def test_a_field_with_no_point_does_not_get_the_canal_sentence(ref):
    f1, _, _ = _two_fields(with_point=False)
    ld.run_months(["2025-07"])
    body = _reader().get(reverse("parcels:detail", args=[f1.pk])).content.decode()
    assert "No canal delivery is recorded" not in body


def _migration():
    return import_module("surface.migrations.0035_remove_canal_estimates")


def test_the_migration_deletes_open_year_estimates_and_leaves_a_finalized_years_alone(ref):
    f1, _, point = _two_fields(with_point=True)
    open_estimate = DiversionRecord.objects.create(
        point_of_diversion=point, month=dt.date(2025, 11, 1), volume_acre_feet=D("20.0000"),
        diversion_type="direct_use", method="estimated_from_use", data_state="provisional",
        reporting_period=ld.period_of(dt.date(2025, 11, 1)),
    )
    closed_estimate = DiversionRecord.objects.create(
        point_of_diversion=point, month=dt.date(2025, 1, 1), volume_acre_feet=D("30.0000"),
        diversion_type="direct_use", method="estimated_from_use", data_state="provisional",
        reporting_period=ld.period_of(dt.date(2025, 1, 1)),
    )
    typed = DiversionRecord.objects.create(
        point_of_diversion=point, month=dt.date(2025, 12, 1), volume_acre_feet=D("40.0000"),
        diversion_type="direct_use", method="", data_state="provisional",
        reporting_period=ld.period_of(dt.date(2025, 12, 1)),
    )
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)

    _migration().remove_open_year_estimates(apps, None)

    assert not DiversionRecord.objects.filter(pk=open_estimate.pk).exists()
    assert DiversionRecord.objects.filter(pk=closed_estimate.pk).exists()
    assert DiversionRecord.objects.filter(pk=typed.pk).exists()


# ------------------------------------------------------------------ row 11

_USE_CSV = (
    "APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT,calendar_month\n"
    "A100001,2024,6,DIRECT,100,2024-06\n"
    "A100001,2024,6,USE,130,2024-06\n"
)


def _use_rule_import(rule):
    from .factories import WaterRightFactory

    right = WaterRightFactory(right_id="A100001")
    PointOfDiversionFactory(water_right=right, status="active")
    import io

    columns, rows = diversion_import.parse_csv(io.StringIO(_USE_CSV))
    return diversion_import.import_diversion_rows(columns, rows, use_rule=rule, dry_run=True)


def test_a_use_row_folded_in_as_returned_water_is_not_counted_as_combined():
    result = _use_rule_import("returned")
    assert result["combined_rows"] == []


def test_a_use_row_added_as_direct_water_is_counted_as_combined():
    result = _use_rule_import("as_direct")
    assert [(c["row_count"], c["rows"]) for c in result["combined_rows"]] == [(2, [2, 3])]


# ------------------------------------------------------------------ row 12


def _record_page(pod):
    return _reader().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()


def _records_in(open_year, closed_year):
    pod = PointOfDiversionFactory()
    closed = ReportingPeriodFactory(name="WY 2023-2024", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30))
    opened = ReportingPeriodFactory(name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30))
    old = DiversionRecordFactory(point_of_diversion=pod, month=dt.date(2024, 3, 1), reporting_period=closed)
    new = DiversionRecordFactory(point_of_diversion=pod, month=dt.date(2025, 3, 1), reporting_period=opened)
    ReportingPeriod.objects.filter(pk=closed.pk).update(is_finalized=True)
    return pod, old, new


def test_a_record_in_a_finalized_year_reads_finalized_with_no_edit_or_delete():
    pod, old, new = _records_in(None, None)
    body = _record_page(pod)
    assert reverse("surface:diversion_record_edit", args=[pod.pk, old.pk]) not in body
    assert reverse("surface:diversion_record_delete", args=[pod.pk, old.pk]) not in body
    assert "Finalized" in body


def test_a_record_in_an_open_year_keeps_edit_and_delete():
    pod, old, new = _records_in(None, None)
    body = _record_page(pod)
    assert reverse("surface:diversion_record_edit", args=[pod.pk, new.pk]) in body
    assert reverse("surface:diversion_record_delete", args=[pod.pk, new.pk]) in body


def test_a_use_area_assignment_in_a_finalized_year_has_no_remove_control():
    account = WaterAccountFactory()
    closed = ReportingPeriodFactory(name="WY 2023-2024", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30))
    opened = ReportingPeriodFactory(name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30))
    old = WaterAccountParcelFactory(water_account=account, parcel=ParcelFactory(parcel_number="OLD-1"), reporting_period=closed)
    new = WaterAccountParcelFactory(water_account=account, parcel=ParcelFactory(parcel_number="NEW-1"), reporting_period=opened)
    ReportingPeriod.objects.filter(pk=closed.pk).update(is_finalized=True)
    body = _reader().get(reverse("accounting:account_detail", args=[account.pk])).content.decode()
    assert reverse("accounting:remove_parcel", args=[account.pk, old.pk]) not in body
    assert reverse("accounting:remove_parcel", args=[account.pk, new.pk]) in body
    assert "Finalized" in body


# ------------------------------------------------- a stored record of the old estimate


def test_the_calwatrs_worksheet_still_marks_a_stored_estimated_month():
    """A finalized year may hold a record of the retired estimate; it is never shown as a measurement."""
    from tests.factories import ReportSubmissionFactory

    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    DiversionRecord.objects.create(
        point_of_diversion=pod, reporting_period=rp, month=dt.date(2024, 1, 1),
        volume_acre_feet=D("12.5000"), diversion_type="direct_use",
        method="estimated_from_use", data_state="provisional",
    )
    submission = ReportSubmissionFactory(reporting_period=rp)
    html = _reader().get(reverse("reporting:calwatrs_worksheet", args=[submission.pk])).content.decode()
    assert "12.50" in html
    assert "Estimated</span>" in html


def test_no_diversion_form_offers_the_retired_method():
    assert "estimated_from_use" not in dict(DiversionRecord.OFFERED_METHOD_CHOICES)
    from surface.forms import DiversionRecordForm

    assert "estimated_from_use" not in dict(DiversionRecordForm().fields["method"].choices)
