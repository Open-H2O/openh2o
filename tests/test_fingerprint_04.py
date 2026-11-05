# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finalized year's fingerprint (151.7-04).

Finalizing computes a code from every record, figure and Change history entry of
the year (``core/fingerprint.py``); the water year page shows it with Download and
Check; Check computes it again and says whether the year is the same as when the
code was taken. The tests work on the hand-checked district D1
(``tests/ledger_districts.py``), whose July to September 2025 months sit in
WY 2024-2025. Literal sentences and counts are written out here, never read back
from the code under test.

* (a) the digest is stable across two computations and equals the stored code;
* (b) one digit of a meter reading, by raw SQL under the recorded door, changes the
  digest and Check for changes says to look at meter readings;
* (c) a correction through the correct route changes the digest and Check for changes
  counts it; a correction a figure moved for links to the Figures as filed card;
* (d) finalizing sets the three fields; ``record_fingerprints`` sets them on a year
  already finalized, once, and leaves a code alone;
* (e) the download names the parts with the counts the digest used and prints the
  short and the full code; its wording is the approved page's, byte for byte;
* (f) voided and replaced rows are in the digest;
* (g) a Viewer reads the line, downloads and presses Check;
* (h) the covered tables are the locked tables plus the correction registry;
* (i) a use area's acres edited in an open year leave "No changes found", voiding it does not;
* (j) ending a running fallow period leaves "No changes found", any other change does not;
* (k) a later-added column is ignored, a vanished column or table is "can no longer
  read" and never a difference;
