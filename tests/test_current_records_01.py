# SPDX-License-Identifier: AGPL-3.0-or-later
"""The current-records rule: a voided record stays on file and counts nowhere.

``core/corrections.py`` holds the one rule (``.current()``) and the one way to
void (``void()``). These tests prove, per kind of record, that

* (a) ``current()`` leaves out a voided row and a replaced row on each of the
  eleven covered models, and the rows of a voided use area;
* (b) the engine and the totals read through it: take the figure, add a row, void
  it, run the same months again, and the figure equals the figure with no row at
  all (the baseline is built in the same test), the voided row still on file;
* (c) no calculation or total reads a covered model around the rule (a static
  guard with an allowlist of the reads that show voided rows on purpose);
* (h) Meter, SampleEvent and RechargeSite record their changes;
* (i) the table that says who made a change refuses DELETE, and nothing else.

The figures come from the hand-worked districts in ``tests.ledger_districts``.
"""

import ast
import csv
import datetime as dt
import io
import itertools
import pathlib
from decimal import Decimal as D

import pghistory
import pghistory.models as pghistory_models
import pgtrigger
import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.locks import PeriodFinalized
from accounting.models import AccountCredit, AllocationCarryover, CalculationRun, ReportingPeriod, WaterAccount
from accounting.services import parcel_balance
from core import corrections
from core.corrections import KINDS, AlreadyVoided, NotVoidable, void
from core.history import CONTEXT_LOCK_URI
from core.models import User
from datasync.models import DataRecordStaging, TypedReading
from drinking.models import SampleEventEvent, SystemProduction
from measurements.models import Meter, MeterEvent, MeterReading, WaterMeasurement
from parcels.models import FallowPeriod, Parcel, ParcelLedger
from recharge.models import RechargeMeasurement, RechargeSiteEvent
from surface.models import DiversionRecord
from wells.models import WellMeter

