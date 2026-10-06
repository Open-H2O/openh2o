# SPDX-License-Identifier: AGPL-3.0-or-later
"""149-01 Task 3: start the calculation from a screen, and from a saved record.

A person presses "Run the calculation" on a reporting period's page; a saved
diversion record, a hand-entered or imported delivery row and the nightly
schedule start the same month-by-month run (``accounting.engine_run``). The
suite never spawns a process: ``conftest.py`` sets
``OPENH2O_CALCULATION_INLINE`` so the worker runs in this process.

Fixture: the three-field canal world of ``tests/test_run_accounting.py`` (three
10-acre fields A, B and C, 10.0000 AF of crop water use each in January and
February, a 30 AF January and a 25 AF February headgate record, and field A's
own 4 AF January delivery). Tests that read the split rows set the agency's
irrigation efficiency to 1.000, so each field's cap is exactly its 10.0000 AF
of crop water use and every figure below is a literal that can be checked by
hand: January's remainder is 30 - 4 = 26 AF over fields B and C (cap 10 each,
so 10.0000 each); an edit of the record to 12 AF makes the remainder 8, split
evenly, 4.0000 each.

Every assertion is a stored value or an exact sentence.
"""
import json
import zoneinfo
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounting.engine_run import request_for_months
from accounting.locks import finalized_message
from accounting.models import CalculationRequest
from core.access import READ_ONLY_MESSAGE
from core.models import SiteConfig
from parcels.models import ParcelLedger
from surface.models import DiversionRecord, MeasuringDevice, PointOfDiversionDevice
from tests.factories import ReportingPeriodFactory, WaterRightFactory
from tests.test_run_accounting import (  # noqa: F401  (world is a fixture)
    FEB,
    JAN,
    NO_DATA_MARCH,
    _run_months,
    world,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

LOS_ANGELES = zoneinfo.ZoneInfo("America/Los_Angeles")


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        **flags,
    )


@pytest.fixture
def operator():
    return _user("calc-operator")


@pytest.fixture
def administrator():
    return _user("calc-administrator", agency_admin=True)


