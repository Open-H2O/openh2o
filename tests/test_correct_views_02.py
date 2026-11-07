# SPDX-License-Identifier: AGPL-3.0-or-later
"""Correct this record: the screens (151.7-02, Builder B). ``tests/test_correct_02.py`` holds the data layer.

* (a) through the page an operator corrects an open-year meter read; the response holds the
  struck record, its line and the new row, the month's request is created with trigger
  ``record_corrected``, and the month reads the corrected value;
* (b) in a finalized year an operator is refused and nothing is written; an administrator
  succeeds through the recorded door (history rows carry ``override`` and the reason, the
  request carries ``override_reason``, the year stays finalized); a void in a finalized year
  works the same way;
* (e) the attached file is stored under a random name inside MEDIA_ROOT/corrections/, served by
  the view to a signed-in user under its own name, refused to an anonymous request, and an
  executable (or one renamed .png) is refused with the sentence;
* (h) a viewer is refused on GET and POST of Correct this record;
* (i) the route is a write page;
* (j) the menu: none on a voided, replaced or engine-written row, none on a use area; an
  administrator's finalized row holds Correct and Void and no Edit; an operator's holds nothing;
  the Finalized word sits in the year's header once and in no row;
* the entry form's Meter or estimate writes the read's quality; a correction that changes only
  that choice reads "now estimated"; the prefilled figure reads 39781.39; the finalized form's
  first line names the year and the months.
"""

import datetime as dt
import re
from decimal import Decimal as D
from unittest import mock

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import CalculationRequest, ReportingPeriod
from core import corrections
from core.access import is_write_page
from core.models import RecordAttachment
from core.reasons import REASON_SENTENCE
from measurements.models import MeterReading
from tests import ledger_districts as ld
from parcels.models import ParcelLedger
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
)
from tests.test_correct_02 import _pumped
from tests.test_current_records_01 import figure, meter_field, ref  # noqa: F401  (ref is a fixture)
from tests.test_void_01 import menu_of, well_with_reading

pytestmark = pytest.mark.django_db

User = get_user_model()