from . import ledger_districts as ld
from .factories import (
    DiversionRecordFactory,
    MonitoredStationFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    RechargeEventFactory,
    RechargeSiteFactory,
    SampleEventFactory,
    SampleResultFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

REASON = "typed on the wrong record"
_counter = itertools.count(1)


# ------------------------------------------------------------------ builders
def make_row(key):
    """One minimal row of the kind, standing alone."""
    n = next(_counter)
    now = timezone.now()
    if key == "meter_reading":
        meter = Meter.objects.create(serial_number=f"CR-M-{n}")
        return MeterReading.objects.create(meter=meter, reading_date=now, current_value=D("10"))
    if key == "water_level":
        return WaterMeasurement.objects.create(
            name=f"Level {n}", measurement_type="flow", unit="ft", measurement_date=now, value=D("5")
        )
    if key == "ledger_entry":
        return ParcelLedgerFactory()
    if key == "fallow_period":
        return FallowPeriod.objects.create(parcel=ParcelFactory(), start_month=dt.date(2025, 7, 1))
    if key == "use_area":
        return ParcelFactory()
    if key == "diversion_record":
        return DiversionRecordFactory()
    if key == "recharge_event":
        return RechargeEventFactory()
    if key == "recharge_measurement":
        return RechargeMeasurement.objects.create(
            recharge_site=RechargeSiteFactory(), measurement_date=now,
            measurement_type="flow_rate", value=D("1"), unit="cfs",
        )
    if key == "lab_result":
        return SampleResultFactory()
    if key == "production_record":
        return SystemProduction.objects.create(
            system=WaterSystemFactory(), year=2025, month=3, type_code="GW",
            volume_as_reported=D("100"), unit_as_reported="G", provenance="typed",
        )
    if key == "station_reading":
        station = MonitoredStationFactory()
        published = DataRecordStaging.objects.create(
            data_source=station.data_source, station=station, raw_data={},
            observation_date=now, parameter_code="gage_height", statistic="",
            value=D("1"), status="published", published_at=now,
        )
        return TypedReading.objects.create(
            station=station, reading=published, parameter_code="gage_height",
            observation_date=now.date(), value=D("1"),
        )
    raise AssertionError(key)


@pytest.fixture
def ref():
    ld.seed_reference()


@pytest.fixture
def person():
    return User.objects.create_user(username="clerk", password="x", is_active=True)


def figure(parcel, month):
    """What a use area shows for a month: its balance, its run, its rows that count."""
    run = CalculationRun.objects.filter(parcel=parcel, period=month).first()
    return (
        parcel_balance(parcel),
        None if run is None else (run.gw_extracted_af, run.net_consumptive_use_af),
        ParcelLedger.objects.current().filter(parcel=parcel).count(),
    )


def meter_field(tag, lon, readings):
    """A 100-acre field on its own well and totalizer, with ET in July and August 2025.

    ``readings`` is ``[(date, value), ...]`` oldest first, entered the way the
    entry form stores them: each keeps the reading before it and the change.
    """
    well = ld.make_well(f"W-{tag}", lon, 37.2)
    meter = Meter.objects.create(serial_number=f"CR-{tag}", meter_type="totalizer", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    field = ld.add_field(
        f"CR-{tag}", 100, "Alfalfa", None, [], lon, 37.2,
        [{"2025-07": "26.99522", "2025-08": "26.99522"}], well,
    )
    rows = []
    previous = None
    for day, value in readings:
        rows.append(
            MeterReading.objects.create(
                meter=meter,
                reading_date=timezone.make_aware(dt.datetime(day.year, day.month, day.day, 12, 0)),
                previous_value=previous,
                current_value=D(value),
                calculated_volume=None if previous is None else D(value) - previous,
            )
        )
        previous = D(value)
    return field, rows


# ------------------------------------------------------------------ (a) the rule
@pytest.mark.parametrize("key", list(KINDS))
def test_current_leaves_out_a_voided_row_and_a_replaced_row(key):
    model = KINDS[key].model_class()
    voided, replaced, replacer, kept = (make_row(key) for _ in range(4))
    model.objects.filter(pk=voided.pk).update(voided_at=timezone.now())
    model.objects.filter(pk=replacer.pk).update(replaces=replaced)

    counting = set(model.objects.current().values_list("pk", flat=True))

    assert voided.pk not in counting
    assert replaced.pk not in counting
    assert {replacer.pk, kept.pk} <= counting
    # The default manager still returns every row: pages show voided rows struck.
    assert {voided.pk, replaced.pk, replacer.pk, kept.pk} <= set(
        model.objects.values_list("pk", flat=True)
    )


def test_the_ledger_rows_of_a_voided_use_area_do_not_count():
    gone, stays = ParcelFactory(), ParcelFactory()
    on_gone = ParcelLedgerFactory(parcel=gone)
    on_stays = ParcelLedgerFactory(parcel=stays)
    Parcel.objects.filter(pk=gone.pk).update(voided_at=timezone.now())

    counting = set(ParcelLedger.objects.current().values_list("pk", flat=True))

    assert on_gone.pk not in counting
    assert on_stays.pk in counting
    assert ParcelLedger.objects.filter(pk=on_gone.pk).exists()


def test_the_ledger_rows_of_a_replaced_use_area_do_not_count():
    old, new = ParcelFactory(), ParcelFactory()
    on_old = ParcelLedgerFactory(parcel=old)
    Parcel.objects.filter(pk=new.pk).update(replaces=old)
    assert on_old.pk not in set(ParcelLedger.objects.current().values_list("pk", flat=True))


def test_a_fallow_period_that_is_voided_does_not_make_the_field_fallow():
    field = ParcelFactory()
    period = FallowPeriod.objects.create(parcel=field, start_month=dt.date(2025, 7, 1))
    assert field.is_fallow_in(dt.date(2025, 7, 1)) is True
    FallowPeriod.objects.filter(pk=period.pk).update(voided_at=timezone.now())
    assert field.is_fallow_in(dt.date(2025, 7, 1)) is False
    # and the same months can be marked fallow again
    FallowPeriod.objects.create(parcel=field, start_month=dt.date(2025, 7, 1))


def test_the_fallow_queryset_chains_current_in_either_order():
    field = ParcelFactory()
    FallowPeriod.objects.create(parcel=field, start_month=dt.date(2025, 7, 1), end_month=dt.date(2025, 7, 1))
    day = dt.date(2025, 7, 15)
    assert FallowPeriod.objects.covering(day).current().count() == 1
    assert FallowPeriod.objects.current().covering(day).count() == 1


# ------------------------------------------------------------------ (b) the figures
def test_a_voided_meter_reading_is_out_of_the_months_pumping(ref, person):
    field, _ = meter_field("A", -120.55, [(dt.date(2025, 6, 30), "1000")])
    ld.run_months(["2025-07"])
    baseline = figure(field, "2025-07")
    meter = Meter.objects.get(serial_number="CR-A")
    reading = MeterReading.objects.create(
        meter=meter, reading_date=timezone.make_aware(dt.datetime(2025, 7, 31, 12, 0)),
        previous_value=D("1000"), current_value=D("1030"), calculated_volume=D("30"),
    )
    ld.run_months(["2025-07"])
    assert figure(field, "2025-07") != baseline

    months = void(reading, user=person, reason=REASON)
    ld.run_months(["2025-07"])

    assert months == ["2025-07"]
    assert figure(field, "2025-07") == baseline
    assert MeterReading.objects.filter(pk=reading.pk, voided_by=person).exists()


def test_a_voided_reading_in_the_middle_of_a_run_is_figured_from_the_last_one_still_in_use(ref, person):
    # X has a wrong reading between two good ones; Y never had it.
    x, x_rows = meter_field(
        "X", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1030"), (dt.date(2025, 8, 31), "1060")]
    )
    y, _ = meter_field("Y", -120.50, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 8, 31), "1060")])
    for month in ("2025-07", "2025-08"):
        ld.run_months([month])
    assert figure(x, "2025-07") != figure(y, "2025-07")

    months = void(x_rows[1], user=person, reason=REASON)
    for month in ("2025-07", "2025-08"):
        ld.run_months([month])

    next_reading = MeterReading.objects.get(pk=x_rows[2].pk)
    assert next_reading.previous_value == D("1000.0000")
    assert next_reading.calculated_volume == D("60.0000")
    assert next_reading.current_value == D("1060.0000")  # what was typed never moves
    assert months == ["2025-07", "2025-08"]
    assert figure(x, "2025-07") == figure(y, "2025-07")
    assert figure(x, "2025-08") == figure(y, "2025-08")
    assert MeterReading.objects.filter(pk=x_rows[1].pk).exists()


