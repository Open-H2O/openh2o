# SPDX-License-Identifier: AGPL-3.0-or-later
"""A point that serves no field still accounts for its water; a record keeps its day.

* Every active point with a direct-use record in the month is visited, whatever
  day the record is dated.
* A point that serves no field books what is left after its canal losses to a
  destination the canal page shows: the recharge site it feeds, or "no field".
  That water credits no one, writes no recharge event or account credit, and is
  not the water Site Health reports as undivided.
* Editing a diversion record keeps the day it was stored with, and a second
  record for the same point and month is refused whatever its day.
* The canal page's "Taken at the headgate" prints the volume taken, with what was
  returned and what was kept beneath it.

Every expected figure is a literal worked out by hand.
"""

from datetime import date
from decimal import Decimal as D

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.engine_run import _points_of_diversion, run_month
from accounting.models import AccountCredit
from recharge.models import RechargeEvent, RechargeSitePOD
from surface.forms import DiversionRecordForm
from surface.models import CanalMonthLoss, DiversionRecord, UnallocatedDelivery
from surface.services import canal_water_by_month
from tests import ledger_districts as ld
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db

JAN = date(2025, 1, 1)
FEB = date(2025, 2, 1)
JUN = date(2025, 6, 1)


def _point(name, evap="0", seep="0", spill="0"):
    return PointOfDiversionFactory(
        name=name,
        evaporation_fraction=D(evap),
        seepage_fraction=D(seep),
        spill_fraction=D(spill),
        loss_basis="measured",
    )


def _record(pod, day, af, returned="0"):
    return DiversionRecord.objects.create(
        point_of_diversion=pod,
        reporting_period=ld.period_of(day),
        month=day,
        volume_acre_feet=D(str(af)),
        returned_af=D(returned),
        diversion_type="direct_use",
    )


def _row(pod, month):
    for group in canal_water_by_month(pod):
        for row in group["rows"]:
            if row["month"] == month:
                return row
    raise AssertionError(f"no canal row for {month}")


# --------------------------------------------------------------- a point that serves no field
def test_a_point_serving_no_field_books_its_water_to_no_field():
    ld.seed_reference()
    pod = _point("Re-diversion test point")
    _record(pod, date(2025, 6, 15), 300)

    run_month("2025-06")

    stored = CanalMonthLoss.objects.get(point_of_diversion=pod, month=JUN)
    assert stored.unserved_af == D("300.0000")
    row = _row(pod, JUN)
    assert row["unserved"] == D("300.0000")
    assert row["unserved_to"] == "no field"
    assert row["adds_up"] is True
    assert UnallocatedDelivery.objects.filter(point_of_diversion=pod).count() == 0


def test_a_recharge_intake_books_what_is_left_to_its_site_in_both_months():
    ld.seed_reference()
    site = RechargeSiteFactory(name="Intake basin")
    pod = _point("Intake test point", evap="0.01", seep="0.25")
    RechargeSitePOD.objects.create(recharge_site=site, point_of_diversion=pod)
    _record(pod, date(2025, 1, 1), 100)
    _record(pod, date(2025, 2, 15), 100)
    credits_before = AccountCredit.objects.count()

    run_month("2025-01")
    run_month("2025-02")

    for month in (JAN, FEB):
        stored = CanalMonthLoss.objects.get(point_of_diversion=pod, month=month)
        assert stored.evaporation_af == D("1.0000")
        assert stored.seepage_af == D("25.0000")
        assert stored.unserved_af == D("74.0000")
        row = _row(pod, month)
        assert row["unserved_to"] == "Intake basin"
        assert row["adds_up"] is True
    assert RechargeEvent.objects.count() == 0
    assert AccountCredit.objects.count() == credits_before
    assert UnallocatedDelivery.objects.count() == 0


def test_the_engine_visits_a_point_whose_record_is_dated_the_15th():
    ld.seed_reference()
    pod = _point("Fifteenth test point")
    _record(pod, date(2025, 6, 15), 10)
    assert pod in _points_of_diversion(JUN)


def test_the_canal_page_names_the_destination_and_the_site_health_card_stays_quiet():
    ld.seed_reference()
    pod = _point("Page test point")
    _record(pod, date(2025, 6, 15), 300)
    run_month("2025-06")

    from health.checks import check_unallocated_delivery

    result = check_unallocated_delivery()
    assert "300" not in str(getattr(result, "detail", result))
    assert UnallocatedDelivery.objects.count() == 0

    html = _client().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    section = html[html.index('id="where-the-water-went"'):]
    assert "Delivered to no field" in section
    # A point that serves no field shows the destination in place of the
    # two field columns, which could only read 0.00 there.
    assert "Divided up among the other fields" not in section
    assert "300.00" in section


# --------------------------------------------------------------- the day a record keeps
def _client():
    from core.models import User

    user = User.objects.create(
        username="unservedreader",
        email="unservedreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def test_editing_only_the_volume_keeps_the_stored_day():
    ReportingPeriodFactory(start_date=date(2024, 10, 1), end_date=date(2025, 9, 30))
    pod = PointOfDiversionFactory()
    record = DiversionRecordFactory(
        point_of_diversion=pod, month=date(2025, 3, 15),
        volume_acre_feet=D("33.0000"), diversion_type="direct_use",
    )
    resp = _client().post(
        reverse("surface:diversion_record_edit", args=[pod.pk, record.pk]),
        {
            "month": "2025-03-15",
            "volume_acre_feet": "40",
            "returned_af": "0",
            "diversion_type": "direct_use",
        },
    )
    assert resp.status_code == 200
    record.refresh_from_db()
    assert record.volume_acre_feet == D("40.0000")
    assert record.month == date(2025, 3, 15)


def test_a_second_record_for_the_same_point_and_month_is_refused_whatever_its_day():
    pod = PointOfDiversionFactory()
    DiversionRecordFactory(
        point_of_diversion=pod, month=date(2025, 3, 15),
        volume_acre_feet=D("33.0000"), diversion_type="direct_use",
    )
    data = {
        "month": "2025-03-01",
        "volume_acre_feet": "5",
        "returned_af": "0",
        "diversion_type": "direct_use",
    }
    form = DiversionRecordForm(data, pod=pod)
    assert not form.is_valid()
    assert "month" in form.errors

    resp = _client().post(reverse("surface:diversion_record_create", args=[pod.pk]), data)
    assert resp.status_code == 200
    assert DiversionRecord.objects.filter(point_of_diversion=pod).count() == 1


# --------------------------------------------------------------- the headgate
def test_the_headgate_prints_taken_then_returned_then_kept():
    ld.seed_reference()
    pod = _point("Headgate test point")
    _record(pod, date(2025, 6, 1), 100, returned="40")
    run_month("2025-06")

    row = _row(pod, JUN)
    assert row["taken"] == D("100.0000")
    assert row["returned"] == D("40.0000")
    assert row["headgate"] == D("60.0000")

    html = _client().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    section = html[html.index('id="where-the-water-went"'):]
    assert "100.00" in section
    assert "40.00 returned, 60.00 kept" in section