REASON = "typed an 8 for a 7 on the meter"
HX = {"HTTP_HX_REQUEST": "true"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _enforced_and_quiet(settings):
    settings.ACCESS_CONTROL_ENFORCED = True
    with mock.patch("accounting.engine_run.start_calculation"):
        yield


def _user(username, **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="a-good-passw0rd",
        is_active=True, **flags,
    )


@pytest.fixture
def operator():
    return _user("operator", first_name="Jose", last_name="Lopez")


@pytest.fixture
def boss():
    return _user("boss", first_name="Ana", last_name="Reyes", agency_admin=True)


@pytest.fixture
def viewer():
    return _user("viewer", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def url(kind, row):
    return reverse("core:record_correct", args=[kind, row.pk])


def post(client, row, kind="meter_reading", **data):
    data.setdefault("reason", REASON)
    return client.post(url(kind, row), data, **HX)


def text(response):
    return response.content.decode().replace("\xa0", " ")


def read_form(row, value, quality="provisional"):
    when = timezone.localtime(row.reading_date).date()
    return {"reading_date": when.isoformat(), "current_value": value, "quality": quality}


def three_reads(tag="VA"):
    return meter_field(
        tag, -120.55,
        [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412"), (dt.date(2025, 8, 31), "1442")],
    )


def well_of(rows):
    return rows[0].meter.wellmeter_set.first().well


def finalize_wy():
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)


# ------------------------------------------------------------------ (a) through the page
def test_an_operator_corrects_an_open_year_read_and_the_month_reads_the_new_value(ref, operator):
    x, x_rows = three_reads("VX")
    y, _ = meter_field(
        "VY", -120.50,
        [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1142"), (dt.date(2025, 8, 31), "1442")],
    )
    ld.run_months(["2025-07"])
    assert _pumped(x) != _pumped(y)
    old = x_rows[1]

    response = post(_client(operator), old, **read_form(old, "1142"))

    body = text(response)
    assert response.status_code == 200
    old.refresh_from_db()
    new = MeterReading.objects.get(replaces=old)
    assert f'<tr id="record-meter_reading-{old.pk}" class="record-void">' in body
    assert f'id="record-meter_reading-{new.pk}"' in body
    day = timezone.localtime(old.replaced_at)
    assert (
        f"Replaced {day:%b} {day.day}, {day.year} by J. Lopez, now 1,142.00: {REASON}." in body
    )
    assert (
        "Record corrected. OpenH2O recalculated Jul 2025 and Aug 2025; Aug 31 pumped is now 300.00." in body
    )
    # The new row sits directly above the struck one, and the year still counts 3 reads.
    assert body.index(f"record-meter_reading-{new.pk}") < body.index(f"record-meter_reading-{old.pk}")
    assert "3 reads" in body
    request = CalculationRequest.objects.get(trigger="record_corrected")
    assert request.months == ["2025-07", "2025-08"]
    assert request.override_reason == ""

    ld.run_months(request.months)
    assert figure(x, "2025-07") == figure(y, "2025-07")
    assert _pumped(x) == _pumped(y)


def test_a_bad_reason_or_no_change_writes_nothing_and_keeps_the_row_open(ref, operator):
    _field, rows = three_reads("VB")
    old = rows[1]
    client = _client(operator)

    short = text(post(client, old, reason="too short", **read_form(old, "1142")))
    assert REASON_SENTENCE in short
    assert 'class="row-editing record-void-form record-correct-form"' in short
    assert 'value="1142"' in short

    same = text(post(client, old, **read_form(old, "1412")))
    assert "Nothing was changed." in same

    assert not MeterReading.objects.filter(replaces=old).exists()
    assert CalculationRequest.objects.count() == 0


def test_a_lower_total_than_the_read_before_is_refused_beside_the_figure(ref, operator):
    _field, rows = three_reads("VL")
    old = rows[1]

    body = text(post(_client(operator), old, **read_form(old, "900")))

    assert "The reading is below the previous reading of 1,000.00." in body
    assert not MeterReading.objects.filter(replaces=old).exists()


def test_the_form_opens_under_the_record_prefilled_to_the_tables_places(ref, operator):
    _field, rows = meter_field(
        "VP", -120.55, [(dt.date(2025, 6, 30), "39761.62"), (dt.date(2025, 7, 31), "39781.3900")]
    )
    old = rows[1]
    client = _client(operator)

    opened = text(client.get(url("meter_reading", old), **HX))

    assert 'value="39781.39"' in opened
    assert "39781.3900" not in opened
    assert 'inputmode="decimal"' in opened
    assert f'id="record-meter_reading-{old.pk}" class="row-editing"' in opened
    assert f'id="menu-record-meter_reading-{old.pk}"' not in opened
    assert "Meter or estimate" in opened and "Read from the meter" in opened and "Estimated" in opened
    assert "Optional: a photo or PDF" in opened and "Save correction" in opened
    assert "is finalized" not in opened  # an open year's form has no first line

    closed = text(client.get(url("meter_reading", old) + "?cancel=1", **HX))
    assert "record-correct-form" not in closed
    assert f'id="menu-record-meter_reading-{old.pk}"' in closed


# ------------------------------------------------------------------ Meter or estimate
def test_the_entry_forms_choice_writes_the_reads_quality(ref, operator):
    well, reading = well_with_reading()
    client = _client(operator)
    page = client.get(reverse("wells:detail", args=[well.pk])).content.decode()
    assert "Meter or estimate" in page and "Read from the meter" in page and "Estimated" in page
    assert re.search(r'name="quality" value="provisional"[^>]*checked', page)

    add = reverse("wells:meter_reading_add", args=[well.pk])
    client.post(add, {"reading_date": "2026-10-31", "current_value": "17600", "quality": "estimated"})
    client.post(add, {"reading_date": "2026-11-30", "current_value": "17700"})

    reads = list(MeterReading.objects.filter(meter=reading.meter).order_by("reading_date"))
    assert [r.quality for r in reads] == ["provisional", "estimated", "provisional"]


def test_a_correction_that_changes_only_the_choice_reads_now_estimated(ref, operator):
    _field, rows = three_reads("VQ")
    old = rows[1]
    old.quality = "approved"
    old.save()

    body = text(post(_client(operator), old, **read_form(old, "1412", "estimated")))

    new = MeterReading.objects.get(replaces=old)
    assert new.quality == "estimated"
    assert f"by J. Lopez, now estimated: {REASON}." in body
    # Nothing else moved, so nothing recalculates and the one-time line says so.
    assert "Record corrected." in body and "recalculated" not in body
    assert CalculationRequest.objects.count() == 0


def test_an_unchanged_choice_keeps_an_approved_reads_quality(ref, operator):
    _field, rows = three_reads("VK")
    old = rows[1]
    old.quality = "approved"
    old.save()

    post(_client(operator), old, **read_form(old, "1142"))

    assert MeterReading.objects.get(replaces=old).quality == "approved"


# ------------------------------------------------------------------ (b) a finalized year
def test_an_operator_is_refused_in_a_finalized_year_and_nothing_is_written(ref, operator):
    _field, rows = three_reads("VF")
    finalize_wy()
    old = rows[1]
    client = _client(operator)

    opened = text(client.get(url("meter_reading", old), **HX))
    assert "Nothing was corrected. WY 2024-2025 is finalized. An administrator can correct or void a record in it." in opened
    assert "record-correct-form" not in opened

    refused = text(post(client, old, **read_form(old, "1142")))
    assert "Nothing was corrected. WY 2024-2025 is finalized." in refused
    assert not MeterReading.objects.filter(replaces=old).exists()
    assert MeterReading.objects.get(pk=old.pk).replaced_at is None
    assert CalculationRequest.objects.count() == 0


def test_an_administrator_corrects_through_the_door_with_their_own_reason(ref, boss):
    _field, rows = three_reads("VG")
    finalize_wy()
    old = rows[1]
    client = _client(boss)

    opened = text(client.get(url("meter_reading", old), **HX))
    assert "WY 2024-2025 is finalized. Saving recalculates Jul 2025 and Aug 2025." in opened

    body = text(post(client, old, **read_form(old, "1142")))

    new = MeterReading.objects.get(replaces=old)
    assert "Record corrected. OpenH2O recalculated Jul 2025 and Aug 2025" in body
    events = apps.get_model("measurements.MeterReadingEvent")
    for pk, label in ((new.pk, "insert"), (old.pk, "update")):
        found = events.objects.filter(pgh_obj_id=pk, pgh_label=label)
        assert found.exists()
        for event in found:
            assert event.pgh_context.metadata.get("override") is True
            assert event.pgh_context.metadata.get("reason") == REASON
    request = CalculationRequest.objects.get(trigger="record_corrected")
    assert request.override_reason == REASON
    assert ReportingPeriod.objects.get(name="WY 2024-2025").is_finalized is True
    # The door closes behind it: an operator still cannot touch the new row.
    again = text(post(_client(_user("op2")), new, **read_form(new, "1100")))
    assert "Nothing was corrected." in again


def test_a_void_in_a_finalized_year_is_an_administrators_and_an_operator_is_refused(ref, operator, boss):
    _field, rows = three_reads("VH")
    finalize_wy()
    first, second = rows[1], rows[2]
    void = lambda row: reverse("core:record_void", args=["meter_reading", row.pk])  # noqa: E731

    refused = text(_client(operator).post(void(first), {"void_reason": REASON}, **HX))
    assert "Nothing was voided." in refused
    assert MeterReading.objects.get(pk=first.pk).voided_at is None

    done = text(_client(boss).post(void(first), {"void_reason": REASON}, **HX))
    assert "Record voided." in done
    assert MeterReading.objects.get(pk=first.pk).voided_by == boss
    request = CalculationRequest.objects.get(trigger="record_voided")
    assert request.override_reason == REASON
    assert MeterReading.objects.get(pk=second.pk).voided_at is None


# ------------------------------------------------------------------ (e) the attached file
@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def test_the_file_is_stored_under_a_random_name_and_served_to_a_signed_in_user(ref, operator, media):
    _field, rows = three_reads("VE")
    old = rows[1]
    upload = SimpleUploadedFile("meter face.png", PNG, content_type="image/png")

    body = text(post(_client(operator), old, file=upload, **read_form(old, "1142")))

    new = MeterReading.objects.get(replaces=old)
    attachment = RecordAttachment.objects.get(kind="meter_reading", record_pk=new.pk)
    assert attachment.stored_path.startswith("corrections/")
    assert "meter" not in attachment.stored_path
    stored = media / attachment.stored_path
    assert stored.is_file() and stored.parent == media / "corrections"
    assert stored.read_bytes() == PNG
    assert (attachment.original_name, attachment.content_type, attachment.uploaded_by) == (
        "meter face.png", "image/png", operator,
    )
    link = reverse("core:record_attachment", args=[attachment.pk])
    assert f'<a href="{link}" class="text-link">Photo</a>.' in body

    served = _client(operator).get(link)
    assert served.status_code == 200
    assert "meter face.png" in served["Content-Disposition"]
    assert b"".join(served.streaming_content) == PNG

    anonymous = Client().get(link)
    assert anonymous.status_code == 302 and "login" in anonymous["Location"]


def test_a_pdf_gets_the_word_pdf(ref, operator, media):
    _field, rows = three_reads("VD")
    old = rows[1]
    upload = SimpleUploadedFile("page.pdf", b"%PDF-1.7\n" + b"0" * 20, content_type="application/pdf")

    body = text(post(_client(operator), old, file=upload, **read_form(old, "1142")))

    assert ">PDF</a>." in body


@pytest.mark.parametrize(
    "name,content",
    [("run.exe", b"MZ" + b"\x90" * 30), ("photo.png", b"MZ" + b"\x90" * 30), ("notes.txt", b"hello there")],
)
def test_an_executable_or_anything_that_is_not_a_photo_or_pdf_is_refused(
    name, content, ref, operator, media
):
    _field, rows = three_reads("VX" + name[:2])
    old = rows[1]

    body = text(post(_client(operator), old, file=SimpleUploadedFile(name, content), **read_form(old, "1142")))

    assert "Attach a photo or a PDF." in body
    assert not MeterReading.objects.filter(replaces=old).exists()
    assert RecordAttachment.objects.count() == 0
    assert not (media / "corrections").exists()


# ------------------------------------------------------------------ (h) and (i) a viewer
def test_a_viewer_is_refused_on_get_and_post_and_nothing_is_stored(ref, viewer, media):
    _field, rows = three_reads("VV")
    old = rows[1]
    client = _client(viewer)

    assert client.get(url("meter_reading", old), **HX).status_code == 403
    upload = SimpleUploadedFile("a.png", PNG, content_type="image/png")
    assert post(client, old, file=upload, **read_form(old, "1142")).status_code == 403
    assert not MeterReading.objects.filter(replaces=old).exists()
    assert RecordAttachment.objects.count() == 0


def test_the_correct_route_is_a_write_page():
    assert is_write_page("core:record_correct") is True
    assert is_write_page("core:record_attachment") is False


# ------------------------------------------------------------------ (j) the menu
def test_no_menu_on_a_voided_or_replaced_row_and_the_new_row_has_one(ref, operator):
    _field, rows = three_reads("VM")
    well = well_of(rows)
    page = reverse("wells:detail", args=[well.pk])
    gone, old = rows[2], rows[1]
    corrections.void(gone, user=operator, reason=REASON)
    post(_client(operator), old, **read_form(old, "1142"))
    new = MeterReading.objects.get(replaces=old)

    body = _client(operator).get(page).content.decode()

    assert f"menu-record-meter_reading-{gone.pk}" not in body
    assert f"menu-record-meter_reading-{old.pk}" not in body
    assert "Correct this record" in menu_of(body, "meter_reading", new)


def test_an_engine_row_and_a_use_area_have_no_correct(ref, operator):
    typed = ParcelLedgerFactory(source_type="manual_entry", effective_date=dt.date(2026, 9, 15))
    engine = ParcelLedgerFactory(source_type="calculated", effective_date=dt.date(2026, 9, 30))
    body = _client(operator).get(reverse("accounting:ledger_list") + "?period=").content.decode()
    assert "Correct this record" in menu_of(body, "ledger_entry", typed)
    assert f"menu-record-ledger_entry-{engine.pk}" not in body

    parcel = ParcelFactory()
    client = _client(operator)
    assert client.get(url("use_area", parcel), **HX).status_code == 404
    assert client.post(url("use_area", parcel), {"reason": REASON}, **HX).status_code == 404
    assert "Correct this record" not in client.get(reverse("parcels:detail", args=[parcel.pk])).content.decode()
    assert client.get(url("no_such_kind", parcel), **HX).status_code == 404


def test_a_ledger_entry_is_corrected_in_place_with_its_filters_kept(ref, operator):
    entry = ParcelLedgerFactory(
        source_type="manual_entry", effective_date=dt.date(2026, 9, 15), amount_acre_feet=D("-12.0000")
    )

    response = _client(operator).post(
        url("ledger_entry", entry),
        {
            "correct-effective_date": "2026-09-15", "correct-amount_acre_feet": "-21",
            "correct-water_type": entry.water_type_id or "", "correct-description": entry.description,
            "reason": REASON, "period": "", "water_type": "",
        },
        **HX,
    )

    body = text(response)
    assert response.status_code == 200
    assert f'<tr id="record-ledger_entry-{entry.pk}" class="record-void">' in body
    assert "by J. Lopez, now −21.00:" in body
    assert ParcelLedger.objects.current().filter(pk=entry.pk).count() == 0


def test_an_administrators_finalized_row_holds_correct_and_void_and_no_edit(operator, boss):
    pod_record = _finalized_record()
    page = reverse("surface:pod_detail", args=[pod_record.point_of_diversion_id])

    admin_body = _client(boss).get(page).content.decode()
    menu = menu_of(admin_body, "diversion_record", pod_record)
    assert menu.index("Correct this record") < menu.index('role="separator"') < menu.index("Void this record")
    assert "Edit" not in menu

    operator_body = _client(operator).get(page).content.decode()
    assert f"menu-record-diversion_record-{pod_record.pk}" not in operator_body


def test_the_finalized_word_is_in_the_year_header_once_and_in_no_row(operator, boss):
    record = _finalized_record()
    page = reverse("surface:pod_detail", args=[record.point_of_diversion_id])

    for user in (operator, boss):
        body = _client(user).get(page).content.decode()
        assert body.count("&middot; Finalized") == 1
        assert '<span class="text-tertiary">Finalized</span>' not in body


def test_a_diversion_record_is_corrected_in_a_finalized_year_by_an_administrator_only(operator, boss):
    record = _finalized_record()
    fields = {
        "month": "2024-03-01", "volume_acre_feet": "44.5", "returned_af": "0",
        "diversion_type": record.diversion_type, "method": record.method, "data_state": record.data_state,
    }

    refused = text(post(_client(operator), record, kind="diversion_record", **fields))
    assert "Nothing was corrected." in refused

    done = text(post(_client(boss), record, kind="diversion_record", **fields))
    assert "Record corrected." in done
    current = type(record).objects.current().get(point_of_diversion=record.point_of_diversion)
    assert current.volume_acre_feet == D("44.5000") and current.replaces_id == record.pk
    assert f'id="record-diversion_record-{record.pk}" class="record-void"' in done


def _finalized_record():
    """A diversion record written while its year was open, which is then finalized."""
    closed = ReportingPeriodFactory(
        name="Closed WY", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30)
    )
    record = DiversionRecordFactory(month=dt.date(2024, 3, 1), reporting_period=closed)
    ReportingPeriod.objects.filter(pk=closed.pk).update(is_finalized=True)
    return record