* (l) a correction touching no use area (a water level) links the count to Change history;
* (m) a demonstration load answers "No changes found" at once;
* (n) a stored code changed by hand is answered as disagreeing with its parts;
* (o) on the six tables the demonstration has no rows for, the rule agrees with the lock;
* finalizing then Check for changes, through the real views, answers "No changes found" (the
  context row's metadata may not move under the code); a reopened year shows no card.

The screen words are the approved drawing's (rulings 86 and 87); ``tests/test_year_changes_05.py``
holds the card, the answers and the logic behind them.
"""
import copy
import datetime as dt
import re
from decimal import Decimal as D
from html import unescape
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.locks import override
from accounting.models import ReportingPeriod, ReportingPeriodEvent
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db

User = get_user_model()

HX = {"HTTP_HX_REQUEST": "true"}
REASON = "Typed 30 for 20; the meter photo shows 20."
PINNED = dt.datetime(2025, 10, 15, 19, 0, tzinfo=dt.timezone.utc)
TAKEN = "Oct 15, 2025"
NO_CHANGES = f"No changes found since {TAKEN}."
UNRECORDED = "Changes found with no correction on record."
FORBIDDEN = ("tamper", "audit", "evidence", "proof", "certified", "attestation", "sworn", "verify")

PART_NAMES = [
    "Use ledger", "Account use areas", "Allocations", "Water credits", "Water credit draws",
    "Carry-over", "Account credits", "Calculation results", "Diversion records",
    "Unallocated deliveries", "Canal losses", "Meter readings", "Water levels",
    "Recharge events", "Recharge measurements", "Fallow periods", "Station readings",
    "Production records", "Lab results", "Filed figures records", "Figures as filed",
    "Use areas", "Change history",
]


def fp():
    from core import fingerprint

    return fingerprint


# -- Setup -------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _quiet(settings):
    settings.ACCESS_CONTROL_ENFORCED = True
    with mock.patch("accounting.engine_run.start_calculation"):
        yield


def _user(username, **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="a-good-passw0rd",
        is_active=True, **flags,
    )


@pytest.fixture
def administrator():
    return _user("filer", agency_admin=True, first_name="Rae", last_name="Ortiz")


@pytest.fixture
def operator():
    return _user("operator", first_name="Jose", last_name="Lopez")


@pytest.fixture
def viewer():
    return _user("reader", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _meter_field(tag, lon, readings):
    """A 100-acre field on its own well and totalizer, with dated reads, oldest first."""
    from measurements.models import Meter, MeterReading
    from wells.models import WellMeter

    well = ld.make_well(f"W-{tag}", lon, 37.2)
    meter = Meter.objects.create(serial_number=f"FP-{tag}", meter_type="totalizer", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    field = ld.add_field(
        f"FP-{tag}", 100, "Alfalfa", None, [], lon, 37.2,
        [{"2025-07": "26.99522", "2025-08": "26.99522"}], well,
    )
    rows, previous = [], None
    for day, value in readings:
        rows.append(
            MeterReading.objects.create(
                meter=meter,
                reading_date=timezone.make_aware(dt.datetime(day.year, day.month, day.day, 12, 0)),
                previous_value=previous, current_value=D(value),
                calculated_volume=None if previous is None else D(value) - previous,
            )
        )
        previous = D(value)
    return field, rows


@pytest.fixture
def d1():
    """D1 calculated, plus three meter reads and one water level in the year, all still open."""
    from measurements.models import WaterMeasurement

    ld.seed_reference()
    built = ld.build_d1()
    ld.run_months(["2025-07", "2025-08", "2025-09"])
    field, reads = _meter_field(
        "A", -120.55,
        [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412"), (dt.date(2025, 8, 31), "1442")],
    )
    level = WaterMeasurement.objects.create(
        name="Level", measurement_type="flow", unit="ft",
        measurement_date=timezone.make_aware(dt.datetime(2025, 3, 1, 12, 0)), value=D("5"),
    )
    return {**built, "field": field, "reads": reads, "level": level}


@pytest.fixture
def year(d1):
    return ReportingPeriod.objects.get(name="WY 2024-2025")


def _finalize(client, period):
    response = client.post(reverse("accounting:period_finalize", args=[period.pk]), {})
    assert response.status_code == 302
    period.refresh_from_db()
    assert period.is_finalized


def _reopen(client, period):
    response = client.post(
        reverse("accounting:period_finalize", args=[period.pk]),
        {"note": "Reopened to record the corrected July reading."},
    )
    assert response.status_code == 302
    period.refresh_from_db()
    assert not period.is_finalized


def _pin(period):
    """Make the code read as taken Oct 15, 2025, whatever day the suite runs."""
    ReportingPeriod.objects.filter(pk=period.pk).update(fingerprint_at=PINNED)
    period.refresh_from_db()


@pytest.fixture
def filed(year, administrator):
    """WY 2024-2025 finalized through the real view, its code pinned to Oct 15, 2025."""
    _finalize(_client(administrator), year)
    _pin(year)
    return year


def _check_url(period):
    return reverse("accounting:period_fingerprint_check", args=[period.pk])


def _file_url(period):
    return reverse("accounting:period_fingerprint_file", args=[period.pk])


def _answer_html(client, period):
    response = client.post(_check_url(period), **HX)
    assert response.status_code == 200
    found = re.search(r'<p class="[^"]*" id="fingerprint-answer" role="status"[^>]*>(.*?)</p>',
                      response.content.decode(), re.S)
    assert found, response.content.decode()
    return found.group(1)


def _answer(client, period):
    return unescape(re.sub(r"<[^>]+>", "", _answer_html(client, period)))


def _meter_sql(period_unused=None, sql="UPDATE measurements_meterreading SET current_value = current_value + 1"):
    with override("a test of the recorded door"):
        with connection.cursor() as cursor:
            cursor.execute(sql)


def _correct_july(d1, administrator):
    """Correct F1's July meter-reading entry from -30 to -20 through the recorded door."""
    from accounting.engine_run import request_for_months
    from core.corrections import correct
    from parcels.models import ParcelLedger

    row = ParcelLedger.objects.current().get(
        parcel=d1["F1"], source_type="meter_reading", effective_date=dt.date(2025, 7, 1)
    )
    with override(REASON):
        months = correct(row, user=administrator, reason=REASON, changes={"amount_acre_feet": D("-20.0000")})
    request_for_months("record_corrected", months, requested_by=administrator, reason=REASON)
    return row


def _day(moment):
    local = timezone.localtime(moment, timezone.get_default_timezone())
    return f"{local:%b} {local.day}, {local.year}"


# -- The printed code ------------------------------------------------------------------------------


def test_the_printed_code_is_five_groups_of_four_from_the_first_twenty_characters():
    digest = "0ab101814eb93dfd02d4d77fe555b4f89bdbe7dfee873193a4b1048234ba9fba"
    assert fp().short_code(digest) == "0AB1-0181-4EB9-3DFD-02D4"
    assert re.fullmatch(r"[0-9A-F]{4}(-[0-9A-F]{4}){4}", fp().short_code("f" * 64))


def test_a_value_is_written_down_one_way_and_an_unknown_type_raises():
    f = fp()
    assert f.canonical((D("1.2300"), D("100"), D("0.0"), 1.5, None, True, "x")) == '["1.23","100","0",\"1.5\",null,true,"x"]'
    assert f.canonical((dt.date(2025, 3, 1), dt.datetime(2025, 3, 1, 12, 0, tzinfo=dt.timezone.utc))) == (
        '["2025-03-01","2025-03-01T12:00:00+00:00"]'
    )
    assert f.canonical(({"b": 1, "a": [D("2.50")]},)) == '[{"a":["2.5"],"b":1}]'
    with pytest.raises(TypeError):
        f.canonical((memoryview(b"x"),))


# -- (h) what is covered -----------------------------------------------------------------------------


def test_the_covered_tables_are_the_locked_tables_and_the_correction_registry():
    from accounting.locks import LOCKED_MODELS
    from core.corrections import KINDS

    covered = set(fp().COVERED_MODELS)
    registry = {kind["model"] for kind in KINDS.values()}
    assert covered == set(LOCKED_MODELS) | registry
    assert registry - set(LOCKED_MODELS) == {"parcels.Parcel"}
    assert len(covered) == 22
    links_and_settings = {
        "geography.ParcelZone", "geography.Zone", "accounting.WaterAccount", "wells.WellIrrigatedParcel",
        "wells.WellMeter", "surface.PointOfDiversionParcel", "core.SiteConfig",
    }
    assert not covered & links_and_settings
    assert [fp().PART_NAMES[key] for key in fp().PART_KEYS] == PART_NAMES


# -- (a) the digest ---------------------------------------------------------------------------------


def test_the_digest_is_stable_and_is_the_stored_code(d1, year, administrator):
    from parcels.models import ParcelLedger

    _finalize(_client(administrator), year)
    first, second = fp().compute(year), fp().compute(year)
    assert first.digest == second.digest == year.fingerprint
    assert re.fullmatch(r"[0-9a-f]{64}", year.fingerprint)
    assert [part["name"] for part in first.parts.values()] == PART_NAMES
    assert first.parts["measurements.MeterReading"]["rows"] == 3
    assert first.parts["measurements.WaterMeasurement"]["rows"] == 1
    assert first.parts["parcels.ParcelLedger"]["rows"] == ParcelLedger.objects.filter(
        effective_date__range=(year.start_date, year.end_date)
    ).count() > 0
    assert first.parts["parcels.Parcel"]["rows"] == 4
    assert first.parts["history"]["rows"] > 0


# -- (d) taking it -----------------------------------------------------------------------------------


def test_finalizing_sets_the_three_fields_and_reopening_keeps_them(year, administrator):
    assert (year.fingerprint, year.fingerprint_at, year.fingerprint_parts) == ("", None, {})
    client = _client(administrator)
    _finalize(client, year)
    assert re.fullmatch(r"[0-9a-f]{64}", year.fingerprint)
    assert year.fingerprint_at is not None
    stored = year.fingerprint_parts
    assert stored["version"] == 1
    assert set(stored) == {"version", "parts", "columns"}
    assert set(stored["parts"]) == set(fp().PART_KEYS)
    assert stored["columns"]["parcels.Parcel"] == [
        "id", "parcel_number", "voided_at", "voided_by_id", "void_reason", "replaced_at",
        "replaces_id", "change_reason",
    ]
    assert "parcels.ParcelLedgerEvent" in stored["columns"] and "pghistory.Context" in stored["columns"]
    assert "parcels.ParcelEvent" not in stored["columns"] and "parcels.FallowPeriodEvent" not in stored["columns"]
    for columns in stored["columns"].values():
        assert "geometry" not in columns and "boundary" not in columns

    code, at = year.fingerprint, year.fingerprint_at
    _reopen(client, year)
    assert (year.fingerprint, year.fingerprint_at) == (code, at)


def test_the_upgrade_command_fingerprints_a_finalized_year_once_and_leaves_a_code_alone(year):
    other = ReportingPeriod.objects.get(name="WY 2025-2026")
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    ReportingPeriod.objects.filter(pk=other.pk).update(is_finalized=True, fingerprint="a" * 64)
    open_year = ReportingPeriod.objects.create(
        name="WY 2026-2027", start_date=dt.date(2026, 10, 1), end_date=dt.date(2027, 9, 30)
    )

    call_command("record_fingerprints")

    year.refresh_from_db()
    assert re.fullmatch(r"[0-9a-f]{64}", year.fingerprint)
    assert year.fingerprint_parts["at_upgrade"] is True
    taken_at = year.fingerprint_at
    other.refresh_from_db()
    assert other.fingerprint == "a" * 64 and other.fingerprint_at is None
    open_year.refresh_from_db()
    assert open_year.fingerprint == ""

    events = ReportingPeriodEvent.objects.count()
    call_command("record_fingerprints")
    year.refresh_from_db()
    assert year.fingerprint_at == taken_at
    assert ReportingPeriodEvent.objects.count() == events


def test_a_year_fingerprinted_at_the_upgrade_answers_no_changes_found_at_once(year, administrator):
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    call_command("record_fingerprints")
    year.refresh_from_db()
    assert _answer(_client(administrator), year).startswith("No changes found since ")


def test_the_command_does_nothing_with_water_accounting_off():
    with mock.patch("core.modules.is_enabled", return_value=False):
        call_command("record_fingerprints")


# -- finalize, then Check: the context row's metadata must not move under the code ---------------------


def test_finalize_then_check_through_the_real_views_answers_no_changes_found(filed, administrator):
    client = _client(administrator)
    assert _answer(client, filed) == NO_CHANGES
    # And the answer is the same without scripts: the page, with the answer in place.
    page = client.post(_check_url(filed))
    assert page.status_code == 200
    body = page.content.decode()
    assert NO_CHANGES in unescape(body) and 'id="figures-as-filed"' in body


def test_finalize_with_a_note_then_check_answers_no_changes_found(year, administrator):
    client = _client(administrator)
    client.post(reverse("accounting:period_finalize", args=[year.pk]), {"note": "Finalized after the board vote."})
    year.refresh_from_db()
    assert year.is_finalized
    assert _answer(client, year).startswith("No changes found since ")


def test_refinalize_then_check_answers_no_changes_found(filed, administrator):
    client = _client(administrator)
    _reopen(client, filed)
    _finalize(client, filed)
    assert _answer(client, filed).startswith("No changes found since ")


def test_change_history_prints_the_code_and_when_and_not_what_it_read(filed, administrator):
    from core.changes import changes_for

    labels = {change.name for row in changes_for(filed) for change in row.changes}
    assert "Code" in labels
    assert "Code taken" in labels
    assert not any(label.startswith("Code parts") for label in labels)
    assert not any("ingerprint" in label for label in labels)


def test_check_writes_nothing(filed, administrator):
    before = ReportingPeriodEvent.objects.count()
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pghistory_context")
        contexts = cursor.fetchone()[0]
    _answer(_client(administrator), filed)
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pghistory_context")
        assert cursor.fetchone()[0] == contexts
    assert ReportingPeriodEvent.objects.count() == before


# -- (b) one digit ------------------------------------------------------------------------------------


def test_one_digit_of_a_meter_reading_changes_the_digest_and_names_the_part(filed, administrator):
    before = fp().compute(filed)
    _meter_sql(sql="UPDATE measurements_meterreading SET current_value = 1413.0000 WHERE current_value = 1412.0000")
    after = fp().compute(filed)
    assert after.digest != before.digest
    changed = [k for k in before.parts if before.parts[k]["digest"] != after.parts[k]["digest"]]
    assert changed == ["measurements.MeterReading", "history"]
    # Change history differs too and is not named: a direct edit leaves history behind.
    assert _answer(_client(administrator), filed) == f"{UNRECORDED} Look at: meter readings."


# -- (c) a correction ----------------------------------------------------------------------------------


def test_a_correction_through_the_route_changes_the_digest_and_check_lists_it(d1, filed, administrator):
    reading = d1["reads"][1]
    before = fp().compute(filed).digest
    response = _client(administrator).post(
        reverse("core:record_correct", args=["meter_reading", reading.pk]),
        {
            "reading_date": "2025-07-31", "current_value": "1142", "quality": "provisional",
            "reason": REASON,
        },
        **HX,
    )
    assert response.status_code == 200
    assert fp().compute(filed).digest != before
    answer = _answer(_client(administrator), filed)
    # Meter readings and Change history differ; the correction's own kind and history are explained.
    assert answer == f"1 correction since {TAKEN}."
    # The screen counts the correction; the Figures as filed card or Change history says which.


def test_a_correction_that_moved_a_figure_links_to_the_figures_as_filed_card(d1, filed, administrator):
    _correct_july(d1, administrator)
    html = _answer_html(_client(administrator), filed)
    assert f'<a href="#figures-as-filed" class="prose-link">1 correction</a> since {TAKEN}.' in html
    assert unescape(re.sub(r"<[^>]+>", "", html)) == f"1 correction since {TAKEN}."


# -- (f) struck rows are in --------------------------------------------------------------------------


def test_voided_and_replaced_rows_are_in_the_digest(d1, year, administrator):
    from core import corrections
    from measurements.models import MeterReading

    voided, replaced = d1["reads"][2], d1["reads"][1]
    corrections.void(voided, user=administrator, reason="Read from the wrong meter, voided.")
    corrections.correct(replaced, user=administrator, reason=REASON, changes={"current_value": D("1420")})
    _finalize(_client(administrator), year)

    part = fp().compute(year).parts["measurements.MeterReading"]
    assert MeterReading.objects.count() == 4
    assert MeterReading.objects.current().count() == 2
    assert part["rows"] == 4

    before = fp().compute(year)
    with connection.cursor() as cursor, override("a test of the recorded door"):
        cursor.execute("DELETE FROM measurements_meterreading WHERE id = %s", [voided.pk])
    after = fp().compute(year)
    assert after.parts["measurements.MeterReading"]["rows"] == 3
    assert after.parts["measurements.MeterReading"]["digest"] != before.parts["measurements.MeterReading"]["digest"]
    assert after.digest != before.digest


# -- (e) the download ----------------------------------------------------------------------------------


def test_the_download_names_the_parts_with_the_counts_the_digest_used(d1, filed, administrator):
    response = _client(administrator).get(_file_url(filed))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="changes-code-wy-2024-2025.txt"'
    text = response.content.decode()
    lines = text.splitlines()
    assert lines[0] == "Hand-calculation test district"
    assert lines[1] == "Changes to this year's records: water year WY 2024-2025"
    assert lines[2] == "(Oct 1, 2024 to Sep 30, 2025)"
    short = f"{filed.fingerprint[:20].upper()}"
    assert f"Code        {'-'.join(short[i:i + 4] for i in range(0, 20, 4))}" in lines
    assert f"Full code   {filed.fingerprint.upper()}" in lines
    assert f"Taken       {TAKEN}, when the year was finalized" in lines
    assert "Finalized   " + _day(filed.finalized_at) + " by R. Ortiz" in lines
    assert max(len(line) for line in lines) <= 76
    parts = fp().compute(filed).parts
    for key, part in parts.items():
        if part["rows"]:
            assert re.search(rf"{re.escape(part['name'])} +{part['rows']:,}(\s|$)", text), part["name"]
    assert re.search(r"Meter readings +3(\s|$)", text) and re.search(r"Water levels +1(\s|$)", text)
    assert "No rows in this year: Account use areas, Water credits, Water credit" in text
    assert "Check for changes runs inside OpenH2O, so it does not catch a change to the software." in text.replace("\n", " ")


def test_the_download_of_a_year_taken_at_the_upgrade_and_of_a_restated_year(year, administrator):
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    call_command("record_fingerprints")
    year.refresh_from_db()
    client = _client(administrator)
    text = client.get(_file_url(year)).content.decode()
    assert "Finalized   date not on record" in text
    assert (
        f"Taken       {_day(year.fingerprint_at)}, when OpenH2O began keeping these codes\n"
        "            and after the year was finalized. Changes before that date do\n"
        "            not show in this check.\n"
    ) in text

    first, first_at = year.fingerprint, year.fingerprint_at
    _reopen(client, year)
    _finalize(client, year)
    year.refresh_from_db()
    text = client.get(_file_url(year)).content.decode()
    assert f"Taken       {_day(year.fingerprint_at)}, when the year was finalized again" in text
    short = first[:20].upper()
    code = "-".join(short[i:i + 4] for i in range(0, 20, 4))
    # That first code was taken at the upgrade, not at a filing.
    assert f"First code  {code}, taken {_day(first_at)}" in text
    assert f"First code  {first.upper()}" in text
    assert "As filed" not in text
    body = unescape(re.sub(r"<[^>]+>", "", client.get(reverse("accounting:period_detail", args=[year.pk])).content.decode()))
    assert f"First code {code}, first taken {_day(first_at)}." in re.sub(r"\s+", " ", body)
    assert "as filed " + _day(first_at) not in body


APPROVED_PAGE = """Halvern Valley GSA
Changes to this year's records: water year WY 2024-2025
(Oct 1, 2024 to Sep 30, 2025)

Finalized   date not on record
Code        32A8-3722-E3A1-FE4C-0109
Full code   32A83722E3A1FE4C0109A0023F91C45E78056DBB3D4E14E49C8D2D9E9CD5901C
Taken       Nov 4, 2026, when OpenH2O began keeping these codes
            and after the year was finalized. Changes before that date do
            not show in this check.

What the code covers
OpenH2O computed the code from every row below as it stood when the code was
taken, records marked void or replaced included, and from every Change
history entry of those rows. For a use area with a record in the year, the
code reads its number and whether it was voided, not its acres or other
details. For a fallow period it reads the end month only up to the year's
end. Change history of use areas and fallow periods is left out. Nothing
else is covered: links and settings (which zone a use area is in, which well
serves it, account names, site settings), the stored OpenET figures, and
anything a later version of OpenH2O adds.

  Part                         Rows    Part                         Rows
  Use ledger                  1,057    Water levels                   20
  Account use areas              76    Recharge events                28
  Allocations                     8    Recharge measurements          84
  Carry-over                      3    Lab results                 7,957
  Account credits                28    Filed figures records           1
  Calculation results           912    Figures as filed            3,887
  Diversion records              84    Use areas                      76
  Canal losses                   76    Change history              3,888
  Meter readings                144

  No rows in this year: Water credits, Water credit draws, Unallocated
  deliveries, Fallow periods, Station readings, Production records.

How to check
1. Open the water year page for WY 2024-2025 in OpenH2O.
2. Compare the code on the page with the code on this file. Someone able to
   change the records could also change the code on the page; this file
   catches that. For a dispute, download this page again and compare the
   full code.
3. Press Check for changes. OpenH2O recomputes the code from the records
   now.
4. Read the answer. It gives the number of corrections recorded since, and
   names the parts to look at where changes have no correction on record. An
   unrecorded change in the corrected record's own part, or in a part a
   recalculation writes when the correction started one, reads as the
   correction alone. "Can no longer read" means a later version removed what
   a part was computed from.

"No changes found" means what the code covers is the same as when it was
taken. It does not show that the records were right. Check for changes runs
inside OpenH2O, so it does not catch a change to the software.

OpenH2O does not send this file anywhere. Keeping it is the organization's
choice.
"""


def test_the_download_reads_word_for_word_as_the_approved_page():
    from accounting import fingerprints
    from core.models import SiteConfig

    SiteConfig.objects.create(agency_name="Halvern Valley GSA")
    counts = [
        ("parcels.ParcelLedger", 1057), ("accounting.WaterAccountParcel", 76), ("accounting.AllocationPlan", 8),
        ("accounting.WaterCredit", 0), ("accounting.WaterCreditDraw", 0), ("accounting.AllocationCarryover", 3),
        ("accounting.AccountCredit", 28), ("accounting.CalculationRun", 912), ("surface.DiversionRecord", 84),
        ("surface.UnallocatedDelivery", 0), ("surface.CanalMonthLoss", 76), ("measurements.MeterReading", 144),
        ("measurements.WaterMeasurement", 20), ("recharge.RechargeEvent", 28), ("recharge.RechargeMeasurement", 84),
        ("parcels.FallowPeriod", 0), ("datasync.TypedReading", 0), ("drinking.SystemProduction", 0),
        ("drinking.SampleResult", 7957), ("accounting.PeriodStatement", 1), ("accounting.PeriodStatementRow", 3887),
        ("parcels.Parcel", 76), ("history", 3888),
    ]
    parts = {
        key: {"name": fp().PART_NAMES[key], "digest": "0" * 64, "rows": rows} for key, rows in counts
    }
    moment = dt.datetime(2026, 11, 4, 19, 0, tzinfo=dt.timezone.utc)
    # The drawn example: a code the upgrade took, on a year whose finalized date is not on record.
    period = ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30),
        is_finalized=True,
        fingerprint="32a83722e3a1fe4c0109a0023f91c45e78056dbb3d4e14e49c8d2d9e9cd5901c",
        fingerprint_at=moment,
        fingerprint_parts={"version": 1, "parts": parts, "columns": {}, "at_upgrade": True},
    )
    text = fingerprints.file_text(period).rstrip() + "\n"
    assert text == APPROVED_PAGE
    # One page: 57 lines, none wider than 76, and the old word nowhere.
    assert len(text.splitlines()) == 57
    assert max(len(line) for line in text.splitlines()) == 76
    assert "fingerprint" not in text.lower()
    assert fingerprints.file_name(period) == "changes-code-wy-2024-2025.txt"


