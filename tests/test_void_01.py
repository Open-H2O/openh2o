# SPDX-License-Identifier: AGPL-3.0-or-later
"""Void this record: the control, the reason row, the struck line, and a reason on every edit.

Plan 151.7-01 Task 4. ``core.corrections`` holds the rule (tests/test_current_records_01.py); this
file proves what a person sees and can do:

* (d) a viewer, a finalized-year row, a short reason and an already voided row are all refused;
  the "..." menu is absent for a viewer, on an engine row, on a voided row and (well, diversion,
  recharge) on a finalized-year row, and present on an open person-entered row with Void this
  record last;
* (e) voiding a recharge event takes its credit and its entry in the basin recharge pool back, as
  deleting it did;
* (f) voiding a diversion record asks for the recalculation of its month (trigger
  ``record_voided``) and says so;
* (g) the struck line renders on the well page and the ledger page, with the line's exact words;
* (j) the new route is a write page;
* every edit of a covered figure refuses a missing or short reason and saves the reason into
  Change history.
"""

import datetime as dt
import re
from decimal import Decimal as D
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from accounting.models import CalculationRequest, ReportingPeriod
from core import corrections
from core.access import is_write_page
from core.reasons import REASON_SENTENCE
from datasync.models import DataRecordStaging, TypedReading
from drinking.models import SystemProduction
from measurements.models import Meter, MeterReading
from parcels.models import FallowPeriod
from recharge.models import RechargeEvent
from tests import ledger_districts as ld
from tests.factories import (
    DiversionRecordFactory,
    MonitoredStationFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    RechargeEventFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    WaterSystemFactory,
    WaterTypeFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
    ZoneFactory,
)
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

User = get_user_model()

REASON = "typed on the wrong well"
HX = {"HTTP_HX_REQUEST": "true"}
PACIFIC = ZoneInfo("America/Los_Angeles")


# ------------------------------------------------------------------ helpers
def _user(username, **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="a-good-passw0rd",
        is_active=True, **flags,
    )


@pytest.fixture
def operator():
    return _user("operator", first_name="Jose", last_name="Lopez")


