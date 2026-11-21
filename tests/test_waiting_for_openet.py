# SPDX-License-Identifier: AGPL-3.0-or-later
"""A month OpenET has not sent crop ET for is waiting, and one rule covers it everywhere.

Ruling 211: a waiting month's measured water (a well's meter shares, canal water split by the
shares the district set) reaches the field the night it is entered and counts against the
allocation at once. Canal water split by crop need waits with the month. The balance leaves the
waiting month out whole and says what it covers. Ruling 212 approved the words.

The site: one water year, October 2025 to September 2026, read on October 3, 2026 (the day the
site thinks it is, ``crop_et.today``). Two use areas, WAIT-1 and WAIT-2, each inside its own
OpenET field, with crop ET for October 2025 to August 2026 and none for September 2026. Well W
waters WAIT-1 and its meter reads 8.94 AF in September 2026 and 5.00 AF in April 2026. WAIT-4
lies in no OpenET field (ruling 160: not waiting). Each test adds what it needs.
"""
import io
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import CalculationRequest, CalculationRun
from accounting.year_reading import YearReading
from core.models import User
from datasync import crop_et, field_list
from datasync.models import CropETFigure, OpenETField, OpenETFieldMonth, OpenETFieldShare
from measurements.models import Meter, MeterReading
from parcels.models import Parcel, ParcelLedger
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WellIrrigatedParcelFactory,
)
from tests.test_calculation_run import _irrigate, _square
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

ET_MM = Decimal("304.8")  # 10.0000 AF over 10 acres
OCT3 = date(2026, 10, 3)
SEP = date(2026, 9, 1)
AUG = date(2026, 8, 1)
APR = date(2026, 4, 1)
MONTHS = [date(2025 + (m < 10), m, 1) for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8)]


def _on(monkeypatch, day):
    monkeypatch.setattr(crop_et, "today", lambda: day, raising=False)


class World:
    """The fixture's rows, by name."""


_next_field = iter(range(99_000_100_001, 99_000_199_999))


def _use_area(number, months=MONTHS, with_field=True):
    parcel = Parcel.objects.create(
        parcel_number=number, area_acres=Decimal("10"), geometry=_square(0.02 * int(number[-1]))
    )
    _irrigate(parcel)
    if with_field:
        field = OpenETField.objects.create(
            field_id=next(_next_field), area_acres=Decimal("10"), received_on=date(2026, 9, 8)
        )
        OpenETFieldShare.objects.create(parcel=parcel, field=field, overlap_acres=Decimal("10"))
        for month in months:
            OpenETFieldMonth.objects.create(
                field=field, month=month, et_mm=ET_MM, pr_mm=Decimal("0"), received_on=date(2026, 9, 8)
            )
        crop_et.record_received_months(parcel, [crop_et.month_text(m) for m in months])
    return parcel


def _reading(meter, day, af):
    return MeterReading.objects.create(
        meter=meter, reading_date=timezone.make_aware(timezone.datetime(day.year, day.month, day.day)),
        current_value=Decimal(af), calculated_volume=Decimal(af),
    )


def _own_delivery(parcel, period, month, af):
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=month, effective_date=month,
        amount_acre_feet=-Decimal(af), source_type="surface_diversion", reporting_period=period,
    )