# -- the line on the page ---------------------------------------------------------------------------------


def test_the_page_carries_the_card_as_drawn(filed, administrator):
    body = _client(administrator).get(reverse("accounting:period_detail", args=[filed.pk])).content.decode()
    code = "-".join(f"{filed.fingerprint[i:i + 4]}" for i in range(0, 20, 4)).upper()
    assert body.index("Allocations by water type</h2>") < body.index('id="fingerprint"') < body.index("Calculation</h2>")
    assert '<div class="card-raised page-grid-account-full" id="fingerprint">' in body
    assert f'Code <span class="text-mono">{code}</span>, taken {_day(filed.fingerprint_at)}' in body
    assert f'<a href="{_file_url(filed)}" class="text-link">Download a copy to keep</a>' in body
    assert f'hx-post="{_check_url(filed)}" hx-target="#fingerprint-answer" hx-swap="outerHTML"' in body
    assert '<button type="submit" class="btn-as-link text-link">Check for changes</button>' in body
    assert '<span id="fingerprint-answer"></span>' in body


def test_a_restated_year_shows_the_newest_code_and_the_first_beneath(filed, administrator):
    client = _client(administrator)
    first = filed.fingerprint
    _reopen(client, filed)
    _finalize(client, filed)
    _meter_sql(sql="UPDATE measurements_meterreading SET current_value = current_value + 1000 WHERE id = (SELECT max(id) FROM measurements_meterreading)")
    # A third finalize keeps the earliest code as the first.
    _reopen(client, filed)
    _finalize(client, filed)
    assert filed.fingerprint != first
    assert filed.fingerprint_parts["first"]["digest"] == first
    body = client.get(reverse("accounting:period_detail", args=[filed.pk])).content.decode()
    new = "-".join(filed.fingerprint[i:i + 4] for i in range(0, 20, 4)).upper()
    old = "-".join(first[i:i + 4] for i in range(0, 20, 4)).upper()
    start = body.index('id="fingerprint"')
    card = body[start : body.find('<div class="card-raised', start + 20)]
    assert f"taken {_day(filed.fingerprint_at)}" in card and "restated" not in card.lower()
    assert body.index(new) < body.index(old)
    assert f", as filed {TAKEN}." in body.split(old)[1][:80]


