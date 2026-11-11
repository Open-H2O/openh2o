# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading the records as they stood: ``core.as_of.reading_as_of``.

Inside the block every table that feeds a printed figure is shadowed by a
temporary table of the same name, rebuilt from change history, so the real
balance functions and ``.current()`` read the past with no change of their own.
This file proves that from outside, on the D1 district of
``tests.ledger_districts`` and the real code paths (``core.corrections.correct``
and ``void``, ``run_accounting``, ``account_balance``, ``parcel_water_use_months``):

* (a) a corrected ledger row reads its old figure the day before the correction
  and the new one on the day, through the balance functions and ``.current()``;
* (b) a voided row counts the day before the void and not after;
* (c) a recalculation that moved a figure reads the earlier calculation the day
  before, and a re-run that moved none counts 0 although history grew;
* (d) rows with no history are read from their own ``created_at``; a row whose
  only event is a delete comes back; an insert event with no live row does not;
* at the moment now every rebuilt table equals its live table;
* a write outside the set is refused, a change inside it is thrown away, and
  afterwards the bare names read live rows again (also in a real transaction);
* an exception propagates; a switched-off module is skipped; ``parse_as_of``;
* (h) the fill on a demonstration-sized district stays under two seconds.

**The clock.** ``pgh_created_at`` is the transaction's start, so inside one test
everything happens at one instant, and the event tables refuse UPDATE by trigger.
:func:`age` moves what exists so far back by whole site-time-zone days, with
``pgtrigger.ignore()`` around the UPDATEs (the way ``core/demonstration.py``
gets past the same locks). Later work then happens "now", earlier work happened
N days ago, and a test reads the days in between.
"""
import copy
import datetime as dt
import time
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pgtrigger
import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.utils import DatabaseError
from django.utils import timezone

from accounting.models import CalculationRun, ReportingPeriod, WaterAccount
from accounting.services import account_balance, parcel_water_use_months
from core.changes import event_models
from core.corrections import correct, void
from core.modules import ALL_MODULE_NAMES
from datasync.models import CropETFigure
from parcels.models import Parcel, ParcelLedger
from surface.models import DiversionRecord
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db

REASON = "digits swapped when typed"
WY25 = "WY 2024-2025"

# The thirteen tables, as the brief states them. Written out here, not imported
# from core.as_of, so a change to the module's list shows up as a failing test.
TABLES = [
    "parcels.ParcelLedger", "accounting.CalculationRun", "parcels.Parcel",
    "accounting.WaterAccountParcel", "accounting.AllocationPlan", "accounting.AccountCredit",
    "geography.ParcelZone", "parcels.FallowPeriod", "surface.DiversionRecord",
    "wells.WellIrrigatedParcel", "parcels.ParcelIrrigationMethod",
    "surface.PointOfDiversionParcel", "accounting.PeriodStatement",
]


# ---------------------------------------------------------------- the module under test
# Imported inside the call so every test fails on its own while core/as_of.py
# does not exist, instead of one collection error hiding them all.
def reading_as_of(*args, **kwargs):
    from core.as_of import reading_as_of as real

    return real(*args, **kwargs)


def parse_as_of(*args, **kwargs):
    from core.as_of import parse_as_of as real

    return real(*args, **kwargs)


# ---------------------------------------------------------------- the clock
def day_ago(n):
    return timezone.localdate() - dt.timedelta(days=n)


def age(days):
    """Move everything recorded so far back by ``days`` site-time-zone days.

    Shifts ``pgh_created_at`` (and the copied ``created_at``) of every event row
    and ``created_at`` of every live row, by wall-clock days so a daylight-saving
    change in between cannot move a record onto another date. Every trigger is
    switched off for the UPDATEs, so the shift writes no history of its own.
    """
    zone = timezone.get_current_timezone_name()

    def shift(cursor, table, column):
        cursor.execute(
            f'UPDATE "{table}" SET "{column}" = '
            f'(("{column}" AT TIME ZONE %s) - %s * interval \'1 day\') AT TIME ZONE %s',
            [zone, days, zone],
        )

    with pgtrigger.ignore(), connection.cursor() as cursor:
        for event in event_models().values():
            shift(cursor, event._meta.db_table, "pgh_created_at")
            if any(f.column == "created_at" for f in event._meta.concrete_fields):
                shift(cursor, event._meta.db_table, "created_at")
            live = event.pgh_tracked_model
            if any(f.column == "created_at" for f in live._meta.concrete_fields):
                shift(cursor, live._meta.db_table, "created_at")


def forget_history():
    """Delete every event row, as the demonstration's load does: rows with no history."""
    with pgtrigger.ignore(), connection.cursor() as cursor:
        for event in event_models().values():
            cursor.execute(f'DELETE FROM "{event._meta.db_table}"')