@pytest.fixture
def viewer():
    return _user("viewer", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def void_url(kind, row):
    return reverse("core:record_void", args=[kind, row.pk])


def post_void(client, kind, row, reason=REASON):
    return client.post(void_url(kind, row), {"void_reason": reason})


def finalize(start, end, name="Closed WY"):
    period = ReportingPeriodFactory(name=name, start_date=start, end_date=end)
    ReportingPeriod.objects.filter(pk=period.pk).update(is_finalized=True)
    period.refresh_from_db()
    return period


def expected_line(row, reason=REASON, who="J. Lopez"):
    when = timezone.localtime(row.voided_at, PACIFIC)
    return f"Voided {when:%b} {when.day}, {when.year} by {who}: {reason}."


def well_with_reading(day=dt.date(2026, 9, 30), value="17557.18"):
    well = WellFactory()
    meter = Meter.objects.create(serial_number=f"V1-{well.pk}", meter_type="totalizer", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    reading = MeterReading.objects.create(
        meter=meter,
        reading_date=timezone.make_aware(dt.datetime(day.year, day.month, day.day, 12, 0)),
        current_value=D(value),
    )
    return well, reading


def menu_of(body, kind, row):
    """The markup of one row's menu: from its popover to the end of its cell.

    Not to the first </div>: the separator before Void this record is a div of its own.
    """
    start = body.index(f'id="menu-record-{kind}-{row.pk}"')
    return body[start:body.index("</td>", start)]


# ------------------------------------------------------------------ (d) refusals
def test_a_viewer_cannot_open_or_take_a_void(viewer):
    record = DiversionRecordFactory()
    client = _client(viewer)

    assert client.get(void_url("diversion_record", record), **HX).status_code == 403
    assert post_void(client, "diversion_record", record).status_code == 403
    record.refresh_from_db()
    assert record.voided_at is None


def test_the_void_route_is_a_write_page():
    assert is_write_page("core:record_void") is True


def test_a_finalized_year_row_is_refused(operator):
    # The record goes in before the year closes: the lock refuses it after.
    closed = ReportingPeriodFactory(
        name="Closed WY", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30)
    )
    record = DiversionRecordFactory(month=dt.date(2024, 3, 1), reporting_period=closed)
    ReportingPeriod.objects.filter(pk=closed.pk).update(is_finalized=True)

    response = post_void(_client(operator), "diversion_record", record)

    assert response.status_code == 200
    assert "Nothing was voided." in response.content.decode()
    record.refresh_from_db()
    assert record.voided_at is None


def test_a_reason_under_ten_characters_is_refused_and_the_form_stays_open(operator):
    record = DiversionRecordFactory()

    response = post_void(_client(operator), "diversion_record", record, reason="too short")

    body = response.content.decode()
    assert response.status_code == 200
    assert REASON_SENTENCE in body
    assert 'class="row-editing record-void-form"' in body
    assert 'value="too short"' in body
    record.refresh_from_db()
    assert record.voided_at is None


def test_an_already_voided_row_is_refused_and_keeps_its_first_reason(operator):
    record = DiversionRecordFactory()
    corrections.void(record, user=operator, reason=REASON)

    response = post_void(_client(operator), "diversion_record", record, reason="a second, different reason")

    assert response.status_code == 200
    assert "already voided" in response.content.decode()
    record.refresh_from_db()
    assert record.void_reason == REASON


def test_a_kind_with_no_screen_has_no_void_screen(operator):
    from tests.test_current_records_01 import make_row

    measurement = make_row("recharge_measurement")
    assert post_void(_client(operator), "recharge_measurement", measurement).status_code == 404
    assert _client(operator).post(
        reverse("core:record_void", args=["no_such_kind", 1]), {"void_reason": REASON}
    ).status_code == 404


def test_void_opens_the_reason_row_under_the_record_and_cancel_closes_it(operator):
    record = DiversionRecordFactory()
    other = DiversionRecordFactory(point_of_diversion=record.point_of_diversion, month=dt.date(2024, 2, 1))
    client = _client(operator)

    opened = client.get(void_url("diversion_record", record), **HX).content.decode()
    assert 'class="row-editing record-void-form"' in opened
    assert 'name="void_reason"' in opened
    assert f'id="record-diversion_record-{record.pk}" class="row-editing"' in opened
    assert menu_of(opened, "diversion_record", other)  # the other rows keep their menus
    assert f'id="menu-record-diversion_record-{record.pk}"' not in opened  # this row's cell is empty

    cancelled = client.get(void_url("diversion_record", record) + "?cancel=1", **HX).content.decode()
    assert "record-void-form" not in cancelled
    assert f'id="menu-record-diversion_record-{record.pk}"' in cancelled


# ------------------------------------------------------------------ (d) who gets the menu
def test_an_open_diversion_row_has_edit_then_void_and_a_viewer_has_neither(operator, viewer):
    record = DiversionRecordFactory()
    page = reverse("surface:pod_detail", args=[record.point_of_diversion_id])

    body = _client(operator).get(page).content.decode()
    menu = menu_of(body, "diversion_record", record)
    assert "Actions for the Jan 2024 record" in body
    assert menu.index("Edit") < menu.index("Void this record")
    assert 'role="separator"' in menu[: menu.index("Void this record")]

    seen = _client(viewer).get(page).content.decode()
    assert "row-actions-btn" not in seen
    assert "Void this record" not in seen


def test_a_finalized_diversion_row_reads_finalized_with_no_menu(operator):
    # The record goes in before the year closes: the lock refuses it after.
    closed = ReportingPeriodFactory(
        name="Closed WY", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30)
    )
    record = DiversionRecordFactory(month=dt.date(2024, 3, 1), reporting_period=closed)
    ReportingPeriod.objects.filter(pk=closed.pk).update(is_finalized=True)

    body = _client(operator).get(reverse("surface:pod_detail", args=[record.point_of_diversion_id])).content.decode()

    assert "Finalized" in body
    assert f"menu-record-diversion_record-{record.pk}" not in body


def test_an_engine_diversion_row_has_edit_only(operator):
    record = DiversionRecordFactory(method="estimated_from_use")

    body = _client(operator).get(reverse("surface:pod_detail", args=[record.point_of_diversion_id])).content.decode()

    menu = menu_of(body, "diversion_record", record)
    assert "Edit" in menu
    assert "Void this record" not in menu


def test_the_well_menu_holds_correct_then_void_and_is_absent_for_a_viewer_and_a_voided_read(operator, viewer):
    well, reading = well_with_reading()
    page = reverse("wells:detail", args=[well.pk])

    body = _client(operator).get(page).content.decode()
    assert "Actions for the Sep 30, 2026 reading" in body
    menu = menu_of(body, "meter_reading", reading)
    assert menu.index("Correct this record") < menu.index('role="separator"') < menu.index("Void this record")
    assert "Edit" not in menu

    assert "row-actions-btn" not in _client(viewer).get(page).content.decode()

    corrections.void(reading, user=operator, reason=REASON)
    assert "Actions for the Sep 30, 2026 reading" not in _client(operator).get(page).content.decode()