def test_a_reopened_year_shows_no_line_and_the_routes_answer_not_found(filed, administrator):
    client = _client(administrator)
    _reopen(client, filed)
    body = client.get(reverse("accounting:period_detail", args=[filed.pk])).content.decode()
    assert 'id="fingerprint"' not in body
    assert client.get(_file_url(filed)).status_code == 404
    assert client.post(_check_url(filed)).status_code == 404


def test_an_open_year_with_no_code_answers_not_found(year, administrator):
    client = _client(administrator)
    assert client.get(_file_url(year)).status_code == 404
    assert client.post(_check_url(year)).status_code == 404
    assert 'id="fingerprint"' not in client.get(reverse("accounting:period_detail", args=[year.pk])).content.decode()


def test_a_finalized_year_with_no_code_answers_not_found_and_shows_no_line(year, administrator):
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    client = _client(administrator)
    assert client.get(_file_url(year)).status_code == 404
    assert 'id="fingerprint"' not in client.get(reverse("accounting:period_detail", args=[year.pk])).content.decode()


# -- (g) a Viewer ----------------------------------------------------------------------------------------


def test_a_viewer_reads_the_card_downloads_and_checks(filed, viewer):
    client = _client(viewer)
    page = client.get(reverse("accounting:period_detail", args=[filed.pk]))
    assert page.status_code == 200 and 'id="fingerprint"' in page.content.decode()
    assert "Check for changes" in page.content.decode()
    assert client.get(_file_url(filed)).status_code == 200
    assert _answer(client, filed) == NO_CHANGES
    # Finalize stays an administrator's.
    assert client.post(reverse("accounting:period_finalize", args=[filed.pk]), {}).status_code == 403