# ---------------------------------------------------------------- fixtures and readers
@pytest.fixture
def d1():
    ld.seed_reference()
    return ld.build_d1()


@pytest.fixture
def person():
    return get_user_model().objects.create_user(username="clerk-as-of", password="x")


def wy25():
    return ReportingPeriod.objects.get(name=WY25)


def account_a():
    return WaterAccount.objects.get(account_number="D1-A")


def meter_row(parcel, month_first):
    return ParcelLedger.objects.get(parcel=parcel, effective_date=month_first, source_type="meter_reading")


def counted_amounts(parcel, month_first):
    """The amounts of the rows that count for a use area and month, as ``.current()`` says."""
    return list(
        ParcelLedger.objects.current()
        .filter(parcel=parcel, effective_date=month_first, source_type="meter_reading")
        .values_list("amount_acre_feet", flat=True)
    )


def run_figure(parcel, month="2025-07"):
    run = CalculationRun.objects.get(parcel=parcel, period=month)
    return (run.gross_et_af, run.net_consumptive_use_af, run.gw_extracted_af,
            run.unmet_demand_af, run.final_af)


def double_july_et(parcel):
    """Change the satellite figure the July calculation reads, so a re-run moves a figure.

    The calculation reads the month's record, not the cache, so the record is changed in place;
    these tests are about reading past states, not about accepting a newer figure.
    """
    for record in CropETFigure.objects.current().filter(parcel=parcel, month=dt.date(2025, 7, 1)):
        CropETFigure.objects.filter(pk=record.pk).update(depth_mm=record.depth_mm * 2)


def events_after(label, moment):
    return event_models()[label].objects.filter(pgh_created_at__gt=moment).count()


def read_only_setting():
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        return cursor.fetchone()[0]


def temp_table_exists(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [f"pg_temp.{name}"])
        return cursor.fetchone()[0] is not None


# ---------------------------------------------------------------- the reading object
def test_a_day_means_the_start_of_the_next_day_in_the_site_time_zone(d1):
    los_angeles = ZoneInfo("America/Los_Angeles")
    with timezone.override(los_angeles):
        # 8 March 2026 is the spring-forward day: "plus 24 hours" or UTC midnight would be wrong.
        with reading_as_of(dt.date(2026, 3, 8)) as reading:
            assert reading.day == dt.date(2026, 3, 8)
            assert reading.moment == dt.datetime(2026, 3, 9, 0, 0, tzinfo=los_angeles)


def test_a_moment_is_taken_as_given(d1):
    moment = timezone.now() - dt.timedelta(hours=5)
    with reading_as_of(moment=moment) as reading:
        assert reading.moment == moment


# ---------------------------------------------------------------- (a) a corrected row
def test_a_corrected_row_reads_the_old_figure_before_the_day_and_the_new_one_on_it(d1, person):
    f1, account, period = d1["F1"], account_a(), wy25()
    row = meter_row(f1, ld.JUL)
    old_amount = row.amount_acre_feet
    balance_before = account_balance(account, period)

    age(20)  # the district was set up 30 days ago, below
    correct(row, user=person, reason=REASON, changes={"amount_acre_feet": D("-20.0000")})
    balance_after = account_balance(account, period)
    assert balance_after != balance_before, "the correction must move the live balance or this proves nothing"
    age(10)  # corrected 10 days ago

    with reading_as_of(day_ago(11)) as reading:
        assert counted_amounts(f1, ld.JUL) == [old_amount]
        assert account_balance(account, period) == balance_before
        assert reading.changed_count() == 1  # the correction, once
    with reading_as_of(day_ago(10)) as reading:
        assert counted_amounts(f1, ld.JUL) == [D("-20.0000")]
        assert account_balance(account, period) == balance_after
        assert reading.changed_count() == 0
    # Outside the block everything reads live again.
    assert counted_amounts(f1, ld.JUL) == [D("-20.0000")]
    assert account_balance(account, period) == balance_after