def test_a_well_read_in_a_finalized_year_has_no_menu(operator):
    well, reading = well_with_reading(day=dt.date(2024, 3, 31))
    finalize(dt.date(2023, 10, 1), dt.date(2024, 9, 30))

    body = _client(operator).get(reverse("wells:detail", args=[well.pk])).content.decode()

    assert f"menu-record-meter_reading-{reading.pk}" not in body


def test_the_ledger_menu_is_on_a_typed_row_and_not_on_an_engine_row(operator, viewer):
    typed = ParcelLedgerFactory(source_type="manual_entry", effective_date=dt.date(2026, 9, 15))
    engine = ParcelLedgerFactory(source_type="calculated", effective_date=dt.date(2026, 9, 30))
    page = reverse("accounting:ledger_list") + "?period="

    body = _client(operator).get(page).content.decode()
    assert f'id="menu-record-ledger_entry-{typed.pk}"' in body
    assert f"menu-record-ledger_entry-{engine.pk}" not in body
    assert "Void this record" in menu_of(body, "ledger_entry", typed)

    assert "row-actions-btn" not in _client(viewer).get(page).content.decode()


def test_a_recharge_event_in_a_finalized_year_has_no_edit_and_a_menu_for_an_administrator_only(
    operator, settings
):
    settings.ACCESS_CONTROL_ENFORCED = True
    site = RechargeSiteFactory(zone=ZoneFactory())
    # The events go in before the year closes: the lock refuses a write into it after.
    old = RechargeEventFactory(recharge_site=site, start_date=dt.date(2024, 3, 1))
    new = RechargeEventFactory(recharge_site=site, start_date=dt.date(2025, 3, 1))
    closed = finalize(dt.date(2023, 10, 1), dt.date(2024, 9, 30))
    assert closed.is_finalized
    page = reverse("recharge:detail", args=[site.pk])

    seen = _client(operator).get(page).content.decode()
    assert f"menu-record-recharge_event-{old.pk}" not in seen
    new_menu = menu_of(seen, "recharge_event", new)
    assert new_menu.index("Edit") < new_menu.index("Correct this record") < new_menu.index("Void this record")

    boss = _user("boss", agency_admin=True)
    body = _client(boss).get(page).content.decode()
    old_menu = menu_of(body, "recharge_event", old)
    assert "Correct this record" in old_menu and "Void this record" in old_menu
    assert "Edit" not in old_menu


# ------------------------------------------------------------------ (e) a recharge event
def test_voiding_a_recharge_event_takes_back_its_credit_and_its_pool_entry(operator):
    from accounting.models import AccountCredit, AllocationCarryover, WaterAccount

    ld.seed_reference()
    d3 = ld.build_d3(with_event=False)
    account = WaterAccount.objects.create(name="D3 District", account_number="D3-D", unit_kind="farm_unit")
    site = d3["site"]
    site.water_account = account
    site.save()
    event = ld.log_event(site, dt.date(2025, 8, 1), dt.date(2025, 8, 31), "50.0000", "GW")
    assert AccountCredit.objects.count() == 1
    assert AllocationCarryover.objects.filter(origin="basin_recharge_pool").count() == 1

    response = post_void(_client(operator), "recharge_event", event)

    assert (
        "Event voided. OpenH2O removed any credit and took its volume out of the basin recharge pool."
    ) in response.content.decode()
    assert RechargeEvent.objects.count() == 1
    assert RechargeEvent.objects.current().count() == 0
    assert AccountCredit.objects.count() == 0
    assert AllocationCarryover.objects.filter(origin="basin_recharge_pool").count() == 0


def test_a_voided_event_is_struck_in_place_and_out_of_the_count(operator):
    site = RechargeSiteFactory(zone=ZoneFactory())
    gone = RechargeEventFactory(recharge_site=site, start_date=dt.date(2024, 1, 1))
    RechargeEventFactory(recharge_site=site, start_date=dt.date(2024, 2, 1), volume_acre_feet=D("8.0000"))

    body = post_void(_client(operator), "recharge_event", gone).content.decode()

    assert f'id="record-recharge_event-{gone.pk}" class="record-void"' in body
    assert "1 event over" in body