@pytest.fixture
def viewer():
    return _user("calc-viewer", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def full_efficiency(world):  # noqa: F811
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Test Agency"})
    config.default_irrigation_efficiency = Decimal("1.000")
    config.save()
    return config


def _detail_url(period):
    return reverse("accounting:period_detail", args=[period.pk])


def _calculate_url(period):
    return reverse("accounting:period_calculate", args=[period.pk])


def _status_url(period):
    return reverse("accounting:period_calculation_status", args=[period.pk])


def _split(first):
    """The month's divided-up rows, by parcel number."""
    return {
        row.parcel.parcel_number: row.amount_acre_feet
        for row in ParcelLedger.objects.filter(
            source_type="surface_diversion",
            divided_from_headgate=True,
            effective_date=first,
        ).select_related("parcel")
    }


def _saved(trigger):
    return CalculationRequest.objects.filter(trigger=trigger)


def _request(period, **fields):
    defaults = {"trigger": "screen", "months": ["2024-01", "2024-02"]}
    defaults.update(fields)
    return CalculationRequest.objects.create(reporting_period=period, **defaults)


def _finalize(period):
    period.is_finalized = True
    period.save(update_fields=["is_finalized"])


# --------------------------------------------------------------------------
# The button on the period page
# --------------------------------------------------------------------------


def test_an_operators_press_creates_one_request_and_runs_it(world, operator):  # noqa: F811
    response = _client(operator).post(_calculate_url(world.period))

    assert response.status_code == 302
    assert response.url == _detail_url(world.period)
    calculation = CalculationRequest.objects.get()
    assert calculation.trigger == "screen"
    assert calculation.requested_by == operator
    assert calculation.reporting_period == world.period
    assert calculation.status == "succeeded"
    assert calculation.months == ["2024-01", "2024-02"]
    assert calculation.months_done == 2
    assert calculation.outcome == "Calculated 2 months, January 2024 to February 2024."
    assert calculation.notes[0] == NO_DATA_MARCH
    # The run did its work: three fields, two months, each read exactly 10.0000 AF.
    assert ParcelLedger.objects.filter(source_type="calculated").count() == 6


def test_the_card_says_what_happened_when_it_finishes(world, operator):  # noqa: F811
    client = _client(operator)
    client.post(_calculate_url(world.period))

    html = client.get(_detail_url(world.period)).content.decode()

    assert "Run the calculation" in html
    assert "Calculated 2 months, January 2024 to February 2024." in html
    assert NO_DATA_MARCH in html
    assert f", {operator}</p>" in html  # the person who pressed it
    assert "Finished" in html
    status = client.get(_status_url(world.period)).content.decode()
    assert "hx-trigger" not in status  # finished: nothing left to poll


def test_a_second_press_while_one_is_waiting_or_running_starts_nothing(world, operator):  # noqa: F811
    for status in ("queued", "running"):
        CalculationRequest.objects.all().delete()
        under_way = _request(world.period, status=status)

        response = _client(operator).post(_calculate_url(world.period))

        assert response.status_code == 302
        assert list(CalculationRequest.objects.all()) == [under_way]
        under_way.refresh_from_db()
        assert under_way.status == status  # not run, not merged, not touched


def test_an_administrator_may_press_it_too(world, administrator):  # noqa: F811
    response = _client(administrator).post(_calculate_url(world.period))

    assert response.status_code == 302
    assert CalculationRequest.objects.get().requested_by == administrator


def test_a_viewer_is_refused_and_sees_the_last_outcome_without_a_button(world, viewer):  # noqa: F811
    _request(
        world.period,
        status="succeeded",
        outcome="Calculated 2 months, January 2024 to February 2024.",
        finished_at=datetime(2024, 4, 2, 3, 30, tzinfo=LOS_ANGELES),
        trigger="schedule",
    )

    refused = _client(viewer).post(_calculate_url(world.period))
    page = _client(viewer).get(_detail_url(world.period))

    assert refused.status_code == 403
    assert READ_ONLY_MESSAGE in refused.content.decode()
    assert CalculationRequest.objects.count() == 1
    html = page.content.decode()
    assert page.status_code == 200
    assert "Run the calculation" not in html
    assert "Calculated 2 months, January 2024 to February 2024." in html
    assert "Apr 2, 2024, 3:30 AM, the nightly schedule" in html


def test_a_finalized_period_shows_the_last_outcome_and_no_button(world, operator):  # noqa: F811
    _request(
        world.period,
        status="failed",
        outcome="The calculation stopped at February 2024 with an error.",
        finished_at=datetime(2024, 4, 2, 3, 30, tzinfo=LOS_ANGELES),
        trigger="diversion_saved",
    )
    _finalize(world.period)

    page = _client(operator).get(_detail_url(world.period))

    html = page.content.decode()
    assert "Run the calculation" not in html
    assert "The calculation stopped at February 2024 with an error." in html
    assert "Apr 2, 2024, 3:30 AM, a saved record" in html
    assert "Stopped" in html


def test_a_press_on_a_finalized_period_is_refused_and_starts_nothing(world, operator):  # noqa: F811
    _finalize(world.period)
    client = _client(operator)

    response = client.post(_calculate_url(world.period), follow=True)

    assert CalculationRequest.objects.count() == 0
    assert response.redirect_chain == [(_detail_url(world.period), 302)]
    assert finalized_message("Winter 2024") in response.content.decode()


def test_before_any_run_the_card_says_none_is_recorded(world, operator):  # noqa: F811
    html = _client(operator).get(_detail_url(world.period)).content.decode()

    assert "No calculation has been recorded for this water year yet." in html
    assert "Run the calculation" in html


# --------------------------------------------------------------------------
# The status block: polls only while there is something to wait for
# --------------------------------------------------------------------------


def test_a_running_calculation_says_since_when_and_which_month_and_polls(world, operator):  # noqa: F811
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    _request(
        world.period,
        status="running",
        months=months,
        months_done=2,
        started_at=datetime(2026, 10, 6, 4, 51, tzinfo=LOS_ANGELES),
    )

    response = _client(operator).get(_status_url(world.period))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Running since 4:51 AM, month 3 of 12." in html
    assert f'hx-get="{_status_url(world.period)}"' in html
    assert 'hx-trigger="every 3s"' in html
    assert 'hx-swap="outerHTML"' in html
    assert "hx-on" not in html
    assert "<html" not in html  # the partial, not a page


def test_a_waiting_calculation_says_so_and_polls(world, operator):  # noqa: F811
    _request(world.period, status="queued")

    html = _client(operator).get(_status_url(world.period)).content.decode()

    assert "Waiting to start." in html
    assert 'hx-trigger="every 3s"' in html


@pytest.mark.parametrize("status", ["succeeded", "finished_with_notes", "failed"])
def test_a_finished_calculation_stops_polling(world, operator, status):  # noqa: F811
    _request(
        world.period,
        status=status,
        outcome="Calculated January 2024.",
        notes=["First note.", "Second note."],
        finished_at=datetime(2024, 4, 2, 3, 30, tzinfo=LOS_ANGELES),
    )

    html = _client(operator).get(_status_url(world.period)).content.decode()

    assert "hx-trigger" not in html
    assert "hx-get" not in html
    assert "Calculated January 2024." in html
    assert "<li>First note.</li>" in html
    assert "<li>Second note.</li>" in html


def test_a_viewer_may_read_the_status_block(world, viewer):  # noqa: F811
    _request(world.period, status="queued")

    response = _client(viewer).get(_status_url(world.period))

    assert response.status_code == 200
    assert "Waiting to start." in response.content.decode()


def test_the_traceback_is_never_on_the_period_page(world, administrator):  # noqa: F811
    _request(
        world.period,
        status="failed",
        outcome="The calculation stopped at February 2024 with an error.",
        error_detail="ValueError: secret-trace-text",
        finished_at=datetime(2024, 4, 2, 3, 30, tzinfo=LOS_ANGELES),
    )

    page = _client(administrator).get(_detail_url(world.period))
    status = _client(administrator).get(_status_url(world.period))

    assert "secret-trace-text" not in page.content.decode()
    assert "secret-trace-text" not in status.content.decode()


# --------------------------------------------------------------------------
# A saved diversion record recalculates its month
# --------------------------------------------------------------------------


def _edit_january(world, operator, volume):  # noqa: F811
    record = DiversionRecord.objects.get(point_of_diversion=world.pod, month=JAN)
    return _client(operator).post(
        reverse("surface:diversion_record_edit", args=[world.pod.pk, record.pk]),
        {
            "month": "2024-01-01",
            "volume_acre_feet": volume,
            "returned_af": "0",
            "diversion_type": record.diversion_type,
        },
    )


def test_editing_a_diversion_record_moves_the_split_and_says_so(world, full_efficiency, operator):  # noqa: F811
    _run_months("2024-01")
    assert _split(JAN) == {"RA-B": Decimal("-10.0000"), "RA-C": Decimal("-10.0000")}

    response = _edit_january(world, operator, "12")

    assert response.status_code == 200
    saved = _saved("diversion_saved").get()
    assert saved.months == ["2024-01"]
    assert saved.status == "succeeded"
    assert saved.requested_by == operator
    assert saved.reporting_period == world.period
    assert _split(JAN) == {"RA-B": Decimal("-4.0000"), "RA-C": Decimal("-4.0000")}
    own = ParcelLedger.objects.get(pk=world.own.pk)
    assert own.amount_acre_feet == Decimal("-4.0000")  # field A's own record is never touched
    assert (
        "The fields this water serves are being recalculated for January 2024."
        in response.content.decode()
    )


def test_creating_a_diversion_record_recalculates_its_month(world, full_efficiency, operator):  # noqa: F811
    DiversionRecord.objects.filter(point_of_diversion=world.pod, month=FEB).delete()
    assert _split(FEB) == {}

    response = _client(operator).post(
        reverse("surface:diversion_record_create", args=[world.pod.pk]),
        {
            "month": "2024-02-01",
            "volume_acre_feet": "25",
            "returned_af": "0",
            "diversion_type": "direct_use",
        },
    )

    assert response.status_code == 200
    assert _saved("diversion_saved").get().months == ["2024-02"]
    split = _split(FEB)
    assert sorted(split) == ["RA-A", "RA-B", "RA-C"]
    assert sum(split.values()) == Decimal("-25.0000")
    assert (
        "The fields this water serves are being recalculated for February 2024."
        in response.content.decode()
    )


def test_deleting_a_diversion_record_clears_the_months_divided_up_rows(world, full_efficiency, operator):  # noqa: F811
    _run_months("2024-01")
    assert _split(JAN) == {"RA-B": Decimal("-10.0000"), "RA-C": Decimal("-10.0000")}
    record = DiversionRecord.objects.get(point_of_diversion=world.pod, month=JAN)
    # A metered canal: without a meter, a month with no record left would get
    # a delivery estimated from its fields' crop water use instead
    # (tests/test_diversion_estimate.py).
    PointOfDiversionDevice.objects.create(
        point_of_diversion=world.pod,
        device=MeasuringDevice.objects.create(
            nickname="Gate meter", device_type="inline_flow_meter"
        ),
    )

    response = _client(operator).post(
        reverse("surface:diversion_record_delete", args=[world.pod.pk, record.pk])
    )

    assert response.status_code == 200
    assert not DiversionRecord.objects.filter(pk=record.pk).exists()
    assert _saved("diversion_saved").get().months == ["2024-01"]
    assert _split(JAN) == {}
    own = ParcelLedger.objects.get(pk=world.own.pk)
    assert own.amount_acre_feet == Decimal("-4.0000")
    assert (
        "The fields this water serves are being recalculated for January 2024."
        in response.content.decode()
    )


def test_a_diversion_save_into_a_finalized_period_is_refused_and_starts_nothing(world, operator):  # noqa: F811
    _finalize(world.period)

    response = _edit_january(world, operator, "12")

    html = response.content.decode()
    assert response.status_code == 200
    assert finalized_message("Winter 2024") in html
    assert "being recalculated" not in html
    record = DiversionRecord.objects.get(point_of_diversion=world.pod, month=JAN)
    assert record.volume_acre_feet == Decimal("30.0000")
    assert CalculationRequest.objects.count() == 0


def test_a_diversion_import_recalculates_the_months_it_created(world, full_efficiency, operator):  # noqa: F811
    DiversionRecord.objects.filter(point_of_diversion=world.pod).delete()
    # The state layout names the water right; the whole-file point must be on it.
    world.pod.water_right = WaterRightFactory(right_id="A001885")
    world.pod.status = "active"
    world.pod.save()
    rows = [
        {
            "APPL_ID": "A001885",
            "WATER_RIGHT_ID": "283",
            "YEAR": "2024",
            "MONTH": str(month),
            "MONTH NAME": name,
            "MONTH FORMATTED": f"{month}/1/2024",
            "DIVERSION_TYPE": "DIRECT",
            "AMOUNT": amount,
            "calendar_month": f"2024-{month:02d}",
        }
        for month, name, amount in ((1, "January", "30"), (2, "February", "25"))
    ]

    response = _client(operator).post(
        reverse("surface:diversion_import_commit"),
        {
            "rows_json": json.dumps(rows),
            "point": str(world.pod.pk),
            "method": "",
            "data_state": "provisional",
        },
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert DiversionRecord.objects.filter(point_of_diversion=world.pod).count() == 2
    assert _saved("diversion_saved").get().months == ["2024-01", "2024-02"]
    assert (
        "The fields this water serves are being recalculated for January 2024 "
        "through February 2024." in html
    )
    assert _split(JAN) == {"RA-B": Decimal("-10.0000"), "RA-C": Decimal("-10.0000")}


# --------------------------------------------------------------------------
# A saved delivery row recalculates its month
# --------------------------------------------------------------------------


def test_a_hand_entered_delivery_row_recalculates_its_month(world, full_efficiency, operator):  # noqa: F811
    _run_months("2024-01")
    assert _split(JAN) == {"RA-B": Decimal("-10.0000"), "RA-C": Decimal("-10.0000")}

    response = _client(operator).post(
        reverse("accounting:ledger_create"),
        {
            "parcel": world.b.pk,
            "transaction_date": "2024-01-15",
            "effective_date": "2024-01-15",
            "amount_acre_feet": "-3.0000",
            "source_type": "surface_diversion",
            "description": "",
        },
        follow=True,
    )

    html = response.content.decode()
    assert response.redirect_chain == [(reverse("accounting:ledger_list"), 302)]
    assert "Entry saved." in html
    assert (
        "The fields this water serves are being recalculated for January 2024."
        in html
    )
    assert _saved("ledger_saved").get().months == ["2024-01"]
    # Field B now has a record of its own, so it takes no part of the split.
    assert _split(JAN) == {"RA-C": Decimal("-10.0000")}


def test_a_hand_entered_row_of_another_kind_starts_nothing(world, operator):  # noqa: F811
    response = _client(operator).post(
        reverse("accounting:ledger_create"),
        {
            "parcel": world.b.pk,
            "transaction_date": "2024-01-15",
            "effective_date": "2024-01-15",
            "amount_acre_feet": "-3.0000",
            "source_type": "manual_entry",
            "description": "",
        },
        follow=True,
    )

    assert "being recalculated" not in response.content.decode()
    assert CalculationRequest.objects.count() == 0


def test_an_imported_delivery_row_recalculates_its_month(world, full_efficiency, operator):  # noqa: F811
    csv_text = (
        "parcel_number,effective_date,amount_acre_feet,source_type\n"
        "RA-B,2024-01-15,-3.0000,surface_diversion\n"
    )

    response = _client(operator).post(
        reverse("accounting:csv_upload"),
        {"file": SimpleUploadedFile("deliveries.csv", csv_text.encode())},
        HTTP_HX_REQUEST="true",
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert (
        "The fields this water serves are being recalculated for January 2024."
        in html
    )
    assert _saved("ledger_saved").get().months == ["2024-01"]


def test_a_dry_run_import_starts_nothing(world, operator):  # noqa: F811
    csv_text = (
        "parcel_number,effective_date,amount_acre_feet,source_type\n"
        "RA-B,2024-01-15,-3.0000,surface_diversion\n"
    )

    response = _client(operator).post(
        reverse("accounting:csv_upload"),
        {
            "file": SimpleUploadedFile("deliveries.csv", csv_text.encode()),
            "dry_run": "on",
        },
        HTTP_HX_REQUEST="true",
    )

    assert "being recalculated" not in response.content.decode()
    assert CalculationRequest.objects.count() == 0


# --------------------------------------------------------------------------
# The helper the save hooks share
# --------------------------------------------------------------------------


def test_finalized_months_are_dropped_and_the_rest_grouped_by_period(world, operator):  # noqa: F811
    ReportingPeriodFactory(
        name="Summer 2023",
        start_date=date(2023, 6, 1),
        end_date=date(2023, 12, 31),
        is_finalized=True,
    )

    created = request_for_months(
        "diversion_saved",
        ["2023-12", "2024-02", "2024-01", "2025-05"],
        requested_by=operator,
    )

    assert [(r.reporting_period_id, r.months) for r in created] == [
        (world.period.pk, ["2024-01", "2024-02"]),
        (None, ["2025-05"]),
    ]
    assert CalculationRequest.objects.count() == 2
    assert {r.trigger for r in CalculationRequest.objects.all()} == {"diversion_saved"}


def test_only_finalized_months_means_no_request(world, operator):  # noqa: F811
    _finalize(world.period)

    created = request_for_months("diversion_saved", ["2024-01"], requested_by=operator)

    assert created == []
    assert CalculationRequest.objects.count() == 0