def test_a_voided_person_entered_adjustment_leaves_the_balance(ref, person):
    d1 = ld.build_d1()
    ld.run_months(["2025-07"])
    baseline = figure(d1["F4"], "2025-07")
    row = ld.ledger(d1["F4"], dt.date(2025, 7, 1), "-5", "adjustment", "GW", "added by hand")
    ld.run_months(["2025-07"])
    assert figure(d1["F4"], "2025-07") != baseline

    void(row, user=person, reason=REASON)
    ld.run_months(["2025-07"])

    assert figure(d1["F4"], "2025-07") == baseline
    assert ParcelLedger.objects.filter(pk=row.pk).exists()


def test_a_voided_meter_row_no_longer_makes_the_field_metered(ref, person):
    d1 = ld.build_d1()
    ld.run_months(["2025-07"])
    baseline = figure(d1["F4"], "2025-07")
    row = ld.ledger(d1["F4"], dt.date(2025, 7, 1), "-3", "meter_reading", "GW", "typed meter reading")
    ld.run_months(["2025-07"])
    # metered: the engine writes no calculated row and the typed row is the use
    assert figure(d1["F4"], "2025-07") != baseline

    void(row, user=person, reason=REASON)
    ld.run_months(["2025-07"])

    assert figure(d1["F4"], "2025-07") == baseline
    assert ParcelLedger.objects.filter(pk=row.pk).exists()


def test_a_voided_fallow_period_gives_the_field_its_months_back(ref, person):
    d1 = ld.build_d1()
    ld.run_months(["2025-07"])
    baseline = figure(d1["F3"], "2025-07")
    period = FallowPeriod.objects.create(parcel=d1["F3"])
    ld.run_months(["2025-07"])
    assert figure(d1["F3"], "2025-07") != baseline

    void(period, user=person, reason=REASON)
    ld.run_months(["2025-07"])

    assert figure(d1["F3"], "2025-07") == baseline
    assert FallowPeriod.objects.filter(pk=period.pk).exists()