# ------------------------------------------------------------------ (f) a diversion record
@mock.patch("accounting.engine_run.start_calculation")
def test_voiding_a_diversion_record_asks_for_its_month_to_be_calculated_again(started, operator):
    ReportingPeriodFactory(start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30))
    record = DiversionRecordFactory(month=dt.date(2024, 1, 1))

    response = post_void(_client(operator), "diversion_record", record)

    request = CalculationRequest.objects.get(trigger="record_voided")
    assert request.months == ["2024-01"]
    assert started.called
    assert "Record voided. OpenH2O recalculated Jan 2024." in response.content.decode()
    record.refresh_from_db()
    assert (record.voided_by, record.void_reason) == (User.objects.get(username="operator"), REASON)


# ------------------------------------------------------------------ (g) the struck line
def test_the_well_page_strikes_a_voided_read_and_prints_its_line(operator):
    well, reading = well_with_reading()
    corrections.void(reading, user=operator, reason=REASON)
    reading.refresh_from_db()

    body = _client(operator).get(reverse("wells:detail", args=[well.pk])).content.decode()

    assert f'<tr id="record-meter_reading-{reading.pk}" class="record-void">' in body
    assert expected_line(reading) in body
    assert "WY 2025-2026 &middot; 0 reads" in body


def test_the_ledger_page_strikes_a_voided_entry_and_prints_its_line(operator):
    entry = ParcelLedgerFactory(source_type="manual_entry", effective_date=dt.date(2026, 9, 15))
    corrections.void(entry, user=operator, reason=REASON)
    entry.refresh_from_db()

    body = _client(operator).get(reverse("accounting:ledger_list") + "?period=").content.decode()

    assert f'<tr id="record-ledger_entry-{entry.pk}" class="record-void">' in body
    assert expected_line(entry) in body
    assert f"menu-record-ledger_entry-{entry.pk}" not in body
    assert "0 entries" in body


def test_the_line_is_the_users_initial_and_surname_or_the_name_the_history_shows(operator):
    from core.templatetags.record_marks import void_line

    record = DiversionRecordFactory()
    corrections.void(record, user=operator, reason="Entered on the wrong point.")
    record.refresh_from_db()
    assert void_line(record) == expected_line(record, reason="Entered on the wrong point")

    nameless = _user("nameless")
    other = DiversionRecordFactory(month=dt.date(2024, 5, 1))
    corrections.void(other, user=nameless, reason=REASON)
    other.refresh_from_db()
    assert void_line(other).endswith(f"by nameless@example.org: {REASON}.")


# ------------------------------------------------------------------ the other screens
def test_a_voided_fallow_period_gives_its_months_back_and_cannot_be_ended(operator):
    from parcels.views import fallow_row_context

    parcel = ParcelFactory()
    period = FallowPeriod.objects.create(parcel=parcel, start_month=dt.date(2025, 7, 1))
    assert fallow_row_context(parcel)["can_end"] is True

    corrections.void(period, user=operator, reason=REASON)

    context = fallow_row_context(parcel)
    assert context["can_end"] is False
    assert context["value"] == "Not fallow"
    assert [entry["row"].pk for entry in context["voided"]] == [period.pk]
    body = _client(operator).get(reverse("parcels:detail", args=[parcel.pk])).content.decode()
    assert "End fallow period" not in body
    assert "Add fallow period" in body
    assert "record-void-text" in body


def test_a_voided_use_area_shows_the_line_and_is_not_drawn(operator):
    parcel = ParcelFactory()
    corrections.void(parcel, user=operator, reason=REASON)
    parcel.refresh_from_db()

    response = _client(operator).get(reverse("parcels:detail", args=[parcel.pk]))

    assert response.context["geojson"] is None
    assert expected_line(parcel) in response.content.decode()
    assert "menu-record-use_area" not in response.content.decode()


def test_a_use_area_void_sends_the_browser_to_its_page(operator):
    parcel = ParcelFactory()

    response = post_void(_client(operator), "use_area", parcel)

    assert response.status_code == 204
    assert response["HX-Redirect"] == reverse("parcels:detail", args=[parcel.pk])
    parcel.refresh_from_db()
    assert parcel.voided_at is not None