@pytest.fixture
def world(monkeypatch):
    _on(monkeypatch, OCT3)
    call_command("seed_calculation_plan")
    w = World()
    w.period = ReportingPeriodFactory(
        name="WY 2025-2026 (waiting)", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    w.u1 = _use_area("WAIT-1")
    w.u2 = _use_area("WAIT-2")
    w.u4 = _use_area("WAIT-4", with_field=False)
    link = WellIrrigatedParcelFactory(parcel=w.u1)
    w.well = link.well
    w.meter = Meter.objects.create(serial_number="WAIT-W-METER", meter_type="totalizer", unit="acre_feet")
    WellMeter.objects.create(well=w.well, meter=w.meter, is_current=True)
    _reading(w.meter, date(2026, 4, 15), "5.00")
    _reading(w.meter, date(2026, 9, 15), "8.94")
    return w


def _run(*months):
    args = []
    for month in months:
        args += ["--month", month]
    call_command("run_accounting", *args, stdout=io.StringIO(), stderr=io.StringIO())
    return CalculationRequest.objects.order_by("-pk").first()


def _run_year(w):
    call_command("run_accounting", "--period", w.period.name, stdout=io.StringIO(), stderr=io.StringIO())
    return CalculationRequest.objects.order_by("-pk").first()


def _meter_share(parcel, month):
    return ParcelLedger.objects.current().filter(
        parcel=parcel, source_type="meter_reading", effective_date=month
    )


def _drop_month(parcel, month):
    """Take one month's crop ET away from a use area, as if OpenET had never sent it."""
    CropETFigure.objects.filter(parcel=parcel, month=month).delete()
    OpenETFieldMonth.objects.filter(field__shares__parcel=parcel, month=month).delete()


# -- (a) the latest month: measured water counts at once -----------------------------------------


def test_a_waiting_latest_month_writes_its_meter_share_and_no_calculation(world):
    _run_year(world)

    share = _meter_share(world.u1, SEP)
    assert [abs(r.amount_acre_feet) for r in share] == [Decimal("8.9400")]
    assert not CalculationRun.objects.filter(period="2026-09").exists()
    assert not ParcelLedger.objects.filter(source_type="calculated", effective_date=SEP).exists()
    # The allocation counts it: the metered groundwater charged to WAIT-1 holds September's 8.94.
    assert dict(YearReading(world.period).groundwater_kind_terms([world.u1.pk]))["metered"] == Decimal("13.9400")


def test_canal_water_split_by_shares_reaches_the_field_in_a_waiting_month(world):
    pod = PointOfDiversionFactory(
        name="Shares Ditch", division_method="shares", evaporation_fraction=Decimal("0"),
        seepage_fraction=Decimal("0"), spill_fraction=Decimal("0"),
    )
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=world.u2, fraction=Decimal("1"))
    DiversionRecordFactory(point_of_diversion=pod, reporting_period=world.period, month=SEP,
                           volume_acre_feet=Decimal("12"))
    _run_year(world)

    split = ParcelLedger.objects.current().filter(
        parcel=world.u2, effective_date=SEP, divided_from_headgate=True
    )
    assert sum(abs(r.amount_acre_feet) for r in split) == Decimal("12.0000")


# -- (b) a crop-need point leaves a waiting month undivided -------------------------------------


def test_a_crop_need_point_leaves_a_month_undivided_while_a_served_use_area_waits(world):
    _drop_month(world.u1, APR)
    pod = PointOfDiversionFactory(
        name="Need Canal", division_method="crop_need", evaporation_fraction=Decimal("0"),
        seepage_fraction=Decimal("0"), spill_fraction=Decimal("0"),
    )
    for parcel in (world.u1, world.u2):
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel, fraction=Decimal("0.5"))
    for month in (date(2026, 3, 1), APR):
        DiversionRecordFactory(point_of_diversion=pod, reporting_period=world.period, month=month,
                               volume_acre_feet=Decimal("20"))
    _run_year(world)

    def divided(month):
        return ParcelLedger.objects.current().filter(
            effective_date=month, divided_from_headgate=True, divided_from_point_pk=pod.pk
        ).count()

    assert divided(date(2026, 3, 1)) == 2
    assert divided(APR) == 0


# -- (c) a month missing for one use area in the middle of the year ----------------------------