def test_a_voided_use_area_leaves_every_total_and_its_engine_rows(ref, person):
    d1 = ld.build_d1()
    months = ("2025-07", "2025-08", "2025-09")
    for month in months:
        ld.run_months([month])
    baseline = ld.zone_budget(d1["gsa"], "WY 2024-2025")["used"]
    extra = ld.add_field(
        "F5", 100, "Alfalfa", None, [d1["gsa"]], -120.47, 37.2,
        [dict(zip(months, (60.96, 60.96, 30.48)))], ld.make_well("W5", -120.445, 37.21),
    )
    for month in months:
        ld.run_months([month])
    assert ld.zone_budget(d1["gsa"], "WY 2024-2025")["used"] != baseline
    assert CalculationRun.objects.filter(parcel=extra).count() == 3

    void(extra, user=person, reason="imported twice by mistake")
    for month in months:
        ld.run_months([month])

    assert ld.zone_budget(d1["gsa"], "WY 2024-2025")["used"] == baseline
    assert CalculationRun.objects.filter(parcel=extra).count() == 0
    assert not ParcelLedger.objects.filter(parcel=extra, source_type="calculated").exists()
    assert Parcel.objects.filter(pk=extra.pk).exists()


def test_a_voided_use_area_has_its_months_figures_removed_when_the_month_runs_again(ref, person):
    field, _ = meter_field("V", -120.55, [(dt.date(2025, 6, 30), "1000")])
    ld.run_months(["2025-07"])
    assert CalculationRun.objects.filter(parcel=field).exists()
    void(field, user=person, reason="imported twice by mistake")
    ld.run_months(["2025-07"])
    assert not CalculationRun.objects.filter(parcel=field).exists()


def test_a_voided_diversion_record_comes_off_the_delivery(ref, person):
    well = ld.make_well("WD", -120.55, 37.2)
    field = ld.add_field("CR-D", 100, "Alfalfa", None, [], -120.55, 37.2, [{"2025-07": "26.99522"}], well)
    point = ld.make_point("D headgate", -120.5, 37.15, None, "0", "0", "0", [(field, "1")])
    ld.run_months(["2025-07"])
    baseline = figure(field, "2025-07")
    record = ld.typed_record(point, dt.date(2025, 7, 1), "4.0000")
    ld.run_months(["2025-07"])
    assert figure(field, "2025-07") != baseline

    months = void(record, user=person, reason=REASON)
    ld.run_months(["2025-07"])

    assert months == ["2025-07"]
    assert figure(field, "2025-07") == baseline
    assert DiversionRecord.objects.filter(pk=record.pk).exists()


def test_a_voided_recharge_event_takes_its_credit_back(ref, person):
    d3 = ld.build_d3(with_event=False)
    account = WaterAccount.objects.create(name="D3 District", account_number="D3-D", unit_kind="farm_unit")
    d3["site"].water_account = account
    d3["site"].save()

    def credit_and_pool():
        return (
            sum((c.amount_af for c in AccountCredit.objects.filter(water_account=account)), D("0")),
            sum((r.amount_af for r in AllocationCarryover.objects.filter(zone=d3["gsa"])), D("0")),
        )

    baseline = credit_and_pool()
    event = ld.log_event(d3["site"], dt.date(2025, 8, 1), dt.date(2025, 8, 31), "50.0000", "GW")
    assert credit_and_pool() != baseline

    months = void(event, user=person, reason=REASON)

    assert months == []
    assert credit_and_pool() == baseline
    assert type(event).objects.filter(pk=event.pk).exists()


def test_a_voided_ledger_entry_is_left_out_of_the_csv_export(ref, person):
    d1 = ld.build_d1()
    row = ld.ledger(d1["F4"], dt.date(2025, 7, 1), "-5", "adjustment", "GW", "VOID-ME-MARKER")
    client = Client()
    client.force_login(person)
    assert "VOID-ME-MARKER" in client.get(reverse("accounting:ledger_export")).content.decode()

    void(row, user=person, reason=REASON)

    body = client.get(reverse("accounting:ledger_export")).content.decode()
    assert "VOID-ME-MARKER" not in body
    assert list(csv.reader(io.StringIO(body)))  # still a file


