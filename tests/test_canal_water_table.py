# SPDX-License-Identifier: AGPL-3.0-or-later
"""149-02 Task 2b: each canal's page shows, month by month, where its water went.

The table reads stored rows only (``CanalMonthLoss``, the split's own ledger
rows, ``UnallocatedDelivery``) through ``surface.services.canal_water_by_month``.
The data here is built by running ``allocate_district_delivery`` on a fixture
rather than by hand-writing the stored rows, and every expected figure is a
literal worked out by hand.

Worked example (the canal of tests/test_canal_losses.py): 100 AF diverted, 5 AF
returned, so 95.0000 AF at the headgate. Shares 0.01 / 0.12 / 0.02 take
0.9500 + 11.4000 + 1.9000 = 14.2500 AF, which leaves 80.7500 AF.
  * Field A recorded 20 AF at its own gate: 80.75 - 20 = 60.75 AF for B and C,
    divided by crop water use 30 : 60, which is 20.25 and 40.50 (the caps, 40 and
    80, are above the 60.75 so all of it is handed out): 95 = 14.25 + 20 + 60.75 + 0.
  * Ample month (demand 15 each, caps 20.0000 each): 60 AF used, 20.75 AF beyond
    what the crops could use: 95 = 14.25 + 0 + 60 + 20.75.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun, ReportingPeriod
from health.models import HealthCheckResult
from surface.models import DiversionRecord
from surface.services import allocate_district_delivery, canal_water_by_month
from tests.factories import (
    DiversionRecordFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
)
from tests.test_canal_losses import EFF, JAN, _canal

pytestmark = pytest.mark.django_db

FEB = date(2024, 2, 1)
MAR = date(2024, 3, 1)


def _own(parcel, amount, month=JAN):
    return ParcelLedgerFactory(
        parcel=parcel,
        effective_date=month,
        source_type="surface_diversion",
        amount_acre_feet=Decimal(str(amount)),
        description="Reading at the field turnout",
    )


def _rows(pod):
    groups = canal_water_by_month(pod)
    assert len(groups) == 1
    return groups[0]


def _login():
    from core.models import User

    user = User.objects.create(
        username="canalreader",
        email="canalreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _section(html):
    start = html.index('id="where-the-water-went"')
    return html[start : html.index("Linked use areas", start)]


# (a) one canal, three fields, one with its own record -------------------------


def test_each_cell_is_the_stored_figure_and_the_row_adds_up():
    rp, pod, (a, b, c) = _canal()
    _own(a, "-20")
    allocate_district_delivery(pod, rp, efficiency=EFF)

    group = _rows(pod)
    assert group["name"] == rp.name
    (row,) = group["rows"]
    assert row["month"] == JAN
    assert row["headgate"] == Decimal("95.0000")
    assert row["evaporation"] == Decimal("0.9500")
    assert row["seepage"] == Decimal("11.4000")
    assert row["spill"] == Decimal("1.9000")
    assert row["losses"] == Decimal("14.2500")
    assert row["own"] == Decimal("20.0000")
    assert row["divided"] == Decimal("60.7500")
    assert row["beyond"] == Decimal("0")
    assert row["calculated"] is True
    assert row["estimated"] is False
    assert row["adds_up"] is True
    assert (
        row["losses"] + row["own"] + row["divided"] + row["beyond"]
        == row["headgate"]
    )


def test_the_totals_row_sums_the_period():
    rp, pod, (a, b, c) = _canal()
    _own(a, "-20")
    allocate_district_delivery(pod, rp, efficiency=EFF)

    totals = _rows(pod)["totals"]
    assert totals["count"] == 1
    assert totals["headgate"] == Decimal("95.0000")
    assert totals["losses"] == Decimal("14.2500")
    assert totals["own"] == Decimal("20.0000")
    assert totals["divided"] == Decimal("60.7500")
    assert totals["beyond"] == Decimal("0")
    assert totals["adds_up"] is True
    assert totals["uncalculated"] == 0


# (b) an ample month ------------------------------------------------------------


def test_an_ample_month_shows_its_leftover_beyond_what_the_crops_could_use():
    rp, pod, fields = _canal(demands=(15, 15, 15))
    allocate_district_delivery(pod, rp, efficiency=EFF)

    (row,) = _rows(pod)["rows"]
    assert row["divided"] == Decimal("60.0000")
    assert row["beyond"] == Decimal("20.7500")
    assert row["own"] == Decimal("0.0000")
    assert row["adds_up"] is True
    assert row["headgate"] == Decimal("95.0000")


# (c) which months are rows -------------------------------------------------------


def test_a_month_with_no_record_is_absent_and_to_storage_makes_no_row():
    rp, pod, fields = _canal()
    # February has only a to-storage record; March has nothing at all.
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=rp,
        month=FEB,
        volume_acre_feet=Decimal("40"),
        diversion_type="to_storage",
    )
    allocate_district_delivery(pod, rp, efficiency=EFF)

    months = [r["month"] for r in _rows(pod)["rows"]]
    assert months == [JAN]
    assert MAR not in months
    assert FEB not in months


def test_a_canal_with_no_direct_use_record_has_no_tables():
    pod = PointOfDiversionFactory()
    assert canal_water_by_month(pod) == []


def test_a_month_not_yet_calculated_shows_its_consumed_total_and_invents_no_losses():
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=rp,
        month=JAN,
        volume_acre_feet=Decimal("30"),
        returned_af=Decimal("10"),
    )

    group = _rows(pod)
    (row,) = group["rows"]
    assert row["calculated"] is False
    assert row["headgate"] == Decimal("20.0000")
    assert row["evaporation"] is None
    assert row["losses"] is None
    assert row["divided"] is None
    assert row["beyond"] is None
    assert group["totals"]["uncalculated"] == 1
    assert group["totals"]["headgate"] == Decimal("20.0000")


# (d) the estimated flag ----------------------------------------------------------


def test_a_month_with_an_estimated_record_carries_the_estimated_flag():
    rp, pod, (a, b, c) = _canal()
    DiversionRecord.objects.create(
        point_of_diversion=pod,
        reporting_period=rp,
        month=FEB,
        volume_acre_feet=Decimal("10"),
        diversion_type="direct_use",
        method="estimated_from_use",
        data_state="provisional",
    )
    for parcel in (a, b, c):
        CalculationRun.objects.create(
            parcel=parcel,
            period="2024-02",
            gross_et_af=Decimal("10"),
            net_consumptive_use_af=Decimal("10"),
            final_af=Decimal("0"),
        )
    allocate_district_delivery(pod, rp, efficiency=EFF)

    by_month = {r["month"]: r for r in _rows(pod)["rows"]}
    assert set(by_month) == {JAN, FEB}
    assert by_month[JAN]["estimated"] is False
    assert by_month[FEB]["estimated"] is True
    assert by_month[FEB]["adds_up"] is True
    assert _rows(pod)["totals"]["estimated"] is True


# (e) reporting periods, newest first ----------------------------------------------


def test_periods_are_grouped_newest_first_and_the_open_one_is_expanded():
    prior = ReportingPeriodFactory(
        name="WY 2023-2024",
        start_date=date(2023, 10, 1),
        end_date=date(2024, 9, 30),
    )
    current = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
    )
    pod = PointOfDiversionFactory()
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=prior, month=JAN,
        volume_acre_feet=Decimal("10"),
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=current, month=date(2024, 11, 1),
        volume_acre_feet=Decimal("12"),
    )

    # Finalized after its record is in: the database refuses a record written
    # into a finalized year.
    ReportingPeriod.objects.filter(pk=prior.pk).update(is_finalized=True)

    groups = canal_water_by_month(pod)
    assert [g["name"] for g in groups] == ["WY 2024-2025", "WY 2023-2024"]
    assert [g["is_open"] for g in groups] == [True, False]


# (f) the rendered page --------------------------------------------------------------


def test_the_page_shows_the_headings_and_the_totals():
    rp, pod, (a, b, c) = _canal(demands=(15, 15, 15))
    DiversionRecord.objects.create(
        point_of_diversion=pod,
        reporting_period=rp,
        month=FEB,
        volume_acre_feet=Decimal("10"),
        diversion_type="direct_use",
        method="estimated_from_use",
    )
    allocate_district_delivery(pod, rp, efficiency=EFF)

    html = _login().get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    section = _section(html)

    for heading in (
        "Where the water went",
        "Taken at the headgate",
        "Canal losses",
        "Evaporation",
        "Seepage",
        "Spill",
        "Fields' own records",
        "Divided up among the other fields",
        "Beyond what the crops could use",
    ):
        assert heading in section, heading
    assert "All 2 months" in section
    assert "<details" in section and " open" in section
    assert "95.00" in section  # January's headgate figure
    assert "20.75" in section  # January's leftover
    assert "Estimated" in section  # February's estimated record
    assert "nallocated" not in section
    assert "POD" not in section


# (g) Site Health -----------------------------------------------------------------------


def test_site_health_links_to_the_canal_with_the_most_leftover_water():
    from surface.models import UnallocatedDelivery

    rp = ReportingPeriodFactory()
    small = PointOfDiversionFactory(name="Small Leftover Canal")
    big = PointOfDiversionFactory(name="Big Leftover Canal")
    for pod, amount in ((small, "3.0000"), (big, "20.7500")):
        UnallocatedDelivery.objects.create(
            point_of_diversion=pod,
            reporting_period=rp,
            month=JAN,
            amount_acre_feet=Decimal(amount),
            delivery_acre_feet=Decimal("80.0000"),
        )
    HealthCheckResult.objects.create(
        category="unallocated_delivery",
        status="yellow",
        message="23.75 AF delivered is not explained by crop demand",
        details={},
    )

    response = _login().get(reverse("health:dashboard"))
    card = next(r for r in response.context["results"] if r.category == "unallocated_delivery")

    assert card.where["href"] == (
        reverse("surface:pod_detail", args=[big.pk]) + "#where-the-water-went"
    )
    assert "Big Leftover Canal" in card.where["label"]


def test_site_health_keeps_the_diversions_link_when_there_is_no_leftover_water():
    HealthCheckResult.objects.create(
        category="unallocated_delivery",
        status="yellow",
        message="check",
        details={},
    )

    response = _login().get(reverse("health:dashboard"))
    card = next(r for r in response.context["results"] if r.category == "unallocated_delivery")

    assert card.where["href"] == reverse("surface:pod_list")