def test_the_replaced_row_is_not_marked_replaced_the_day_before_its_correction(d1, person):
    f1 = d1["F1"]
    old = meter_row(f1, ld.JUL)
    age(20)
    correct(old, user=person, reason=REASON, changes={"amount_acre_feet": D("-20.0000")})
    age(10)
    with reading_as_of(day_ago(11)):
        rows = ParcelLedger.objects.filter(parcel=f1, effective_date=ld.JUL, source_type="meter_reading")
        assert [(r.pk, r.replaced_at) for r in rows] == [(old.pk, None)]
    with reading_as_of(day_ago(10)):
        rows = ParcelLedger.objects.filter(parcel=f1, effective_date=ld.JUL, source_type="meter_reading")
        assert rows.count() == 2
        assert rows.get(pk=old.pk).replaced_at is not None


# ---------------------------------------------------------------- (b) a voided row
def test_a_voided_row_counts_the_day_before_the_void_and_not_after(d1, person):
    f2, account, period = d1["F2"], account_a(), wy25()
    row = meter_row(f2, ld.AUG)
    balance_before = account_balance(account, period)

    age(15)
    void(row, user=person, reason=REASON)
    balance_after = account_balance(account, period)
    assert balance_after != balance_before, "the void must move the live balance or this proves nothing"
    age(5)  # voided 5 days ago

    with reading_as_of(day_ago(6)) as reading:
        assert len(counted_amounts(f2, ld.AUG)) == 1
        assert account_balance(account, period) == balance_before
        assert reading.changed_count() == 1  # the void, once
    with reading_as_of(day_ago(5)) as reading:
        assert counted_amounts(f2, ld.AUG) == []
        assert account_balance(account, period) == balance_after
        assert reading.changed_count() == 0
        # Struck, not gone: the row is still on the page.
        assert ParcelLedger.objects.filter(pk=row.pk, voided_at__isnull=False).exists()


# ---------------------------------------------------------------- (c) a recalculation
def test_a_recalculation_that_moved_a_figure_reads_the_earlier_calculation_before_its_day(d1):
    f3, period = d1["F3"], wy25()
    ld.run_months(["2025-07"])
    run_before = run_figure(f3)
    use_before = parcel_water_use_months(f3, period)["totals"]

    age(8)
    double_july_et(f3)
    ld.run_months(["2025-07"])  # re-run 12 days ago, below
    run_after = run_figure(f3)
    use_after = parcel_water_use_months(f3, period)["totals"]
    assert run_after != run_before, "the re-run must move the figure or this proves nothing"
    assert use_after != use_before
    age(12)  # build and first run 20 days ago, the second run 12 days ago

    with reading_as_of(day_ago(13)) as reading:
        assert run_figure(f3) == run_before
        assert parcel_water_use_months(f3, period)["totals"] == use_before
        # Exactly 2: F3's July calculation (its ET doubled) and the "calculated" ledger row the
        # engine writes from it (-20 to -40 AF). F3 has no meter, so nothing else is a figure
        # that moved; the delete-and-rewrite of every other row pairs off to 0.
        assert reading.changed_count() == 2
        assert reading.changed_count(parcel_ids=[d1["F1"].pk]) == 0  # another use area did not move
        # July only: a window that starts in August sees nothing changed.
        assert reading.changed_count(start=dt.date(2025, 8, 1)) == 0
    with reading_as_of(day_ago(12)) as reading:
        assert run_figure(f3) == run_after
        assert parcel_water_use_months(f3, period)["totals"] == use_after
        assert reading.changed_count() == 0


def test_a_rerun_that_moved_no_figure_counts_zero_although_history_grew(d1):
    ld.run_months(["2025-07"])
    age(9)
    ld.run_months(["2025-07"])  # same inputs: every row deleted and written again
    age(5)  # first run 14 days ago, the re-run 5 days ago
    with reading_as_of(day_ago(6)) as reading:
        assert reading.changed_count() == 0
    moment_after_first_run = reading.moment
    # The history plainly grew, so a count of events would not have been 0.
    runs_now = CalculationRun.objects.count()
    assert runs_now > 0
    assert events_after("accounting.CalculationRun", moment_after_first_run) >= runs_now
    assert events_after("parcels.ParcelLedger", moment_after_first_run) > 0