# -- (i) a use area -------------------------------------------------------------------------------------------


def test_editing_a_use_areas_acres_leaves_no_changes_found_and_voiding_it_through_the_door_does_not(
    d1, filed, administrator
):
    from core import corrections
    from parcels.models import Parcel

    client = _client(administrator)
    Parcel.objects.filter(pk=d1["F1"].pk).update(area_acres=D("77.00"), notes="Edited in an open year of 2026.")
    assert _answer(client, filed) == NO_CHANGES

    with override("Voided: the use area was entered twice."):
        corrections.void(d1["F1"], user=administrator, reason="Voided: the use area was entered twice.")
    # The void is a correction of the use area's own kind, so it explains the Use areas part.
    assert _answer(client, filed) == f"1 correction since {TAKEN}."


def test_a_voided_use_area_in_an_account_leaves_the_figures_as_filed_card_readable(
    d1, filed, administrator
):
    """A voided use area keeps its account and zone links; the allocation share must not reach for its acres."""
    from core import corrections

    client = _client(administrator)
    with override("Voided: the use area was entered twice."):
        corrections.void(d1["F1"], user=administrator, reason="Voided: the use area was entered twice.")
    response = client.get(reverse("accounting:period_figures", args=[filed.pk]))
    assert response.status_code == 200