def test_the_entry_form_figures_a_new_reading_from_the_last_one_in_use(ref, person):
    from wells.forms import MeterReadingForm

    field, rows = meter_field("F", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 15), "5000")])
    well = field.wellirrigatedparcel_set.first().well
    void(rows[1], user=person, reason=REASON)
    form = MeterReadingForm({"reading_date": "2025-07-31", "current_value": "1030"}, well=well)
    assert form.is_valid(), form.errors
    assert form.previous_value == D("1000.0000")
    assert form.volume == D("30.0000")


# ------------------------------------------------------------------ the duplicate checks
def test_a_voided_diversion_record_does_not_block_entering_the_right_one(person):
    record = DiversionRecordFactory(month=dt.date(2025, 7, 1))
    again = DiversionRecord(
        point_of_diversion=record.point_of_diversion, month=dt.date(2025, 7, 1),
        volume_acre_feet=D("1"), diversion_type="direct_use",
    )
    with pytest.raises(ValidationError):
        again.validate_constraints()

    void(record, user=person, reason=REASON)
    again.validate_constraints()  # a voided row no longer counts
    again.save()
    with pytest.raises(DatabaseError), transaction.atomic():
        DiversionRecord.objects.create(
            point_of_diversion=record.point_of_diversion, month=dt.date(2025, 7, 1),
            volume_acre_feet=D("2"), diversion_type="direct_use",
        )


def test_a_voided_production_record_does_not_block_entering_the_right_one(person):
    system = WaterSystemFactory()
    facility = SystemFacilityFactory(system=system)
    kwargs = dict(
        system=system, year=2024, month=3, type_code="GW", facility=facility,
        volume_as_reported=D("100"), unit_as_reported="G", provenance="typed",
    )
    first = SystemProduction.objects.create(**kwargs)
    with pytest.raises(DatabaseError), transaction.atomic():
        SystemProduction.objects.create(**kwargs)
    void(first, user=person, reason=REASON)
    SystemProduction.objects.create(**kwargs)


# ------------------------------------------------------------------ void itself
def test_void_marks_the_row_and_changes_nothing_else(person):
    row = ParcelLedgerFactory(description="before")
    before = ParcelLedger.objects.values().get(pk=row.pk)

    void(row, user=person, reason=REASON)

    after = ParcelLedger.objects.values().get(pk=row.pk)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"voided_at", "voided_by_id", "void_reason"}
    assert after["void_reason"] == REASON
    assert row.voided_by == person and row.voided_at is not None


def test_void_refuses_a_row_already_voided(person):
    row = ParcelLedgerFactory()
    void(row, user=person, reason=REASON)
    with pytest.raises(AlreadyVoided):
        void(ParcelLedger.objects.get(pk=row.pk), user=person, reason=REASON)


@pytest.mark.parametrize("reason", ["", "   ", "too short", "x" * 501])
def test_void_refuses_a_reason_outside_ten_to_five_hundred_characters(person, reason):
    row = ParcelLedgerFactory()
    with pytest.raises(ValueError, match="Give a reason of 10 to 500 characters."):
        void(row, user=person, reason=reason)
    assert ParcelLedger.objects.get(pk=row.pk).voided_at is None


def test_void_refuses_a_row_the_engine_wrote(person):
    calculated = ParcelLedgerFactory(source_type="calculated")
    share = ParcelLedgerFactory(source_type="meter_reading", description="From the well's meter: W1 pumped 5 AF")
    split = ParcelLedgerFactory(source_type="surface_diversion", divided_from_headgate=True)
    estimated = DiversionRecordFactory(method="estimated_from_use")
    for row in (calculated, share, split, estimated):
        assert corrections.can_void(row) is False
        with pytest.raises(NotVoidable):
            void(row, user=person, reason=REASON)
    typed = ParcelLedgerFactory(source_type="manual_entry")
    typed_delivery = ParcelLedgerFactory(source_type="surface_diversion", divided_from_headgate=False)
    assert corrections.can_void(typed) is True
    assert corrections.can_void(typed_delivery) is True