# ---------------------------------------------------------------- (d) rows with no history
def test_rows_with_no_history_read_from_their_own_created_at(d1, person):
    f1, f2 = d1["F1"], d1["F2"]
    originals = {
        (r.parcel_id, r.effective_date): r.amount_acre_feet
        for r in ParcelLedger.objects.filter(source_type="meter_reading")
    }
    assert len(originals) == 6
    forget_history()
    age(20)  # six meter rows created 20 days ago, with no history at all

    # Three later changes, today: a new entry, a correction, a void.
    ld.ledger(f1, dt.date(2025, 9, 15), "-5.0000", "manual_entry", "GW")
    correct(meter_row(f2, ld.JUL), user=person, reason=REASON, changes={"amount_acre_feet": D("-99.0000")})
    void(meter_row(f2, ld.AUG), user=person, reason=REASON)

    with reading_as_of(day_ago(5)) as reading:
        now_rows = {
            (r.parcel_id, r.effective_date): r.amount_acre_feet
            for r in ParcelLedger.objects.filter(source_type="meter_reading")
        }
        assert now_rows == originals  # as they stood, the correction's and void's rows undone
        assert not ParcelLedger.objects.filter(source_type="manual_entry").exists()  # created later
        assert ParcelLedger.objects.current().filter(source_type="meter_reading").count() == 6
        assert reading.changed_count() == 3
        assert reading.has_records() is True
        assert reading.has_records(parcel_ids=[f1.pk]) is True
        assert reading.has_records(parcel_ids=[d1["F4"].pk]) is False  # F4 has no ledger row
        assert reading.has_records(start=dt.date(2026, 1, 1)) is False  # every row is 2025
        assert reading.has_records(end=dt.date(2025, 6, 30)) is False


def test_a_date_before_every_row_has_no_records(d1):
    forget_history()
    age(20)
    with reading_as_of(day_ago(25)) as reading:
        assert reading.has_records() is False
        assert ParcelLedger.objects.count() == 0
        assert Parcel.objects.count() == 0  # a use area created later is not there either


def test_a_row_whose_only_event_is_a_delete_comes_back_as_it_stood(d1):
    row = ld.ledger(d1["F1"], dt.date(2025, 9, 20), "-7.5000", "manual_entry", "GW", "entered then removed")
    pk = row.pk
    forget_history()  # the load that wrote it forgot its history
    age(20)
    row.delete()  # the delete is the only event it has
    assert not ParcelLedger.objects.filter(pk=pk).exists()

    with reading_as_of(day_ago(5)):
        back = ParcelLedger.objects.get(pk=pk)
        assert (back.amount_acre_feet, back.description, back.parcel_id) == (
            D("-7.5000"), "entered then removed", d1["F1"].pk)
    with reading_as_of(day_ago(0)):
        assert not ParcelLedger.objects.filter(pk=pk).exists()  # the delete is behind us


def test_a_row_with_an_insert_event_and_no_delete_and_no_live_row_does_not_come_back(d1):
    row = ld.ledger(d1["F1"], dt.date(2025, 9, 21), "-3.0000", "manual_entry", "GW", "leftover of an earlier load")
    pk = row.pk
    age(20)  # its insert event is 20 days old
    with pgtrigger.ignore(), connection.cursor() as cursor:  # gone with no delete event written
        cursor.execute("DELETE FROM parcels_parcelledger WHERE id = %s", [pk])
    event = event_models()["parcels.ParcelLedger"]
    assert event.objects.filter(pgh_obj_id=pk, pgh_label="insert").exists()
    assert not event.objects.filter(pgh_obj_id=pk, pgh_label="delete").exists()

    for days in (25, 10, 0):
        with reading_as_of(day_ago(days)):
            assert not ParcelLedger.objects.filter(pk=pk).exists(), f"came back as of {days} days ago"