# -- (j) a fallow period ------------------------------------------------------------------------------------------


def test_ending_a_running_fallow_period_leaves_no_changes_found_and_any_other_change_does_not(d1, year, administrator):
    from parcels.models import FallowPeriod

    running = FallowPeriod.objects.create(parcel=d1["F4"], start_month=dt.date(2025, 8, 1))
    _finalize(_client(administrator), year)
    _pin(year)
    client = _client(administrator)
    assert _answer(client, year) == NO_CHANGES

    response = client.post(
        reverse("parcels:fallow_period_end_edit", args=[d1["F4"].pk]),
        {"end_month": "2025-11-10", "reason": "Ended when the crop went in."},
    )
    assert response.status_code in (200, 302)
    running.refresh_from_db()
    assert running.end_month == dt.date(2025, 11, 1)
    assert _answer(client, year) == NO_CHANGES

    with override("a test of the recorded door"):
        FallowPeriod.objects.filter(pk=running.pk).update(start_month=dt.date(2025, 9, 1))
    assert _answer(client, year) == f"{UNRECORDED} Look at: fallow periods."


# -- (k) a column or table that comes or goes ------------------------------------------------------------------------


def _restate(period, stored):
    """Store ``stored`` with the digests an older code would have written over its columns."""
    result = fp().compute(period, stored)
    assert not result.unreadable
    kept = {**stored, "parts": result.parts}
    ReportingPeriod.objects.filter(pk=period.pk).update(fingerprint=result.digest, fingerprint_parts=kept)
    period.refresh_from_db()
    return result