def test_void_refuses_a_row_in_a_finalized_year(ref, person):
    row = ld.ledger(ParcelFactory(), dt.date(2025, 7, 1), "-5", "adjustment", "GW")
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)
    assert corrections.can_void(row) is True
    assert corrections.can_void(row, finalized=corrections.finalized_ranges()) is False
    with pytest.raises(PeriodFinalized):
        void(row, user=person, reason=REASON)
    assert ParcelLedger.objects.get(pk=row.pk).voided_at is None


def test_void_refuses_a_use_area_with_rows_in_a_finalized_year(ref, person):
    field = ParcelFactory()
    ld.ledger(field, dt.date(2025, 7, 1), "-5", "adjustment", "GW")
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)
    with pytest.raises(PeriodFinalized):
        void(field, user=person, reason=REASON)


def test_voiding_a_station_reading_takes_its_published_copy_off_the_chart(person):
    row = make_row("station_reading")
    published = row.reading_id
    assert DataRecordStaging.objects.filter(pk=published).exists()

    void(row, user=person, reason=REASON)

    assert not DataRecordStaging.objects.filter(pk=published).exists()
    stored = TypedReading.objects.get(pk=row.pk)
    assert stored.reading_id is None
    assert stored.voided_at is not None
    assert stored.value == D("1.0000")


@pytest.mark.parametrize(
    "key",
    ["water_level", "recharge_measurement", "lab_result", "production_record", "station_reading"],
)
def test_kinds_no_figure_reads_ask_for_no_recalculation(key, person):
    row = make_row(key)
    assert void(row, user=person, reason=REASON) == []


def test_every_kind_has_the_entries_the_screens_read():
    assert set(KINDS) == {
        "meter_reading", "water_level", "ledger_entry", "fallow_period", "use_area",
        "diversion_record", "recharge_event", "recharge_measurement", "lab_result",
        "production_record", "station_reading",
    }
    for key, kind in KINDS.items():
        row = make_row(key)
        assert corrections.kind_for(row) is kind
        assert corrections.get_kind(key) is kind
        assert kind["label"] == kind["label"].lower()
        assert isinstance(kind["summary"](row), str) and kind["summary"](row)
        assert kind["page_url"](row).startswith("/")
        assert kind.enabled() is True
        assert isinstance(set(kind["months"](row)), set)


# ------------------------------------------------------------------ (c) the static guard
COVERED = frozenset(
    {
        "MeterReading", "WaterMeasurement", "ParcelLedger", "FallowPeriod", "Parcel",
        "DiversionRecord", "RechargeEvent", "RechargeMeasurement", "SampleResult",
        "SystemProduction", "TypedReading",
    }
)
WRITERS = frozenset(
    {"create", "bulk_create", "bulk_update", "update", "delete", "get_or_create", "update_or_create"}
)
ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Files the guard reads: accounting/ whole, and the named files of the other modules.
GUARDED = ("accounting",)
GUARDED_FILES = (
    "surface/services.py",
    "parcels/views.py",
    "geography/views.py",
    "reporting/generators.py",
    "reporting/services.py",
    "reporting/validators.py",
)