def test_a_typed_station_reading_has_a_menu_and_a_voided_one_is_struck_on_the_card(operator):
    station = MonitoredStationFactory()
    now = timezone.now()
    published = DataRecordStaging.objects.create(
        data_source=station.data_source, station=station, raw_data={},
        observation_date=now, parameter_code="gage_height", statistic="",
        value=D("1"), status="published", published_at=now,
    )
    typed = TypedReading.objects.create(
        station=station, reading=published, parameter_code="gage_height",
        observation_date=now.date(), value=D("1"),
    )
    from datasync.views import _readings_card_context

    card = _readings_card_context(station)
    assert [r.typed.pk for r in card["card_records"] if r.typed] == [typed.pk]
    assert card["card_records"][0].typed.menu_ok is True

    post_void(_client(operator), "station_reading", typed)

    typed.refresh_from_db()
    assert typed.voided_at is not None
    assert not DataRecordStaging.objects.filter(pk=published.pk).exists()


def test_the_production_page_strikes_a_voided_month_and_leaves_it_out_of_the_total(operator):
    system = WaterSystemFactory()
    kept = SystemProduction.objects.create(
        system=system, year=2025, month=4, type_code="GW",
        volume_as_reported=D("200"), unit_as_reported="G", provenance="typed",
    )
    gone = SystemProduction.objects.create(
        system=system, year=2025, month=3, type_code="GW",
        volume_as_reported=D("100"), unit_as_reported="G", provenance="typed",
    )
    corrections.void(gone, user=operator, reason=REASON)

    body = _client(operator).get(reverse("drinking:production") + "?year=2025").content.decode()

    assert "record-void-text" in body
    assert "Voided " in body
    assert "200 gallons produced or purchased" in body
    assert f"menu-record-production_record-{kept.pk}" in body
    assert f"menu-record-production_record-{gone.pk}" not in body


# ------------------------------------------------------------------ a reason on every edit
def _patch(client, url, **data):
    return client.patch(url, data=urlencode(data), content_type="application/x-www-form-urlencoded")


def note_of(row, label="update"):
    return row.events.get(pgh_label=label).pgh_context.metadata.get("note")


def test_a_diversion_edit_needs_a_reason_and_saves_it_into_change_history(operator):
    record = DiversionRecordFactory(month=dt.date(2024, 3, 1), volume_acre_feet=D("33.0000"))
    url = reverse("surface:diversion_record_edit", args=[record.point_of_diversion_id, record.pk])
    fields = {"month": "2024-03-01", "volume_acre_feet": "40", "returned_af": "0", "diversion_type": "direct_use"}
    client = _client(operator)

    for reason in ("", "short"):
        refused = client.post(url, {**fields, "reason": reason})
        assert REASON_SENTENCE in refused.content.decode()
        record.refresh_from_db()
        assert record.volume_acre_feet == D("33.0000")

    client.post(url, {**fields, "reason": "Corrected against the ditch log."})
    record.refresh_from_db()
    assert record.volume_acre_feet == D("40.0000")
    assert note_of(record) == "Corrected against the ditch log."


def test_the_diversion_edit_form_carries_a_reason_box_and_void_apart_from_save(operator):
    record = DiversionRecordFactory()
    url = reverse("surface:diversion_record_edit", args=[record.point_of_diversion_id, record.pk])

    body = _client(operator).get(url).content.decode()

    form = body[body.index("Edit diversion record"):]
    assert 'for="id_reason">Reason</label>' in form
    box = re.search(r'<input[^>]*id="id_reason"[^>]*>', form).group(0)
    assert "placeholder" not in box
    assert form.index("Void this record") < form.index("Save")
    assert void_url("diversion_record", record) in body


def test_a_recharge_event_edit_needs_a_reason_and_saves_it_into_change_history(operator):
    site = RechargeSiteFactory()
    event = RechargeEventFactory(recharge_site=site, volume_acre_feet=D("100.0000"))
    water_type = WaterTypeFactory()
    url = reverse("recharge:event_edit", args=[site.pk, event.pk])
    fields = {
        "start_date": "2024-01-01", "end_date": "2024-01-31", "volume_acre_feet": "90",
        "water_type": water_type.pk, "source_description": "", "notes": "",
    }
    client = _client(operator)

    refused = client.post(url, {**fields, "reason": "short"})
    assert REASON_SENTENCE in refused.content.decode()
    event.refresh_from_db()
    assert event.volume_acre_feet == D("100.0000")

    assert client.post(url, {**fields, "reason": "Corrected from the site log."}).status_code == 302
    event.refresh_from_db()
    assert event.volume_acre_feet == D("90.0000")
    assert note_of(event) == "Corrected from the site log."


