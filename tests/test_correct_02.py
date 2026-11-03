# SPDX-License-Identifier: AGPL-3.0-or-later
"""Correct this record, at the model level (151.7-02, the data layer).

``core.corrections.correct`` writes the replacing row and marks the old one; the
views are tested in their own file. This file proves:

* (a) a correction creates the new row with ``replaces``, copies the untouched
  fields, writes only ``replaced_at`` on the old row, figures the next reading
  again, returns both rows' months, and the month's calculation reads the new
  value; a corrected diversion record and a corrected production record do not hit
  their one-current-row unique indexes;
* (b) in a finalized year ``correct()`` is refused outside the recorded door and
  succeeds inside ``override(reason)``, with the history rows carrying
  ``override=True`` and the reason and the year still finalized; a recalculation
  request carrying the reason calculates the finalized month, the same request
  without a reason is refused;
* (f) the chain: B replaces A, C replaces B; only C counts; A and B can be neither
  corrected nor voided; voiding C voids C only;
* (j) a voided or replaced row, a use area and an engine-written row cannot be
  corrected, and a bad reason or field changes nothing;
* a recharge event correction moves its credit; a station reading correction moves
  the published copy.
"""
import datetime as dt
import io
from decimal import Decimal as D
from unittest import mock

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounting.engine_run import create_request, request_for_months
from accounting.locks import PeriodFinalized, override
from accounting.models import CalculationRequest, ReportingPeriod
from core.corrections import (
    ALREADY_REPLACED_SENTENCE,
    KINDS,
    AlreadyReplaced,
    AlreadyVoided,
    NotCorrectable,
    can_correct,
    can_void,
    correct,
    finalized_ranges,
    void,
)
from core.reasons import REASON_SENTENCE
from measurements.models import MeterReading
from parcels.models import ParcelLedger
from tests import ledger_districts as ld
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    WaterSystemFactory,
)
from tests.test_current_records_01 import (  # noqa: F401  (ref is a fixture)
    figure,
    make_row,
    meter_field,
    person,
    ref,
)

pytestmark = pytest.mark.django_db

REASON = "digits swapped when typed"
DOOR_REASON = "the meter shows 142, not 412"
WELL_SHARE = "From the well's meter:"
MARKING = {"voided_at", "voided_by", "void_reason", "replaces", "change_reason", "replaced_at"}
#: Columns a correction figures again itself, or sets for the person who typed it.
DERIVED = {
    "previous_value", "calculated_volume", "volume_gallons", "volume_acre_feet",
    "typed_at", "reading",
}


def _snapshot(row):
    return {f.attname: getattr(row, f.attname) for f in type(row)._meta.concrete_fields}


def _pumped(field, month_prefix="2025-07"):
    """What the engine wrote for the field from its well's meter, summed."""
    rows = ParcelLedger.objects.current().filter(
        parcel=field, description__startswith=WELL_SHARE,
        effective_date__year=int(month_prefix[:4]), effective_date__month=int(month_prefix[5:7]),
    )
    return sum((r.amount_acre_feet for r in rows), D("0"))


