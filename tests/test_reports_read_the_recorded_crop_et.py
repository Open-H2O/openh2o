# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GEARS by-ET report, its checks and the OpenET pre-fill read the recorded crop ET.

Each month's crop ET is recorded once (``datasync.models.CropETFigure``). The by-ET file, the
three pre-fill builders and the by-ET acreage check read that record, converted to acre-feet
with the use area's acres and rounded to four places.

**Every number in this file is made up.** The use areas, wells, points of diversion and depths
are invented for the arithmetic. At 80.00 acres a depth of 38.1 mm is exactly 10 acre-feet
(38.1 / 304.8 x 80), so every figure below is exact.
"""

import csv
import io
import re
from datetime import date
from decimal import Decimal as D

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from accounting.models import ReportingPeriod
from datasync.models import CropETFigure
from parcels.models import Parcel, ParcelLedger
from reporting.generators import generate_gears_csv
from reporting.models import ReportSubmission, ReportTemplate
from reporting.services import build_openet_prefill
from reporting.validators import validate_report
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db

JAN, FEB, MAR = date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)
MM_PER_AF_AT_80_ACRES = D("3.81")  # 304.8 / 80


def _record(parcel, month, af):
    """The month's recorded crop ET, as a depth that is ``af`` acre-feet over 80 acres."""
    return CropETFigure.objects.create(
        parcel=parcel, month=month, variable="ET", model_name="Ensemble",
        depth_mm=D(af) * MM_PER_AF_AT_80_ACRES, fetched_on=month,
    )


def _by_et(period):
    """The by-ET file's lines after its header, as tuples."""
    rows = list(csv.reader(io.StringIO(generate_gears_csv(period, "by_et").getvalue())))
    return [tuple(r) for r in rows[1:]]


def _prefill(period, method):
    """``{(entity label, "YYYY-MM"): acre-feet}`` from a pre-fill builder."""
    return {
        (entity["entity_label"], mv["month"]): mv["value_af"]
        for entity in build_openet_prefill(period, method)["entities"]
        for mv in entity["months"]
    }


@pytest.fixture
def period():
    return ReportingPeriodFactory()


def test_a_recorded_month_with_no_calculation_is_left_out_of_the_by_et_file_and_counted(period):
    """The by-ET file writes each well's extraction estimate, which only a calculation makes."""
    from reporting.generators import _gears_by_et_build

    a = ParcelFactory(parcel_number="MADEUP-A")
    b = ParcelFactory(parcel_number="MADEUP-B")
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="MADEUP-REG"), parcel=a)
    _record(a, JAN, "10")
    _record(a, FEB, "2.5")
    _record(b, JAN, "7.25")
    assert not ParcelLedger.objects.exists()

    rows, left_out = _gears_by_et_build(period)
    assert rows == []
    assert left_out.not_calculated == {JAN: {a.pk}, FEB: {a.pk}}
    assert left_out.no_well == {b.pk}


def test_the_three_pre_fill_builders_read_the_record(period):
    a = ParcelFactory(parcel_number="MADEUP-A")
    _record(a, JAN, "10")
    _record(a, FEB, "2.5")
    well = WellFactory(name="MADEUP-WELL")
    WellIrrigatedParcelFactory(well=well, parcel=a, fraction=D("1.0000"))
    pod = PointOfDiversionFactory(name="MADEUP-POD")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=D("1.0000"))

    assert _prefill(period, "by_parcel") == {("MADEUP-A", "2024-01"): D("10"), ("MADEUP-A", "2024-02"): D("2.5")}
    by_well = build_openet_prefill(period, "by_well")["entities"]
    assert [[mv["value_af"] for mv in e["months"]] for e in by_well] == [[D("10"), D("2.5")]]
    calwatrs = build_openet_prefill(period, "calwatrs")["entities"]
    assert [[mv["value_af"] for mv in e["months"]] for e in calwatrs] == [[D("10"), D("2.5")]]


def test_a_calculated_month_is_written_and_a_metered_month_left_to_the_by_well_file(period):
    a = ParcelFactory(parcel_number="MADEUP-A")
    well = WellFactory(well_registration_id="MADEUP-REG", name="MADEUP-WELL")
    WellIrrigatedParcelFactory(well=well, parcel=a)
    _record(a, JAN, "10")
    _record(a, FEB, "2.5")
    _record(a, MAR, "4")
    ParcelLedgerFactory(
        parcel=a, source_type="calculated", amount_acre_feet=D("-6.1234"),
        effective_date=JAN, transaction_date=JAN, reporting_period=period,
    )
    ParcelLedgerFactory(
        parcel=a, source_type="meter_reading", amount_acre_feet=D("-3"),
        effective_date=date(2024, 2, 14), transaction_date=date(2024, 2, 14), reporting_period=period,
    )

    # January has no run with an extraction estimate, so it counts at the row's own
    # figure, as the account pages count it; March has no calculation and is left out.
    assert [(line[0], line[4], line[5]) for line in _by_et(period)] == [("MADEUP-REG", "2024-01", "6.1234")]


def test_a_finalized_years_file_is_full(period):
    a = ParcelFactory(parcel_number="MADEUP-A")
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="MADEUP-REG"), parcel=a)
    for month in (JAN, FEB, MAR):
        _record(a, month, "1")
        ParcelLedgerFactory(
            parcel=a, source_type="calculated", amount_acre_feet=D("-1"),
            effective_date=month, transaction_date=month, reporting_period=period,
        )
    ReportingPeriod.objects.filter(pk=period.pk).update(is_finalized=True)
    period.refresh_from_db()

    assert [line[4] for line in _by_et(period)] == ["2024-01", "2024-02", "2024-03"]


def test_the_ledger_copy_is_not_a_command():
    with pytest.raises(CommandError, match="Unknown command"):
        call_command("sync_openet_to_ledger", "--start-date", "2024-01-01", "--end-date", "2024-01-31")


def test_the_openet_sync_refuses_the_to_ledger_switch():
    with pytest.raises(CommandError, match="unrecognized arguments: --to-ledger"):
        call_command(
            "sync_openet_parcels", "--start-date", "2024-01-01", "--end-date", "2024-01-31",
            "--dry-run", "--to-ledger",
        )


def test_the_acreage_check_names_a_use_area_with_a_record_and_no_acres(period):
    acreless = ParcelFactory(parcel_number="MADEUP-NOACRES")
    Parcel.objects.filter(pk=acreless.pk).update(area_acres=None)  # a save works acres out from the outline
    _record(acreless, JAN, "1")

    assert _by_et(period) == []

    messages = " ".join(w["message"] for w in validate_report(period, "gears_by_et"))
    assert "MADEUP-NOACRES" in messages


def _submission(report_type, period):
    template, _ = ReportTemplate.objects.get_or_create(
        report_type=report_type, defaults={"name": report_type, "is_active": True}
    )
    return ReportSubmission.objects.create(report_template=template, reporting_period=period, status="draft")


def test_the_by_et_pre_fill_page_shows_a_box_for_each_recorded_month(client, django_user_model, period):
    a = ParcelFactory(parcel_number="MADEUP-A")
    _record(a, JAN, "10")
    _record(a, FEB, "2.5")
    submission = _submission("gears_by_et", period)
    client.force_login(django_user_model.objects.create_user(username="office", password="x"))

    html = client.get(reverse("reporting:report_prefill", kwargs={"pk": submission.pk})).content.decode()

    assert re.findall(r'name="val:(parcel:\d+:\d{4}-\d{2})"', html) == [
        f"parcel:{a.pk}:2024-01", f"parcel:{a.pk}:2024-02",
    ]