def test_the_recharge_edit_page_carries_void_apart_from_save(operator):
    site = RechargeSiteFactory()
    event = RechargeEventFactory(recharge_site=site)

    body = _client(operator).get(reverse("recharge:event_edit", args=[site.pk, event.pk])).content.decode()

    assert body.index("Void this record") < body.index("Save changes")
    assert void_url("recharge_event", event) in body


def test_a_void_from_the_recharge_edit_page_goes_back_to_the_site(operator):
    site = RechargeSiteFactory()
    event = RechargeEventFactory(recharge_site=site)
    client = _client(operator)

    refused = client.post(void_url("recharge_event", event), {"reason": "short", "inline": "1"})
    assert REASON_SENTENCE in refused.content.decode()
    assert "<table" not in refused.content.decode()

    done = client.post(void_url("recharge_event", event), {"reason": REASON, "inline": "1"})
    assert done.status_code == 204
    assert done["HX-Redirect"].startswith(reverse("recharge:detail", args=[site.pk]))


def test_fallow_add_and_end_need_a_reason_and_save_it(operator):
    parcel = ParcelFactory()
    client = _client(operator)
    add = reverse("parcels:fallow_period_add", args=[parcel.pk])
    end = reverse("parcels:fallow_period_end_edit", args=[parcel.pk])

    refused = client.post(add, {"start_month": "2025-07-01", "end_month": ""})
    assert REASON_SENTENCE in refused.content.decode()
    assert not FallowPeriod.objects.filter(parcel=parcel).exists()

    client.post(add, {"start_month": "2025-07-01", "end_month": "", "reason": "Marked from the survey."})
    period = FallowPeriod.objects.get(parcel=parcel)
    assert note_of(period, "insert") == "Marked from the survey."

    refused = client.post(end, {"end_month": "2025-08-01", "reason": ""})
    assert REASON_SENTENCE in refused.content.decode()
    period.refresh_from_db()
    assert period.end_month is None

    client.post(end, {"end_month": "2025-08-01", "reason": "Ended when the crop went in."})
    period.refresh_from_db()
    assert period.end_month == dt.date(2025, 8, 1)
    assert note_of(period) == "Ended when the crop went in."


def test_the_use_area_figures_ask_why_and_the_other_fields_do_not(operator):
    parcel = ParcelFactory(area_acres="80.00", owner_name="Old Owner")
    url = reverse("parcels:edit_field", args=[parcel.pk])
    client = _client(operator)

    refused = _patch(client, url, field="area_acres", value="90")
    assert REASON_SENTENCE in refused.content.decode()
    parcel.refresh_from_db()
    assert str(parcel.area_acres) == "80.00"

    _patch(client, url, field="area_acres", value="90", reason="Re-measured on the aerial photo.")
    parcel.refresh_from_db()
    assert str(parcel.area_acres) == "90.00"
    assert note_of(parcel) == "Re-measured on the aerial photo."

    assert _patch(client, url, field="owner_name", value="New Owner").status_code == 200
    parcel.refresh_from_db()
    assert parcel.owner_name == "New Owner"


def test_the_two_figure_fields_show_a_reason_box_in_their_editor(operator):
    parcel = ParcelFactory()
    client = _client(operator)
    url = reverse("parcels:edit_field", args=[parcel.pk])

    for field, has_box in (("area_acres", True), ("irrigation_method", True), ("owner_name", False)):
        body = client.get(url, {"field": field}).content.decode()
        assert ('name="reason"' in body) is has_box


def test_the_two_share_editors_ask_why(operator):
    client = _client(operator)
    well = WellFactory()
    wip = WellIrrigatedParcelFactory(well=well, fraction="1.0000")
    pod = PointOfDiversionFactory()
    pp = PointOfDiversionParcelFactory(point_of_diversion=pod, fraction="1.0000")
    well_url = reverse("wells:irrigated_parcel_edit_share", args=[well.pk, wip.pk])
    pod_url = reverse("surface:pod_parcel_edit_share", args=[pod.pk, pp.pk])

    for url, row in ((well_url, wip), (pod_url, pp)):
        refused = _patch(client, url, value="0.5")
        assert REASON_SENTENCE in refused.content.decode()
        row.refresh_from_db()
        assert row.fraction == D("1.0000")

        _patch(client, url, value="0.5", reason="Re-surveyed the headgate.")
        row.refresh_from_db()
        assert row.fraction == D("0.5000")
        assert note_of(row) == "Re-surveyed the headgate."