def test_a_middle_month_missing_for_one_use_area_is_left_out_of_its_balance_whole(world):
    _drop_month(world.u1, APR)
    _own_delivery(world.u1, world.period, APR, "3")
    _own_delivery(world.u1, world.period, date(2026, 5, 1), "4")
    _own_delivery(world.u2, world.period, APR, "2")
    _run_year(world)

    reading = YearReading(world.period)
    one = reading.consumptive_use_balance([world.u1.pk])
    # WAIT-1: April (3 AF canal, 5 AF meter) and September (8.94 AF meter) are left out.
    assert one["supplies"]["surface"] == Decimal("4")
    assert one["consumptive_use_gross"] == Decimal("100.0000")  # ten months of 10 AF
    assert one["calculation_runs"] == 10
    # The allocation keeps every month's meter water; the balance leaves out April's and September's.
    assert dict(reading.groundwater_kind_terms([world.u1.pk]))["metered"] == Decimal("13.9400")
    assert one["supplies"]["groundwater"] == reading.charged([world.u1.pk]) - Decimal("13.9400")
    assert one["groundwater_charged"] == reading.charged([world.u1.pk])
    # WAIT-2 has April's figure: its April delivery is in its balance.
    two = reading.consumptive_use_balance([world.u2.pk])
    assert two["supplies"]["surface"] == Decimal("2")
    assert two["calculation_runs"] == 11


# -- (d) the balance says what it covers, everywhere it shows -----------------------------------


def test_the_balance_reports_the_months_it_covers_and_the_months_waiting(world):
    _drop_month(world.u1, APR)
    _run_year(world)

    covered = YearReading(world.period).covered([world.u1.pk])
    assert covered["last"] == AUG
    assert covered["waiting"] == [APR, SEP]
    assert YearReading(world.period).covered([world.u4.pk])["waiting"] == []


def test_account_and_dashboard_count_use_areas_waiting_and_give_no_balance_to_one_with_nothing_counted(world):
    from accounting.views.accounts import _account_detail_context
    from accounting.views.dashboard import _account_rollup

    u3 = _use_area("WAIT-3", months=[])
    _own_delivery(u3, world.period, date(2026, 6, 1), "6")
    account = WaterAccountFactory(status="active")
    for parcel in (world.u1, world.u2, u3):
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
    _run_year(world)

    context = _account_detail_context(account, str(world.period.pk))
    assert context["use_areas_waiting"] == 3
    row = next(r for r in context["parcel_balances"] if r["parcel"].pk == u3.pk)
    assert row["calculation_runs"] == 0
    assert row["supply_total"] == Decimal("0")
    assert context["use_areas_in_surplus"] + context["use_areas_in_deficit"] + context["use_areas_balanced"] == 2

    rollup = _account_rollup(world.period, False, None)
    assert rollup["use_areas_waiting"] == 3


def test_the_use_area_page_reads_waiting_for_the_month_and_says_what_the_balance_covers(world):
    _run_year(world)
    admin = User.objects.create_user(
        username="waiter", email="waiter@example.org", password="a-good-passw0rd", agency_admin=True
    )
    client = Client()
    client.force_login(admin)
    page = client.get(reverse("parcels:detail", args=[world.u1.pk]) + f"?period={world.period.pk}")
    text = " ".join(page.content.decode().split())

    assert reverse("accounting:calculation_run_detail", args=[world.u1.pk, "2026-09"]) in text
    # wording approved: ruling 212 (rows 1 and 3a)
    assert ">Waiting for OpenET<" in text.replace("> ", ">").replace(" <", "<")
    assert "The balance runs through August 2026. September 2026 is waiting for OpenET and is left out." in text


# -- (e) the waiting month's own page ------------------------------------------------------------


def test_the_waiting_months_page_opens_and_a_month_not_ended_stays_not_found(world):
    _run_year(world)
    admin = User.objects.create_user(
        username="pager", email="pager@example.org", password="a-good-passw0rd", agency_admin=True
    )
    client = Client()
    client.force_login(admin)

    def page(parcel, month):
        return client.get(reverse("accounting:calculation_run_detail", args=[parcel.pk, month]))

    waiting = page(world.u1, "2026-09")
    assert waiting.status_code == 200
    text = " ".join(waiting.content.decode().split())
    assert "September 2026" in text
    assert "8.94" in text
    assert page(world.u1, "2026-10").status_code == 404
    # A use area in no OpenET field is not waiting (ruling 160): no month page, and its own page
    # keeps today's words.
    assert page(world.u4, "2026-09").status_code == 404
    pane = client.get(reverse("parcels:detail", args=[world.u4.pk]) + f"?period={world.period.pk}")
    assert "No OpenET field is on record for this use area." in pane.content.decode()