def test_a_column_added_later_is_ignored_by_an_older_code(filed, administrator):
    stored = copy.deepcopy(filed.fingerprint_parts)
    columns = stored["columns"]["measurements.MeterReading"]
    columns.remove("current_value")
    older = _restate(filed, stored)
    assert older.parts["measurements.MeterReading"]["digest"] != fp().compute(filed).parts[
        "measurements.MeterReading"
    ]["digest"]
    assert _answer(_client(administrator), filed) == NO_CHANGES


def test_a_table_added_later_is_ignored_by_an_older_code(filed, administrator):
    stored = copy.deepcopy(filed.fingerprint_parts)
    del stored["parts"]["recharge.RechargeEvent"]
    del stored["columns"]["recharge.RechargeEvent"]
    del stored["columns"]["recharge.RechargeEventEvent"]
    _restate(filed, stored)
    assert _answer(_client(administrator), filed) == NO_CHANGES


def test_a_stored_column_that_no_longer_exists_is_cannot_read_never_a_change(filed, administrator):
    stored = copy.deepcopy(filed.fingerprint_parts)
    stored["columns"]["measurements.MeterReading"].append("retired_column")
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint_parts=stored)
    answer = _answer(_client(administrator), filed)
    assert answer == (
        "OpenH2O can no longer read these parts: meter readings, change history, because a later "
        "version removed what they were computed from."
    )
    assert "Changes found" not in answer and "No changes found" not in answer


def test_a_stored_table_that_no_longer_exists_is_cannot_read_never_a_change(filed, administrator):
    stored = copy.deepcopy(filed.fingerprint_parts)
    stored["columns"]["measurements.RetiredTableEvent"] = ["pgh_id"]
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint_parts=stored)
    answer = _answer(_client(administrator), filed)
    assert answer == (
        "OpenH2O can no longer read the change history, because a later version removed what it "
        "was computed from."
    )


def test_an_unreadable_part_beside_a_real_difference_is_named_after_it(filed, administrator):
    stored = copy.deepcopy(filed.fingerprint_parts)
    stored["columns"]["measurements.RetiredTableEvent"] = ["pgh_id"]
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint_parts=stored)
    _meter_sql(sql="UPDATE measurements_meterreading SET current_value = 1413.0000 WHERE current_value = 1412.0000")
    answer = _answer(_client(administrator), filed)
    assert answer == (
        f"{UNRECORDED} Look at: meter readings. "
        "OpenH2O can no longer read the change history, because a later version removed what it "
        "was computed from."
    )


# -- (l) a correction that touches no use area ---------------------------------------------------------------------------


def test_a_correction_that_touches_no_use_area_links_the_count_to_change_history(d1, filed, administrator):
    from core.corrections import correct

    with override(REASON):
        correct(d1["level"], user=administrator, reason=REASON, changes={"value": D("6")})
    html = _answer_html(_client(administrator), filed)
    # The Figures as filed card lists no water level, so the count goes to Change history from the day taken.
    assert f'<a href="/changes/?from=2025-10-15" class="prose-link">1 correction</a> since {TAKEN}.' in html
    assert "#figures-as-filed" not in html


# -- (n) a code changed by hand ----------------------------------------------------------------------------------------------


def test_a_stored_code_changed_by_hand_is_answered_as_disagreeing_with_its_parts(filed, administrator):
    ReportingPeriod.objects.filter(pk=filed.pk).update(fingerprint="0" * 64)
    assert _answer(_client(administrator), filed) == "The stored code no longer agrees with its own parts."


# -- (m) the demonstration ----------------------------------------------------------------------------------------------------


def test_a_demonstration_load_answers_no_changes_found_at_once_and_leaves_no_water_year_history(
    monkeypatch, administrator
):
    from core import demonstration as demo
    from core.models import SiteConfig
    from tests import factories as f

    def small_year(stdout=None):
        f.BoundaryFactory(name=demo.DEMONSTRATION_BOUNDARY)
        SiteConfig.objects.create(agency_name=demo.DEMONSTRATION_NAME)
        ReportingPeriod.objects.create(
            name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30)
        )
        f.ParcelLedgerFactory(effective_date=dt.date(2025, 3, 1), transaction_date=dt.date(2025, 3, 1))
        ReportingPeriod.objects.update(is_finalized=True)
        call_command("record_filed_figures")

    monkeypatch.setattr(demo, "run_steps", small_year)
    demo.load()

    year = ReportingPeriod.objects.get(name="WY 2024-2025")
    assert re.fullmatch(r"[0-9a-f]{64}", year.fingerprint)
    assert year.fingerprint_parts["at_upgrade"] is True
    assert ReportingPeriodEvent.objects.count() == 0
    assert _answer(_client(administrator), year).startswith("No changes found since ")


# -- (o) the six tables the demonstration has no rows for ------------------------------------------------------------------------


INSIDE, OUTSIDE = dt.date(2025, 3, 1), dt.date(2026, 3, 1)