#: Reads that show every row on purpose, keyed by (file, function name), each
#: with its reason. Function names, never line numbers. A new read of a covered
#: model that is neither chained to ``.current()`` nor here fails the build.
ALLOWED_READS = {
    ("accounting/views/ledger.py", "_ledger_as_of_scope"):
        "finds which use areas a search or zone names, for the count in the line; the count itself reads current rows",
    ("parcels/views.py", "_use_area_on_record"):
        "asks whether the page's use area exists at all, voided or not, so a date before it gets a sentence and a wrong id a 404",
    ("accounting/ledger_import.py", "_lookup_parcel"):
        "finds a use area by number for an upload; a voided use area keeps its number and is refused as a duplicate",
    ("accounting/management/commands/run_calculations.py", "_clear_engine_rows_of_voided_parcels"):
        "finds the use areas that do not count, to clear the engine's own rows for them",
    ("accounting/services.py", "current_period_id"):
        "picks which water year to open a page on: a default, not a figure",
    ("accounting/statements.py", "_existing"):
        "asks which places a filed figure names are still on file, to link them; a voided use area keeps its page",
    ("accounting/views/accounts.py", "_detail_selected_period"):
        "picks which water year to open the account page on: a default, not a figure",
    ("accounting/views/accounts.py", "_period_budget_flags"):
        "asks whether any use area is on file",
    ("accounting/views/accounts.py", "parcel_search_for_assignment"):
        "a pick list: a voided use area can still be found and opened",
    ("accounting/views/dashboard.py", "_engine_run_status"):
        "asks whether any use area is on file",
    ("accounting/views/dashboard.py", "_latest_data_dates"):
        "the newest transaction date on file: a date to print, not a figure",
    ("accounting/views/dashboard.py", "_resolve_selected_period"):
        "picks which water year to open the dashboard on: a default, not a figure",
    ("accounting/views/ledger.py", "_ledger_default_period"):
        "picks which water year to open the ledger on: a default, not a figure",
    ("accounting/views/ledger.py", "ledger_create"):
        "finds the use area the form names; a voided use area can be found",
    ("accounting/views/ledger.py", "_ledger_response"):
        "the ledger page draws voided rows struck; its footer total reads .current()",
    ("accounting/views/settings_pages.py", "methodology_preview"):
        "picks a use area to preview a calculation on",
    ("accounting/views/settings_pages.py", "methodology_settings"):
        "a pick list of use areas for the preview",
    ("geography/views.py", "zone_parcel_search"):
        "a pick list: a voided use area can be found and opened",
    ("parcels/views.py", "_balance_period"):
        "picks which water year to open the use area page on: a default, not a figure",
    ("parcels/views.py", "_recent_ledger"):
        "the use area page's ten recent rows, struck when voided",
    ("parcels/views.py", "parcels_list"):
        "the use area list shows a voided use area struck; its counts say how many are listed",
    ("reporting/generators.py", "build_shared_supply_comparison"):
        "parcel numbers for use areas already chosen: display of ids, not a figure",
}


def guarded_files():
    found = []
    for folder in GUARDED:
        found += [p for p in (ROOT / folder).rglob("*.py") if "migrations" not in p.parts]
    found += [ROOT / name for name in GUARDED_FILES]
    return sorted(found)