# -- (f) the run's note names only ended months --------------------------------------------------


# wording approved: ruling 212 (row 10)
def test_the_runs_note_names_only_ended_months_without_crop_et(world):
    req = _run("2026-08", "2026-09", "2026-10", "2026-11")

    assert req.months == ["2026-08", "2026-09"]
    assert req.notes == [
        "OpenET has not sent crop ET for September 2026 yet. The month is left out of the balance "
        "until it arrives. Its meter readings and canal water split by shares are on the ledger."
    ]


# -- (g) and (h) the monthly OpenET request -------------------------------------------------------


def _fake_figures(calls, stop_after=None):
    def figures(ids, start, end):
        calls.append((list(ids), start, end))
        if stop_after is not None and len(calls) > stop_after:
            raise field_list.AllowanceUsed()
        return [
            (number, month, ET_MM, Decimal("0"))
            for number in ids
            for month in (date(2026, 9, 1),)
        ]
    return figures


def test_the_monthly_request_asks_through_the_end_of_last_month(world, monkeypatch, settings):
    settings.OPENET_MODE = "fields"
    calls = []
    monkeypatch.setattr(field_list, "figures", _fake_figures(calls))
    monkeypatch.setattr(field_list, "lookup", lambda rectangle: [])
    call_command("sync_openet_parcels", stdout=io.StringIO(), stderr=io.StringIO())

    assert calls
    assert {end for _ids, _start, end in calls} == {date(2026, 9, 30)}


def test_a_run_the_allowance_stops_records_the_months_it_received_first(world, monkeypatch, settings):
    settings.OPENET_MODE = "fields"
    settings.OPENET_FIELDS_PER_REQUEST = 1
    calls = []
    monkeypatch.setattr(field_list, "figures", _fake_figures(calls, stop_after=1))
    monkeypatch.setattr(field_list, "lookup", lambda rectangle: [])
    call_command("sync_openet_parcels", stdout=io.StringIO(), stderr=io.StringIO())

    # The first request (WAIT-1's field) was answered; the second ran out of the allowance.
    assert len(calls) == 2
    assert CropETFigure.objects.current().filter(parcel=world.u1, month=SEP).exists()
    assert not CropETFigure.objects.current().filter(parcel=world.u2, month=SEP).exists()


# -- (i) Site Health -----------------------------------------------------------------------------


def test_site_health_counts_waiting_months_green_until_two_months_past_then_yellow(world, monkeypatch):
    from health.checks import check_openet_waiting

    green = check_openet_waiting()
    assert green["category"] == "openet_waiting"
    assert green["status"] == "green"
    assert green["details"]["use_areas_waiting"] == 2
    assert "WAIT-4" not in green["message"]

    _on(monkeypatch, date(2026, 11, 30))
    assert check_openet_waiting()["status"] == "green"

    _on(monkeypatch, date(2026, 12, 1))
    yellow = check_openet_waiting()
    assert yellow["status"] == "yellow"
    assert "WAIT-1" in yellow["message"]
    assert "September 2026" in yellow["message"]


# -- (j) a month with a figure is calculated as before -------------------------------------------


def test_a_month_with_crop_et_is_calculated_exactly_as_before(world):
    _run("2026-08")
    before = sorted(
        (r.parcel_id, r.gross_et_af, r.net_consumptive_use_af, r.final_af)
        for r in CalculationRun.objects.filter(period="2026-08")
    )
    _run_year(world)
    after = sorted(
        (r.parcel_id, r.gross_et_af, r.net_consumptive_use_af, r.final_af)
        for r in CalculationRun.objects.filter(period="2026-08")
    )
    assert before == after
    assert {gross for _p, gross, _n, _f in after} == {Decimal("10.0000")}