def _rows_for(label):
    """``[(row, intended_in_year)]`` for one table: the lock's own cases, inside and outside."""
    from accounting.models import WaterCredit, WaterCreditDraw
    from datasync.models import DataRecordStaging, TypedReading
    from drinking.models import SystemProduction
    from parcels.models import FallowPeriod
    from surface.models import UnallocatedDelivery
    from tests.factories import (
        MonitoredStationFactory,
        ParcelFactory,
        PointOfDiversionFactory,
        WaterSystemFactory,
    )

    def noon(day):
        return timezone.make_aware(dt.datetime(day.year, day.month, day.day, 12, 0))

    month = lambda day: f"{day.year}-{day.month:02d}"  # noqa: E731
    if label == "accounting.WaterCredit":
        return [
            (WaterCredit.objects.create(parcel=ParcelFactory(), origin_period=month(day), amount_af=D("2.5")), yes)
            for day, yes in ((INSIDE, True), (OUTSIDE, False), (dt.date(2024, 9, 1), False), (dt.date(2024, 10, 1), True))
        ]
    if label == "accounting.WaterCreditDraw":
        credit = WaterCredit.objects.create(parcel=ParcelFactory(), origin_period="2023-01", amount_af=D("2.5"))
        return [
            (WaterCreditDraw.objects.create(credit=credit, draw_period=month(day), amount_af=D("1")), yes)
            for day, yes in ((INSIDE, True), (OUTSIDE, False))
        ]
    if label == "surface.UnallocatedDelivery":
        return [
            (UnallocatedDelivery.objects.create(
                point_of_diversion=PointOfDiversionFactory(), reporting_period=None, month=day,
                amount_acre_feet=D("1"), delivery_acre_feet=D("5"),
            ), yes)
            for day, yes in ((INSIDE, True), (OUTSIDE, False))
        ]
    if label == "parcels.FallowPeriod":
        cases = [
            (INSIDE, INSIDE, True),
            (dt.date(2025, 8, 1), None, True),
            (None, dt.date(2025, 1, 1), True),
            (dt.date(2024, 1, 1), dt.date(2024, 3, 1), False),
            (dt.date(2025, 11, 1), None, False),
            (OUTSIDE, OUTSIDE, False),
        ]
        return [
            (FallowPeriod.objects.create(parcel=ParcelFactory(), start_month=start, end_month=end), yes)
            for start, end, yes in cases
        ]
    if label == "datasync.TypedReading":
        found = []
        for day, yes in ((INSIDE, True), (OUTSIDE, False)):
            station = MonitoredStationFactory()
            staged = DataRecordStaging.objects.create(
                data_source=station.data_source, station=station, raw_data={}, observation_date=noon(day),
                parameter_code="gage_height", statistic="", value=D("1"), status="published",
                published_at=noon(day),
            )
            found.append((TypedReading.objects.create(
                station=station, reading=staged, parameter_code="gage_height", observation_date=day, value=D("1"),
            ), yes))
        return found
    if label == "drinking.SystemProduction":
        cases = [
            (2025, 3, True), (2026, 3, False), (2024, 12, True), (2024, 9, False),
            (2025, None, True), (2026, None, False), (2024, None, False),
        ]
        return [
            (SystemProduction.objects.create(
                system=WaterSystemFactory(), year=year, month=m, type_code="GW",
                volume_as_reported=D("100"), unit_as_reported="G", provenance="typed",
            ), yes)
            for year, m, yes in cases
        ]
    raise AssertionError(label)


SIX = [
    "accounting.WaterCredit",
    "accounting.WaterCreditDraw",
    "surface.UnallocatedDelivery",
    "parcels.FallowPeriod",
    "datasync.TypedReading",
    "drinking.SystemProduction",
]


@pytest.mark.parametrize("label", SIX)
def test_the_rule_agrees_with_the_lock_on_a_table_the_demonstration_has_no_rows_for(label):
    from django.apps import apps

    ReportingPeriod.objects.create(name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30))
    rows = _rows_for(label)
    year = ReportingPeriod.objects.get(name="WY 2024-2025")
    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    year.refresh_from_db()
    table = apps.get_model(label)._meta.db_table
    selected = set(fp().selection(year, label).values_list("pk", flat=True))
    for row, intended in rows:
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f'UPDATE "{table}" SET id = id WHERE id = %s', [row.pk])
            refused = False
        except DatabaseError as exc:
            assert "is finalized" in str(exc)
            refused = True
        assert refused == intended == (row.pk in selected), (label, row.pk)

    # Serialization runs on real rows: nothing raises, and the part counts the year's rows.
    result = fp().compute(year)
    assert result.parts[label]["rows"] == sum(1 for _, intended in rows if intended)
    assert re.fullmatch(r"[0-9a-f]{64}", result.parts[label]["digest"])


# -- the words ---------------------------------------------------------------------------------------------------------------------


def test_no_forbidden_word_is_on_the_page_the_answers_or_the_file(d1, filed, administrator):
    client = _client(administrator)
    _meter_sql(sql="UPDATE measurements_meterreading SET current_value = 1413.0000 WHERE current_value = 1412.0000")
    _correct_july(d1, administrator)
    texts = [
        client.get(reverse("accounting:period_detail", args=[filed.pk])).content.decode(),
        _answer_html(client, filed),
        client.get(_file_url(filed)).content.decode(),
    ]
    for text in texts:
        low = text.lower()
        for word in FORBIDDEN:
            assert word not in low, word
        assert "court" not in low