class _Reads(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.functions = []
        self.parents = {}
        self.found = []

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parents[child] = node
        super().generic_visit(node)

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Attribute(self, node):
        if node.attr == "objects" and isinstance(node.value, ast.Name) and node.value.id in COVERED:
            chain, current = [], node
            while True:
                parent = self.parents.get(current)
                if isinstance(parent, ast.Attribute) and parent.value is current:
                    chain.append(parent.attr)
                    current = parent
                elif isinstance(parent, ast.Call) and parent.func is current:
                    current = parent
                else:
                    break
            self.found.append(
                (self.path, self.functions[-1] if self.functions else "<module>", node.value.id, chain, node.lineno)
            )
        self.generic_visit(node)


def covered_statements():
    found = []
    for path in guarded_files():
        reads = _Reads(path.relative_to(ROOT).as_posix())
        reads.visit(ast.parse(path.read_text()))
        found += reads.found
    return found


def test_the_guard_reads_something():
    found = covered_statements()
    assert len(found) > 60
    assert sum("current" in chain for _f, _fn, _m, chain, _l in found) > 30
    assert sum(bool(set(chain) & WRITERS) for _f, _fn, _m, chain, _l in found) > 10


def test_no_calculation_or_total_reads_a_covered_model_around_the_rule():
    unknown = sorted(
        {
            f"{path} {function} {model}.objects.{'.'.join(chain[:3])} (line {line})"
            for path, function, model, chain, line in covered_statements()
            if "current" not in chain
            and not (set(chain) & WRITERS)
            and (path, function) not in ALLOWED_READS
        }
    )
    assert unknown == []


def test_every_allowed_read_still_exists_and_has_a_reason():
    seen = {
        (path, function)
        for path, function, _m, chain, _l in covered_statements()
        if "current" not in chain and not (set(chain) & WRITERS)
    }
    assert sorted(set(ALLOWED_READS) - seen) == []
    assert all(len(reason.split()) >= 4 for reason in ALLOWED_READS.values())


# ------------------------------------------------------------------ (h) history on three more models
def test_a_meter_records_an_update_in_change_history():
    meter = Meter.objects.create(serial_number="CR-H-1", status="active")
    meter.status = "inactive"
    meter.save()
    events = list(MeterEvent.objects.filter(pgh_obj_id=meter.pk).order_by("pgh_id"))
    assert [e.pgh_label for e in events] == ["insert", "before_update", "update"]
    assert events[1].status == "active"
    assert events[2].status == "inactive"


def test_a_sample_event_records_an_update_in_change_history():
    event = SampleEventFactory(collector="Before")
    event.collector = "After"
    event.save()
    events = list(SampleEventEvent.objects.filter(pgh_obj_id=event.pk).order_by("pgh_id"))
    assert [e.pgh_label for e in events] == ["insert", "before_update", "update"]
    assert events[1].collector == "Before"
    assert events[2].collector == "After"


def test_a_recharge_site_records_an_update_in_change_history():
    site = RechargeSiteFactory(operator="Before")
    site.operator = "After"
    site.save()
    events = list(RechargeSiteEvent.objects.filter(pgh_obj_id=site.pk).order_by("pgh_id"))
    assert [e.pgh_label for e in events] == ["insert", "before_update", "update"]
    assert events[1].operator == "Before"
    assert events[2].operator == "After"


def test_a_void_is_one_change_with_the_reason(person):
    from parcels.models import ParcelLedgerEvent

    row = ParcelLedgerFactory()
    with pghistory.context(user=person.pk):
        void(row, user=person, reason=REASON)
    update = ParcelLedgerEvent.objects.get(pgh_obj_id=row.pk, pgh_label="update")
    assert update.pgh_context.metadata["note"] == REASON
    assert update.void_reason == REASON
    assert update.voided_at is not None


# ------------------------------------------------------------------ (i) the who-did-it table
def _refused(sql, params):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    except DatabaseError:
        return True
    return False


def _context_id():
    with pghistory.context(command="lock-test") as context:
        ZoneFactory()
    return context.id


def test_a_delete_on_the_context_table_is_refused():
    context_id = _context_id()
    assert _refused("DELETE FROM pghistory_context WHERE id = %s", [str(context_id)])
    with pytest.raises(DatabaseError), transaction.atomic():
        pghistory_models.Context.objects.filter(id=context_id).delete()
    assert pghistory_models.Context.objects.filter(id=context_id).exists()


def test_an_update_of_the_context_table_is_allowed():
    context_id = _context_id()
    pghistory_models.Context.objects.filter(id=context_id).update(metadata={"a": 1})
    assert pghistory_models.Context.objects.get(id=context_id).metadata == {"a": 1}


def test_the_delete_runs_inside_the_one_door():
    context_id = _context_id()
    with pgtrigger.ignore(CONTEXT_LOCK_URI):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM pghistory_context WHERE id = %s", [str(context_id)])
    assert not pghistory_models.Context.objects.filter(id=context_id).exists()
    # and the door shuts behind it
    other = _context_id()
    assert _refused("DELETE FROM pghistory_context WHERE id = %s", [str(other)])


def test_the_lock_is_in_the_database_and_pgtrigger_knows_it():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = 'pghistory_context' AND t.tgname LIKE %s",
            ["pgtrigger_no_delete%"],
        )
        assert cursor.fetchall()
    assert pgtrigger.registered(CONTEXT_LOCK_URI)


def test_truncate_is_not_stopped_by_a_row_trigger():
    _context_id()
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE pghistory_context")
    assert pghistory_models.Context.objects.count() == 0


def test_forget_events_still_removes_a_demonstration_context_row():
    from core.demonstration import forget_events

    with pghistory.context(command="mine") as mine:
        ZoneFactory(name="Mine")
    forget_events(mine.id)
    assert not pghistory_models.Context.objects.filter(id=mine.id).exists()


def test_the_golden_build_still_empties_the_context_table():
    _context_id()
    call_command("clear_change_history", "--golden-build")
    assert pghistory_models.Context.objects.count() == 0