# -- (k) a month whose crop ET record is withdrawn waits again ----------------------------------


def test_a_month_whose_crop_et_is_withdrawn_after_a_calculation_waits_again(world):
    _run_year(world)
    assert CalculationRun.objects.filter(parcel=world.u2, period="2026-08").exists()

    _drop_month(world.u2, AUG)
    _run_year(world)

    assert not CalculationRun.objects.filter(parcel=world.u2, period="2026-08").exists()
    assert not ParcelLedger.objects.filter(parcel=world.u2, source_type="calculated", effective_date=AUG).exists()
    covered = YearReading(world.period).covered([world.u2.pk])
    assert covered["last"] == date(2026, 7, 1)
    assert covered["waiting"] == [AUG, SEP]


# -- (k) ISS-446: why a row's Groundwater and its Remaining differ while a month waits (ruling 217) -----

GW_GAP_DASHBOARD = (
    "Remaining counts meter readings for months waiting for OpenET. Groundwater leaves those months out."
)
GW_GAP_ACCOUNT = (
    "Used includes meter readings for months waiting for OpenET. "
    "The Groundwater figures on this page leave those months out."
)


def _budgeted_account(w):
    """An account holding WAIT-1 and WAIT-2 inside a zone with a groundwater allocation."""
    from accounting.models import WaterType
    from tests.factories import AllocationPlanFactory, ParcelZoneFactory, ZoneFactory

    groundwater = WaterType.objects.filter(code="GW").first() or WaterType.objects.create(
        name="Groundwater", code="GW"
    )
    zone = ZoneFactory(name="Waiting GSA Zone", zone_type="management_area")
    account = WaterAccountFactory(status="active")
    for parcel in (w.u1, w.u2):
        ParcelZoneFactory(parcel=parcel, zone=zone)
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
    AllocationPlanFactory(
        zone=zone, water_type=groundwater, reporting_period=w.period, allocation_acre_feet=Decimal("50.0000")
    )
    return account


def _caption_words(client, w, account):
    import re

    def words(response):
        assert response.status_code == 200
        return " ".join(re.sub(r"<[^>]+>", " ", response.content.decode()).split())

    dashboard = words(client.get(reverse("accounting:dashboard") + f"?period={w.period.pk}"))
    account_page = words(client.get(reverse("accounting:account_detail", args=[account.pk]) + f"?period={w.period.pk}"))
    return dashboard, account_page


def _staff_client():
    client = Client()
    client.force_login(User.objects.create_user(
        username="gap-reader", email="gap-reader@example.org", password="a-good-passw0rd", agency_admin=True
    ))
    return client


def test_while_a_month_waits_the_dashboard_and_account_say_why_groundwater_and_remaining_differ(world):
    account = _budgeted_account(world)
    _run_year(world)

    dashboard, account_page = _caption_words(_staff_client(), world, account)

    # wording approved: ruling 218 (rows G1, G2, G3)
    assert dashboard.count(GW_GAP_DASHBOARD) == 2  # the Active water accounts and Zones captions
    assert account_page.count(GW_GAP_ACCOUNT) == 1  # the Groundwater budget caption


def test_with_nothing_waiting_neither_page_carries_the_sentence(world):
    account = _budgeted_account(world)
    for parcel in (world.u1, world.u2):
        field = OpenETFieldShare.objects.get(parcel=parcel).field
        OpenETFieldMonth.objects.create(
            field=field, month=SEP, et_mm=ET_MM, pr_mm=Decimal("0"), received_on=date(2026, 10, 2)
        )
        crop_et.record_received_months(parcel, [crop_et.month_text(SEP)])
    _run_year(world)

    dashboard, account_page = _caption_words(_staff_client(), world, account)

    assert "Use areas with a month waiting for OpenET" not in dashboard
    assert "meter readings for months" not in dashboard
    assert "meter readings for months" not in account_page
    assert "Groundwater budget" in account_page