# ------------------------------------------------------------------ (a) the new row
def test_a_correction_creates_the_new_row_and_writes_only_replaced_at_on_the_old(ref, person):
    field, rows = meter_field(
        "CA", -120.55,
        [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412"), (dt.date(2025, 8, 31), "1442")],
    )
    old = rows[1]
    old.notes = "read by Smith"
    old.save()
    before = _snapshot(MeterReading.objects.get(pk=old.pk))

    months = correct(old, user=person, reason=REASON, changes={"current_value": D("1142")})

    assert months == ["2025-07", "2025-08"]
    after = _snapshot(MeterReading.objects.get(pk=old.pk))
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {"replaced_at"}
    assert after["replaced_at"] is not None

    new = MeterReading.objects.get(replaces=old)
    assert (new.meter_id, new.reading_date, new.notes) == (old.meter_id, old.reading_date, "read by Smith")
    assert new.current_value == D("1142.0000")
    assert (new.previous_value, new.calculated_volume) == (D("1000.0000"), D("142.0000"))
    assert (new.read_by, new.change_reason, new.voided_at, new.replaced_at) == (person, REASON, None, None)
    counting = MeterReading.objects.current().filter(meter_id=old.meter_id).order_by("reading_date")
    assert [r.pk for r in counting] == [rows[0].pk, new.pk, rows[2].pk]
    # The reading after it is figured again from the corrected one; what was typed never moves.
    following = MeterReading.objects.get(pk=rows[2].pk)
    assert (following.previous_value, following.calculated_volume) == (D("1142.0000"), D("300.0000"))
    assert following.current_value == D("1442.0000")


def test_the_month_reads_the_corrected_value(ref, person):
    x, x_rows = meter_field("CX", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412")])
    y, _ = meter_field("CY", -120.50, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1142")])
    ld.run_months(["2025-07"])
    assert figure(x, "2025-07") != figure(y, "2025-07")
    assert _pumped(x) != _pumped(y)

    months = correct(x_rows[1], user=person, reason=REASON, changes={"current_value": D("1142")})
    ld.run_months(months)

    assert months == ["2025-07"]
    assert figure(x, "2025-07") == figure(y, "2025-07")
    assert _pumped(x) == _pumped(y)
    assert _pumped(x) != D("0")


def test_a_correction_that_moves_the_date_returns_both_months(ref, person):
    _field, rows = meter_field(
        "CD", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1100")]
    )
    months = correct(rows[1], user=person, reason=REASON, changes={"reading_date": dt.date(2025, 8, 20)})
    assert months == ["2025-07", "2025-08"]
    new = MeterReading.objects.get(replaces=rows[1])
    assert timezone.localtime(new.reading_date).date() == dt.date(2025, 8, 20)
    assert timezone.localtime(new.reading_date).hour == 12


def test_a_corrected_diversion_record_does_not_hit_the_one_current_index():
    record = DiversionRecordFactory()
    user = _user("clerk1")

    months = correct(record, user=user, reason=REASON, changes={"volume_acre_feet": D("60.0000")})

    assert months == ["2024-01"]
    from surface.models import DiversionRecord

    assert DiversionRecord.objects.count() == 2
    assert [r.volume_acre_feet for r in DiversionRecord.objects.current()] == [D("60.0000")]
    again = DiversionRecord.objects.current().get()
    correct(again, user=user, reason=REASON, changes={"volume_acre_feet": D("70.0000")})
    assert [r.volume_acre_feet for r in DiversionRecord.objects.current()] == [D("70.0000")]


def _user(name):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username=name, password="x", is_active=True)


def test_a_corrected_production_record_does_not_hit_the_one_current_index():
    from drinking.models import SystemProduction

    row = SystemProduction.objects.create(
        system=WaterSystemFactory(), year=2026, month=3, type_code="GW",
        volume_as_reported=D("100"), unit_as_reported="G", provenance="typed",
    )
    months = correct(row, user=_user("clerk2"), reason=REASON, changes={"volume_as_reported": D("200")})

    assert months == []
    current = SystemProduction.objects.current().get()
    assert (current.volume_as_reported, current.volume_gallons) == (D("200.00"), D("200.00"))
    assert current.replaces_id == row.pk
    assert SystemProduction.objects.count() == 2


CHANGES = {
    "meter_reading": {"current_value": D("11")},
    "water_level": {"value": D("6")},
    "ledger_entry": {"amount_acre_feet": D("12")},
    "fallow_period": {"end_month": dt.date(2025, 9, 1)},
    "diversion_record": {"volume_acre_feet": D("60")},
    "recharge_event": {"volume_acre_feet": D("20")},
    "recharge_measurement": {"value": D("2")},
    "lab_result": {"result_value": D("0.002")},
    "production_record": {"volume_as_reported": D("200")},
    "station_reading": {"value": D("2")},
}


@pytest.mark.parametrize("key", list(CHANGES))
def test_every_correctable_kind_copies_what_it_did_not_change(key):
    user = _user(f"u-{key}")
    old = make_row(key)
    model = type(old)
    kind = KINDS[key]
    before = _snapshot(model.objects.get(pk=old.pk))

    months = correct(old, user=user, reason=REASON, changes=CHANGES[key])

    assert months == sorted(set(months))
    after = _snapshot(model.objects.get(pk=old.pk))
    # A station reading's published copy is one row, linked one to one, so it
    # moves to the new row and the old row's link is cleared with it.
    moved = {"replaced_at", "reading_id"} if key == "station_reading" else {"replaced_at"}
    assert {n for n in before if before[n] != after[n]} == moved
    new = model.objects.get(replaces=old)
    assert new.pk != old.pk and new.change_reason == REASON
    assert (new.voided_at, new.replaced_at) == (None, None)
    skip = MARKING | DERIVED | set(CHANGES[key]) | set(kind["author"](user)) | {"id", "reporting_period_id"}
    for field in model._meta.concrete_fields:
        if field.attname in skip or field.name in skip:
            continue
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue
        assert getattr(new, field.attname) == before[field.attname], field.name
    for name, value in CHANGES[key].items():
        assert getattr(new, name) == value
    assert list(model.objects.current()) == [new]


def test_a_field_outside_the_kinds_list_is_refused_and_nothing_is_written():
    user = _user("fields")
    record = DiversionRecordFactory()
    with pytest.raises(ValueError):
        correct(record, user=user, reason=REASON, changes={"point_of_diversion": 1})
    with pytest.raises(ValueError):
        correct(record, user=user, reason=REASON, changes={"no_such_field": 1})
    record.refresh_from_db()
    assert record.replaced_at is None
    assert type(record).objects.count() == 1


# ------------------------------------------------------------------ (b) a finalized year
def _finalize_wy_2024_2025():
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)
    return ReportingPeriod.objects.get(name="WY 2024-2025")


def test_a_finalized_year_refuses_a_correction_outside_the_door_and_takes_it_inside(ref, person):
    _field, rows = meter_field(
        "CB", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412")]
    )
    period = _finalize_wy_2024_2025()

    with pytest.raises(PeriodFinalized):
        correct(rows[1], user=person, reason=REASON, changes={"current_value": D("1142")})
    assert MeterReading.objects.count() == 2
    assert MeterReading.objects.get(pk=rows[1].pk).replaced_at is None

    with override(DOOR_REASON):
        months = correct(rows[1], user=person, reason=REASON, changes={"current_value": D("1142")})

    assert months == ["2025-07"]
    new = MeterReading.objects.get(replaces=rows[1])
    events = apps.get_model("measurements.MeterReadingEvent")
    for pk, label in ((new.pk, "insert"), (rows[1].pk, "update")):
        found = events.objects.filter(pgh_obj_id=pk, pgh_label=label)
        assert found.exists()
        for event in found:
            assert event.pgh_context.metadata.get("override") is True
            assert event.pgh_context.metadata.get("reason") == DOOR_REASON
    period.refresh_from_db()
    assert period.is_finalized is True
    # The door closes behind it.
    with pytest.raises(PeriodFinalized):
        correct(new, user=person, reason=REASON, changes={"current_value": D("1100")})


def test_void_takes_the_same_door(ref, person):
    _field, rows = meter_field(
        "CV", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412")]
    )
    _finalize_wy_2024_2025()
    with pytest.raises(PeriodFinalized):
        void(rows[1], user=person, reason=REASON)
    with override(DOOR_REASON):
        assert void(rows[1], user=person, reason=REASON) == ["2025-07"]
    assert MeterReading.objects.get(pk=rows[1].pk).voided_by == person


@mock.patch("accounting.engine_run.start_calculation")
def test_a_request_with_a_reason_calculates_a_finalized_month_and_one_without_is_refused(
    started, ref, person
):
    field, rows = meter_field(
        "CR", -120.55, [(dt.date(2025, 6, 30), "1000"), (dt.date(2025, 7, 31), "1412")]
    )
    ld.run_months(["2025-07"])
    period = _finalize_wy_2024_2025()
    first = _pumped(field)
    assert first != D("0")

    with override(DOOR_REASON):
        months = correct(rows[1], user=person, reason=REASON, changes={"current_value": D("1142")})
    assert months == ["2025-07"]

    # Without a reason the month is dropped, and a plain request is refused.
    assert request_for_months("record_corrected", months, requested_by=person) == []
    plain = create_request("command", reporting_period=period, months=months)
    with pytest.raises(CommandError):
        call_command("run_accounting", request=plain.pk, stdout=io.StringIO(), stderr=io.StringIO())
    plain.refresh_from_db()
    assert plain.status == "failed"
    assert "WY 2024-2025 is finalized." in plain.outcome
    assert _pumped(field) == first

    # With the reason the month is kept, the request carries it, and it runs through the door.
    created = request_for_months("record_corrected", months, requested_by=person, reason=DOOR_REASON)
    assert [(r.months, r.override_reason, r.trigger) for r in created] == [
        (["2025-07"], DOOR_REASON, "record_corrected")
    ]
    call_command("run_accounting", request=created[0].pk, stdout=io.StringIO(), stderr=io.StringIO())
    ran = CalculationRequest.objects.get(pk=created[0].pk)
    assert ran.status in ("succeeded", "finished_with_notes")
    assert _pumped(field) != first
    events = apps.get_model("parcels.ParcelLedgerEvent").objects.filter(
        pgh_context__metadata__override=True, pgh_context__metadata__reason=DOOR_REASON
    )
    assert events.exists()
    period.refresh_from_db()
    assert period.is_finalized is True


def test_requests_with_different_reasons_are_never_merged(ref):
    from accounting.engine_run import _merge_overlapping

    a = create_request("record_corrected", months=["2025-07"], override_reason="first reason here")
    b = create_request("record_corrected", months=["2025-07"], override_reason="")
    c = create_request("record_corrected", months=["2025-07"], override_reason="other reason here")
    d = create_request("record_corrected", months=["2025-07"], override_reason="first reason here")
    assert _merge_overlapping(a, [a, b, c, d]) == [d]
    assert _merge_overlapping(b, [b, c]) == []


# ------------------------------------------------------------------ (f) the chain
def test_only_the_newest_row_of_a_chain_counts_and_can_change():
    from surface.models import DiversionRecord

    user = _user("chain")
    a = DiversionRecordFactory()
    correct(a, user=user, reason=REASON, changes={"volume_acre_feet": D("60")})
    b = DiversionRecord.objects.get(replaces=a)
    correct(b, user=user, reason=REASON, changes={"volume_acre_feet": D("70")})
    c = DiversionRecord.objects.get(replaces=b)

    assert list(DiversionRecord.objects.current()) == [c]
    for old in (a, b):
        with pytest.raises(AlreadyReplaced) as exc:
            correct(old, user=user, reason=REASON, changes={"volume_acre_feet": D("1")})
        assert str(exc.value) == ALREADY_REPLACED_SENTENCE
        with pytest.raises(AlreadyReplaced):
            void(old, user=user, reason=REASON)
        old.refresh_from_db()
        assert old.voided_at is None
    assert ALREADY_REPLACED_SENTENCE == "This record has been corrected already. Correct the newest one."

    void(c, user=user, reason=REASON)
    c.refresh_from_db()
    b.refresh_from_db()
    assert c.voided_at is not None
    assert b.voided_at is None and b.replaced_at is not None
    assert list(DiversionRecord.objects.current()) == []


def test_can_correct_and_can_void_answer_from_the_row_without_a_query(django_assert_num_queries):
    user = _user("flags")
    row = DiversionRecordFactory()
    ranges = [(dt.date(2023, 10, 1), dt.date(2024, 9, 30))]  # the row's month is inside
    with django_assert_num_queries(0):
        assert can_correct(row) is True and can_void(row) is True
        assert can_correct(row, ranges) is False and can_void(row, ranges) is False
        assert can_correct(row, ranges, admin=True) is True and can_void(row, ranges, admin=True) is True
    correct(row, user=user, reason=REASON, changes={"volume_acre_feet": D("60")})
    row.refresh_from_db()
    with django_assert_num_queries(0):
        assert can_correct(row) is False and can_void(row) is False
    assert finalized_ranges() == []


# ------------------------------------------------------------------ (j) what cannot be corrected
def test_a_voided_row_cannot_be_corrected():
    user = _user("voided")
    row = DiversionRecordFactory()
    void(row, user=user, reason=REASON)
    with pytest.raises(AlreadyVoided):
        correct(row, user=user, reason=REASON, changes={"volume_acre_feet": D("1")})
    assert can_correct(row) is False


def test_a_use_area_cannot_be_corrected():
    user = _user("area")
    area = ParcelFactory()
    with pytest.raises(NotCorrectable) as exc:
        correct(area, user=user, reason=REASON, changes={})
    assert "not corrected with a new row" in str(exc.value)
    assert KINDS["use_area"]["correct_fields"] == ()
    assert can_correct(area) is False


def test_an_engine_written_row_cannot_be_corrected():
    user = _user("engine")
    ledger = ParcelLedgerFactory(source_type="calculated")
    estimate = DiversionRecordFactory(method="estimated_from_use")
    well_share = ParcelLedgerFactory(source_type="meter_reading", description=f"{WELL_SHARE} MTR-1")
    for row, changes in (
        (ledger, {"amount_acre_feet": D("-1")}),
        (estimate, {"volume_acre_feet": D("1")}),
        (well_share, {"amount_acre_feet": D("-1")}),
    ):
        with pytest.raises(NotCorrectable) as exc:
            correct(row, user=user, reason=REASON, changes=changes)
        assert "written by OpenH2O's own calculation" in str(exc.value)
        assert can_correct(row) is False


def test_a_short_reason_changes_nothing():
    user = _user("short")
    row = DiversionRecordFactory()
    with pytest.raises(ValueError) as exc:
        correct(row, user=user, reason="too short", changes={"volume_acre_feet": D("1")})
    assert str(exc.value) == REASON_SENTENCE
    assert type(row).objects.count() == 1


def test_void_on_a_replaced_row_is_not_offered():
    user = _user("offer")
    row = DiversionRecordFactory()
    correct(row, user=user, reason=REASON, changes={"volume_acre_feet": D("60")})
    assert can_void(row) is False


# ------------------------------------------------------------------ the two kinds with a consequence
def test_correcting_a_recharge_event_moves_its_credit(ref):
    from accounting.models import AccountCredit, AllocationCarryover, WaterAccount
    from recharge.models import RechargeEvent

    user = _user("recharge")
    d3 = ld.build_d3(with_event=False)
    site = d3["site"]
    site.water_account = WaterAccount.objects.create(name="D3 District", account_number="D3-D", unit_kind="farm_unit")
    site.save()
    event = ld.log_event(site, dt.date(2025, 8, 1), dt.date(2025, 8, 31), "50.0000", "GW")
    old_key = f"recharge_event:{event.pk}"
    assert list(AccountCredit.objects.values_list("source_key", flat=True)) == [old_key]

    correct(event, user=user, reason=REASON, changes={"volume_acre_feet": D("20.0000")})

    new = RechargeEvent.objects.get(replaces=event)
    assert list(AccountCredit.objects.values_list("source_key", flat=True)) == [f"recharge_event:{new.pk}"]
    pool = AllocationCarryover.objects.filter(origin="basin_recharge_pool")
    credit_after = sum(c.amount_af for c in AccountCredit.objects.all())
    pool_after = sum(p.amount_af for p in pool)
    assert pool_after != D("0")

    # The totals equal those of one fresh event of the new figure.
    ld.log_event(site, dt.date(2025, 8, 1), dt.date(2025, 8, 31), "20.0000", "GW")
    assert sum(c.amount_af for c in AccountCredit.objects.all()) == 2 * credit_after
    assert sum(p.amount_af for p in AllocationCarryover.objects.filter(origin="basin_recharge_pool")) == 2 * pool_after


def test_correcting_a_station_reading_moves_the_published_copy():
    from datasync import typed_readings
    from datasync.models import DataRecordStaging, TypedReading

    user = _user("station")
    old = make_row("station_reading")
    published = old.reading
    assert DataRecordStaging.objects.filter(station=old.station).count() == 1

    correct(
        old, user=user, reason=REASON,
        changes={"value": D("2.5"), "observation_date": dt.date(2025, 3, 5)},
    )

    new = TypedReading.objects.get(replaces=old)
    staging = DataRecordStaging.objects.filter(station=old.station)
    assert staging.count() == 1
    only = staging.get()
    assert only.pk == published.pk
    assert (only.value, only.observation_date) == (D("2.5000"), typed_readings.midnight(dt.date(2025, 3, 5)))
    assert new.reading_id == only.pk
    assert TypedReading.objects.get(pk=old.pk).reading_id is None
    assert (new.typed_by, new.typed_by_email) == (user, user.email or user.get_username())
    assert list(TypedReading.objects.current()) == [new]