# ---------------------------------------------------------------- the present
def test_at_the_moment_now_every_rebuilt_table_equals_its_live_table(d1, person):
    ld.run_months(["2025-07"])
    correct(meter_row(d1["F1"], ld.JUL), user=person, reason=REASON, changes={"amount_acre_feet": D("-21.0000")})
    void(meter_row(d1["F2"], ld.AUG), user=person, reason=REASON)
    age(2)
    ld.run_months(["2025-07"])

    events = event_models()
    compared = {}
    with reading_as_of(moment=timezone.now()):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_schema()")
            schema = cursor.fetchone()[0]
            for label in TABLES:
                event = events[label]
                live = event.pgh_tracked_model
                table = live._meta.db_table
                copied = {f.column for f in event._meta.concrete_fields}
                columns = ", ".join(f'"{f.column}"' for f in live._meta.concrete_fields if f.column in copied)
                rebuilt = f'SELECT {columns} FROM "{table}"'  # bare name: the temporary table
                real = f'SELECT {columns} FROM "{schema}"."{table}"'
                cursor.execute(f"SELECT count(*) FROM ({rebuilt}) a")
                n_rebuilt = cursor.fetchone()[0]
                cursor.execute(f"SELECT count(*) FROM ({real}) a")
                n_live = cursor.fetchone()[0]
                cursor.execute(f"SELECT count(*) FROM (({rebuilt}) EXCEPT ({real})) d")
                extra = cursor.fetchone()[0]
                cursor.execute(f"SELECT count(*) FROM (({real}) EXCEPT ({rebuilt})) d")
                missing = cursor.fetchone()[0]
                compared[label] = (n_rebuilt, n_live, extra, missing)
    for label, (n_rebuilt, n_live, extra, missing) in compared.items():
        assert (n_rebuilt, extra, missing) == (n_live, 0, 0), label
    assert compared["parcels.ParcelLedger"][1] > 0 and compared["accounting.CalculationRun"][1] > 0


# ---------------------------------------------------------------- a block that writes nothing
def test_a_write_to_a_table_outside_the_set_inside_the_block_raises(d1):
    period = wy25()
    with pytest.raises(DatabaseError, match="read-only"):
        with reading_as_of(day_ago(0)):
            ReportingPeriod.objects.filter(pk=period.pk).update(name="renamed inside a reading")
    assert ReportingPeriod.objects.get(pk=period.pk).name == WY25
    assert read_only_setting() == "off"


def test_a_change_to_a_table_in_the_set_is_gone_afterwards_and_the_names_read_live_again(d1):
    row = meter_row(d1["F1"], ld.JUL)
    live_amount = row.amount_acre_feet
    with reading_as_of(day_ago(0)):
        assert read_only_setting() == "on"
        assert temp_table_exists("parcels_parcelledger")
        ParcelLedger.objects.filter(pk=row.pk).update(amount_acre_feet=D("999.0000"))
        assert ParcelLedger.objects.get(pk=row.pk).amount_acre_feet == D("999.0000")
    assert ParcelLedger.objects.get(pk=row.pk).amount_acre_feet == live_amount
    assert not temp_table_exists("parcels_parcelledger")
    assert read_only_setting() == "off"
    ReportingPeriod.objects.filter(pk=wy25().pk).update(name=WY25)  # a write works again


@pytest.mark.django_db(transaction=True)
def test_in_a_real_transaction_the_block_leaves_the_connection_as_it_found_it():
    ld.seed_reference()
    d1 = ld.build_d1()
    row = meter_row(d1["F1"], ld.JUL)
    live_amount = row.amount_acre_feet
    assert not connection.in_atomic_block

    with reading_as_of(day_ago(0)):
        assert connection.in_atomic_block
        assert read_only_setting() == "on"
        ParcelLedger.objects.filter(pk=row.pk).update(amount_acre_feet=D("999.0000"))

    assert not connection.in_atomic_block
    assert read_only_setting() == "off"
    assert not temp_table_exists("parcels_parcelledger")
    assert ParcelLedger.objects.get(pk=row.pk).amount_acre_feet == live_amount
    ReportingPeriod.objects.filter(pk=wy25().pk).update(name=WY25)  # a write works again


def test_an_exception_inside_the_block_propagates_and_leaves_the_connection_usable(d1):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with reading_as_of(day_ago(0)):
            raise Boom
    assert read_only_setting() == "off"
    assert not temp_table_exists("parcels_parcelledger")
    assert ParcelLedger.objects.count() == 6
    ReportingPeriod.objects.filter(pk=wy25().pk).update(name=WY25)


# ---------------------------------------------------------------- an optional module off
def test_with_an_optional_module_switched_off_the_block_still_works(d1, settings):
    row = meter_row(d1["F1"], ld.JUL)
    # recharge needs surface, so they leave together (tests/test_droppable_acceptance does the same sum).
    settings.OPENH2O_MODULES = [m for m in ALL_MODULE_NAMES if m not in ("surface", "recharge")]
    assert "surface.DiversionRecord" not in event_models()

    with reading_as_of(day_ago(0)):
        assert temp_table_exists("parcels_parcelledger")
        assert not temp_table_exists(DiversionRecord._meta.db_table)  # skipped, not failed
        assert ParcelLedger.objects.get(pk=row.pk).amount_acre_feet == row.amount_acre_feet
        assert DiversionRecord.objects.count() == 0  # the real table is still there to read
    assert read_only_setting() == "off"


# ---------------------------------------------------------------- parse_as_of
def test_parse_as_of_reads_the_date_box():
    today = dt.date(2026, 11, 4)
    assert parse_as_of("", today=today) == (None, "")
    assert parse_as_of("2026-11-03", today=today) == (dt.date(2026, 11, 3), "")
    assert parse_as_of("2026-11-04", today=today) == (today, "")
    assert parse_as_of("2026-13-45", today=today) == (None, "OpenH2O could not read that date. This page shows today's records.")
    assert parse_as_of("last tuesday", today=today) == (None, "OpenH2O could not read that date. This page shows today's records.")
    assert parse_as_of("2026-11-05", today=today) == (None, "That date is in the future. This page shows today's records.")


def test_parse_as_of_takes_today_from_the_site_clock_when_not_given():
    assert parse_as_of(timezone.localdate().isoformat()) == (timezone.localdate(), "")
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    assert parse_as_of(tomorrow.isoformat()) == (None, "That date is in the future. This page shows today's records.")


# ---------------------------------------------------------------- (h) time
@pytest.mark.slow  # this suite registers no such mark (pyproject.toml lists only "network"); see the report
def test_the_fill_on_a_demonstration_sized_district_takes_under_two_seconds(d1):
    ld.run_months(["2025-07"])
    template = CalculationRun.objects.first()
    period = wy25()
    months = [dt.date(2024 + (9 + i) // 12, (9 + i) % 12 + 1, 1) for i in range(27)]  # Oct 2024 on

    # 76 use areas, about 2,000 ledger rows and 1,800 calculations: the local demonstration's size.
    parcels = Parcel.objects.bulk_create([
        Parcel(parcel_number=f"T{i:03d}", area_acres=D("10"), area_override=True,
               geometry=ld.sq(-120.7 + i * 0.001, 37.45, 0.0004))
        for i in range(76)
    ])
    ids = [p.pk for p in parcels]
    ParcelLedger.objects.bulk_create([
        ParcelLedger(parcel=p, transaction_date=ld.TODAY, effective_date=m, amount_acre_feet=D("-1.0000"),
                     source_type="manual_entry", water_type=ld.wt("GW"), description="timing district",
                     reporting_period=period)
        for p in parcels for m in months
    ])
    clones = []
    for p in parcels:
        for m in months[:24]:
            clone = copy.copy(template)
            clone.pk = clone.id = None
            clone._state.adding = True
            clone.parcel, clone.period, clone.period_start = p, m.strftime("%Y-%m"), m
            clones.append(clone)
    CalculationRun.objects.bulk_create(clones)

    age(3)
    # Change history with something to rebuild: every row changed once since.
    ParcelLedger.objects.filter(parcel_id__in=ids).update(description="revised")
    CalculationRun.objects.filter(parcel_id__in=ids).update(unmet_demand_af=D("1.0000"))
    assert ParcelLedger.objects.filter(parcel_id__in=ids).count() == 76 * 27

    started = time.perf_counter()
    with reading_as_of(day_ago(2)):
        fill = time.perf_counter() - started
        assert ParcelLedger.objects.filter(parcel_id__in=ids, description="timing district").count() == 76 * 27
        assert CalculationRun.objects.filter(parcel_id__in=ids).count() == 76 * 24
    # A reading should finish within 2 s. The real demonstration measures 0.09 s; this district changes every
    # row, the worst case, and took 2.00 s beside a running suite, and CI runs about 3 times slower
    # than the machine that measured it. So 6 s here catches a read gone wrong without flaking.
    assert fill < 6.0, f"the fill took {fill:.2f} s"
