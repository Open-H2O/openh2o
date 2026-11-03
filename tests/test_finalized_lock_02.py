# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finalized-year lock on nine more tables (151.7-02).

``tests/test_finalized_period_lock.py`` is parametrized over ``LOCKED_MODELS``, so
its raw-SQL, override-history and open-year tests already run for the nine tables
added here (its ``_build`` knows each of them). This file adds what is particular
to them:

* (c) on each of the nine, every ORM path (``save()``, ``QuerySet.update()``,
  ``delete()``, ``bulk_create`` and a fresh insert) is refused inside a finalized
  year, allowed in an open year, and allowed inside ``override(reason)`` with the
  history rows carrying ``override=True`` and the reason; the refusal's DETAIL is
  the table name;
* (d) a DateTime is read as the site's calendar day: 23:30 Pacific on the year's
  last day is locked (06:30 UTC the next day), 00:30 Pacific on the next year's first
  day is not; the zone is recorded in the trigger the migration installs;
* the three columns that are not a plain date: a drinking result takes its event's
  sample date, a production record takes ``make_date(year, month)`` with an empty
  month meaning January, a fallow period takes its start month and falls back to
  its end month;
* (g) a row dated in a finalized year is a row error in each import (water levels,
  lab results, production) and in the typed station reading, in the preview as on
  commit, and the same rows load inside ``override(...)``.
"""
import datetime as dt
from decimal import Decimal
from html import unescape
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, connection, models, transaction

from accounting.locks import (
    LOCK_SQLSTATE,
    LOCKED_MODELS,
    lock_error_message,
    override,
)
from accounting.models import ReportingPeriod
from tests.test_finalized_period_lock import (  # noqa: F401  (periods is a fixture)
    CLOSED_DAY,
    OPEN_DAY,
    REASON,
    REFUSAL,
    _build,
    _finalize,
    _table,
    periods,
)

pytestmark = pytest.mark.django_db

PACIFIC = ZoneInfo("America/Los_Angeles")

NEW_LABELS = (
    "measurements.MeterReading",
    "measurements.WaterMeasurement",
    "recharge.RechargeEvent",
    "recharge.RechargeMeasurement",
    "surface.CanalMonthLoss",
    "parcels.FallowPeriod",
    "datasync.TypedReading",
    "drinking.SystemProduction",
    "drinking.SampleResult",
)


def _model(label):
    return apps.get_model(label)


def _refused(action):
    """Run ``action`` in a savepoint; assert the lock refused it, with the year's sentence."""
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        action()
    cause = exc.value.__cause__
    assert (cause.sqlstate, cause.diag.message_primary) == (LOCK_SQLSTATE, REFUSAL)
    return cause


def _clone(row):
    """An unsaved copy of ``row`` with no key, ready for ``bulk_create``."""
    copy = type(row).objects.get(pk=row.pk)
    copy.pk = None
    copy.id = None
    copy._state.adding = True
    if hasattr(copy, "reading_id"):
        copy.reading = None  # TypedReading.reading is a OneToOne
    return copy


def test_the_new_tables_are_the_last_nine_of_the_lock_tuple():
    assert tuple(LOCKED_MODELS[-9:]) == NEW_LABELS


# -- (c) every ORM path ----------------------------------------------------------------


@pytest.mark.parametrize("label", NEW_LABELS)
def test_every_orm_path_is_refused_in_a_finalized_year(periods, label):
    closed, _ = periods
    row = _build(label, CLOSED_DAY, closed)
    _finalize(closed)
    model = type(row)

    _refused(row.save)
    _refused(lambda: model.objects.filter(pk=row.pk).update(id=models.F("id")))
    _refused(row.delete)
    _refused(lambda: model.objects.filter(pk=row.pk).delete())
    _refused(lambda: model.objects.bulk_create([_clone(row)]))
    _refused(lambda: _build(label, CLOSED_DAY, closed))
    assert model.objects.filter(pk=row.pk).count() == 1


@pytest.mark.parametrize("label", NEW_LABELS)
def test_the_refusal_names_the_table_in_its_detail(periods, label):
    closed, _ = periods
    row = _build(label, CLOSED_DAY, closed)
    _finalize(closed)
    cause = _refused(lambda: _model(label).objects.filter(pk=row.pk).update(id=models.F("id")))
    assert cause.diag.message_detail == _table(label)
    assert lock_error_message(DatabaseError()) is None


@pytest.mark.parametrize("label", NEW_LABELS)
def test_every_orm_path_is_allowed_in_an_open_year(periods, label):
    closed, opened = periods
    row = _build(label, OPEN_DAY, opened)
    _finalize(closed)
    model = type(row)

    row.save()
    assert model.objects.filter(pk=row.pk).update(id=models.F("id")) == 1
    second = _build(label, OPEN_DAY, opened)
    assert model.objects.filter(pk=second.pk).count() == 1
    row.delete()
    assert model.objects.filter(pk=second.pk).delete()[0] >= 1
    assert model.objects.filter(pk__in=[row.pk, second.pk]).count() == 0


@pytest.mark.parametrize("label", NEW_LABELS)
def test_inside_the_door_every_path_writes_and_history_carries_the_reason(periods, label):
    closed, _ = periods
    row = _build(label, CLOSED_DAY, closed)
    _finalize(closed)
    model = type(row)
    events = apps.get_model(f"{label}Event")

    old_pk = row.pk  # delete() clears row.pk
    with override(REASON):
        row.save()
        assert model.objects.filter(pk=row.pk).update(id=models.F("id")) == 1
        fresh = _build(label, CLOSED_DAY, closed)
        row.delete()

    assert model.objects.filter(pk=fresh.pk).count() == 1
    assert model.objects.filter(pk=old_pk).count() == 0
    for pk, expected in ((fresh.pk, {"insert"}), (old_pk, {"delete"})):
        found = events.objects.filter(pgh_obj_id=pk).exclude(pgh_label="before_update")
        by_label = {e.pgh_label for e in found}
        assert expected <= by_label
        for event in found.filter(pgh_label__in=expected):
            assert event.pgh_context.metadata.get("override") is True
            assert event.pgh_context.metadata.get("reason") == REASON
    # Outside the door the same row is refused again.
    _refused(lambda: model.objects.filter(pk=fresh.pk).update(id=models.F("id")))


# -- (d) a DateTime is the site's calendar day --------------------------------------------


def _datetime_row(label, moment):
    from measurements.models import Meter, MeterReading, WaterMeasurement
    from recharge.models import RechargeMeasurement
    from tests.factories import RechargeSiteFactory

    if label == "measurements.MeterReading":
        meter = Meter.objects.create(serial_number=f"D-{moment:%Y%m%d%H%M}-{Meter.objects.count()}")
        return MeterReading.objects.create(meter=meter, reading_date=moment, current_value=Decimal("1"))
    if label == "measurements.WaterMeasurement":
        return WaterMeasurement.objects.create(
            name="Boundary level", measurement_type="flow", unit="ft",
            measurement_date=moment, value=Decimal("5"),
        )
    return RechargeMeasurement.objects.create(
        recharge_site=RechargeSiteFactory(), measurement_date=moment,
        measurement_type="flow_rate", value=Decimal("1"), unit="cfs",
    )


DATETIME_LABELS = (
    "measurements.MeterReading",
    "measurements.WaterMeasurement",
    "recharge.RechargeMeasurement",
)


@pytest.mark.parametrize("label", DATETIME_LABELS)
def test_23_30_pacific_on_the_last_day_is_locked_and_00_30_on_the_next_years_first_day_is_not(
    periods, label
):
    closed, _ = periods
    _finalize(closed)
    last_night = dt.datetime(2025, 9, 30, 23, 30, tzinfo=PACIFIC)
    first_night = dt.datetime(2025, 10, 1, 0, 30, tzinfo=PACIFIC)
    # The reason the zone matters: in UTC the first moment is already October 1.
    assert last_night.astimezone(dt.timezone.utc).date() == dt.date(2025, 10, 1)
    assert settings.TIME_ZONE == "America/Los_Angeles"

    _refused(lambda: _datetime_row(label, last_night))
    kept = _datetime_row(label, first_night)
    assert type(kept).objects.filter(pk=kept.pk).count() == 1


def test_the_lock_reads_the_day_in_the_sites_time_zone_whatever_it_is(periods):
    """Every connection carries the site's TIME_ZONE; a site on Eastern time gets Eastern days."""
    from accounting.locks import TIME_ZONE_SETTING

    closed, _ = periods
    _finalize(closed)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [TIME_ZONE_SETTING])
        assert cursor.fetchone()[0] == settings.TIME_ZONE
    # 23:30 Pacific on Sep 30 is 02:30 Eastern on Oct 1: in the open year for an Eastern site.
    last_night = dt.datetime(2025, 9, 30, 23, 30, tzinfo=PACIFIC)
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, 'America/New_York', true)", [TIME_ZONE_SETTING])
    kept = _datetime_row("measurements.MeterReading", last_night)
    assert type(kept).objects.filter(pk=kept.pk).count() == 1
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", [TIME_ZONE_SETTING, settings.TIME_ZONE])
    _refused(lambda: _datetime_row("measurements.MeterReading", last_night))


# -- the three columns that are not a plain date ---------------------------------------------


def test_a_lab_result_takes_its_events_sample_date(periods):
    from drinking.models import SampleResult
    from tests.factories import SampleEventFactory, SampleResultFactory

    closed, opened = periods
    in_closed = SampleResultFactory(event__sample_date=CLOSED_DAY)
    in_open = SampleResultFactory(event__sample_date=OPEN_DAY)
    open_event = in_open.event
    closed_event = in_closed.event
    _finalize(closed)

    _refused(lambda: SampleResult.objects.filter(pk=in_closed.pk).update(unit="ug/L"))
    assert SampleResult.objects.filter(pk=in_open.pk).update(unit="ug/L") == 1
    # A result cannot be moved onto an event in a finalized year, or off one.
    _refused(lambda: SampleResult.objects.filter(pk=in_open.pk).update(event=closed_event))
    _refused(lambda: SampleResult.objects.filter(pk=in_closed.pk).update(event=open_event))
    # The event itself is not locked: only the results hang on its date.
    assert SampleEventFactory(sample_date=CLOSED_DAY).pk


def test_a_production_record_with_no_month_is_read_as_january(periods):
    from drinking.models import SystemProduction
    from tests.factories import WaterSystemFactory

    closed, _ = periods
    _finalize(closed)
    system = WaterSystemFactory()

    def make(year, month):
        return SystemProduction.objects.create(
            system=system, year=year, month=month, type_code="GW",
            volume_as_reported=Decimal("10"), unit_as_reported="G", provenance="typed",
        )

    _refused(lambda: make(2025, None))   # January 2025 is in WY 2024-2025
    _refused(lambda: make(2025, 9))      # September 2025 is its last month
    assert make(2025, 10).pk             # October 2025 is not
    assert make(2026, None).pk           # January 2026 is not


def test_a_fallow_period_is_locked_by_the_months_it_covers_and_a_running_one_can_be_ended(periods):
    from parcels.models import FallowPeriod
    from tests.factories import ParcelFactory

    closed, _ = periods
    open_ended = FallowPeriod.objects.create(parcel=ParcelFactory(), start_month=dt.date(2025, 3, 1))
    before = FallowPeriod.objects.create(parcel=ParcelFactory(), end_month=dt.date(2025, 3, 1))
    _finalize(closed)

    # Inserts that cover a finalized month: a start in it, an end in it, a span across it.
    _refused(lambda: FallowPeriod.objects.create(parcel=ParcelFactory(), end_month=dt.date(2025, 3, 1)))
    _refused(lambda: FallowPeriod.objects.create(parcel=ParcelFactory(), start_month=dt.date(2025, 3, 1)))
    _refused(
        lambda: FallowPeriod.objects.create(
            parcel=ParcelFactory(), start_month=dt.date(2023, 1, 1), end_month=dt.date(2026, 3, 1)
        )
    )
    assert FallowPeriod.objects.create(parcel=ParcelFactory(), start_month=dt.date(2025, 10, 1)).pk
    assert FallowPeriod.objects.create(
        parcel=ParcelFactory(), start_month=dt.date(2023, 1, 1), end_month=dt.date(2024, 9, 1)
    ).pk

    # A running period that began in the finalized year can be ended, at the year's
    # last month or after it; it cannot be ended inside the year, moved or removed.
    FallowPeriod.objects.filter(pk=open_ended.pk).update(end_month=dt.date(2025, 9, 1))
    FallowPeriod.objects.filter(pk=open_ended.pk).update(end_month=dt.date(2025, 11, 1))
    _refused(lambda: FallowPeriod.objects.filter(pk=open_ended.pk).update(end_month=dt.date(2025, 6, 1)))
    _refused(lambda: FallowPeriod.objects.filter(pk=open_ended.pk).update(start_month=dt.date(2025, 4, 1)))
    _refused(lambda: FallowPeriod.objects.filter(pk=open_ended.pk).delete())
    _refused(lambda: FallowPeriod.objects.filter(pk=before.pk).update(end_month=dt.date(2025, 4, 1)))


# -- (g) the imports and the typed reading -----------------------------------------------------


def _finalized_year(periods):
    closed, _ = periods
    _finalize(closed)
    return closed


def test_a_water_level_in_a_finalized_year_is_a_row_error_in_the_preview_and_on_commit(periods):
    from measurements.models import WaterMeasurement
    from tests.factories import WellFactory
    from tests.import_flow import csv_text_of
    from tests.test_water_levels_04 import FIELD_COLUMNS, _client, _csv_upload, _run_import, _user
    from wells import water_level_import

    WellFactory(name="Well Seven")
    _finalized_year(periods)
    rows = [
        {"WELL_NAME": "Well Seven", "MSMT_DATE": "2025-03-07", "GSE_GWE": "40.5"},
        {"WELL_NAME": "Well Seven", "MSMT_DATE": "2026-03-07", "GSE_GWE": "41.5"},
    ]
    mapping = {"well": "WELL_NAME", "date": "MSMT_DATE", "depth": "GSE_GWE"}

    plan = water_level_import.plan_rows(rows, mapping)
    assert [(e["line"], e["message"]) for e in plan["errors"]] == [(2, REFUSAL)]
    assert len(plan["new"]) == 1

    _preview, result = _run_import(
        _client(_user("importer")), _csv_upload(csv_text_of(rows)), FIELD_COLUMNS
    )
    assert REFUSAL in unescape(result)
    assert list(WaterMeasurement.objects.values_list("value", flat=True)) == [Decimal("41.5000")]

    with override(REASON):
        assert water_level_import.plan_rows(rows, mapping)["errors"] == []
        # The open year's row is on file now; the finalized year's is the one new row.
        new = water_level_import.plan_rows(rows, mapping)["new"]
        assert [r["moment"].year for r in new] == [2025]


def _lab_setup():
    from tests.factories import AnalyteFactory, SamplingPointFactory

    point = SamplingPointFactory(ps_code="CA1900001_F0001_001")
    AnalyteFactory(name="Nitrate")
    mapping = {
        "ps_code": "PS Code", "sample_date": "Sample Date", "analyte_name": "Analyte",
        "result": "Result", "unit": "Unit",
    }
    rows = [
        {"PS Code": point.ps_code, "Sample Date": day, "Analyte": "Nitrate",
         "Result": "1.2", "Unit": "mg/L"}
        for day in ("2025-03-05", "2026-03-05")
    ]
    return rows, mapping


def test_a_lab_result_in_a_finalized_year_is_a_row_error_in_the_preview_and_on_commit(periods):
    from drinking import importer
    from drinking.models import SampleResult

    rows, mapping = _lab_setup()
    _finalized_year(periods)

    validated = importer.validate_rows(rows, mapping)
    assert [r["errors"] for r in validated] == [[REFUSAL], []]
    counts = importer.commit_rows(validated, source_file="lab.csv")
    assert counts["results"] == 1
    assert list(SampleResult.objects.values_list("event__sample_date", flat=True)) == [
        dt.date(2026, 3, 5)
    ]

    SampleResult.objects.all().delete()
    with override(REASON):
        validated = importer.validate_rows(rows, mapping)
        assert [r["errors"] for r in validated] == [[], []]
        assert importer.commit_rows(validated, source_file="lab.csv")["results"] == 2
    assert SampleResult.objects.count() == 2


def test_a_lab_result_already_on_file_in_a_finalized_year_is_skipped_not_rewritten(periods):
    from drinking import importer
    from drinking.models import SampleResult

    rows, mapping = _lab_setup()
    rows = rows[:1]
    with override(REASON):
        importer.commit_rows(importer.validate_rows(rows, mapping), source_file="first.csv")
    _finalized_year(periods)
    SampleResult.objects.update  # the stored row stays untouched below

    validated = importer.validate_rows(rows, mapping)
    assert validated[0]["errors"] == []
    assert validated[0]["data"]["is_duplicate"] is True
    assert "fill_limits_pk" not in validated[0]["data"]
    assert importer.commit_rows(validated, source_file="again.csv")["results"] == 0
    assert SampleResult.objects.count() == 1


def test_a_production_month_in_a_finalized_year_is_a_row_error_in_the_preview_and_on_commit(periods):
    from drinking import production_import
    from drinking.models import SystemProduction
    from tests.factories import WaterSystemFactory

    system = WaterSystemFactory()
    _finalized_year(periods)

    def candidate(year, month, line):
        return {
            "year": year, "month": month, "type_code": "GW",
            "volume_as_reported": Decimal("100"), "unit_as_reported": "G",
            "source_lines": [line], "annual_in_january": False,
        }

    built = {
        "candidates": [candidate(2025, 3, 2), candidate(2026, 3, 3)],
        "errors": [], "skipped_rows": 0, "duplicate_rows_in_file": 0, "year_missing": False,
    }
    preview = production_import.commit_rows(built, system=system, provenance="typed", dry_run=True)
    assert preview["created"] == 1
    assert preview["errors"] == [{"line": "2", "message": REFUSAL}]
    assert SystemProduction.objects.count() == 0

    result = production_import.commit_rows(built, system=system, provenance="typed")
    assert result["created"] == 1
    assert result["errors"] == [{"line": "2", "message": REFUSAL}]
    assert list(SystemProduction.objects.values_list("year", "month")) == [(2026, 3)]

    SystemProduction.objects.all().delete()
    with override(REASON):
        loaded = production_import.commit_rows(built, system=system, provenance="typed")
    assert (loaded["created"], loaded["errors"]) == (2, [])


def test_a_typed_station_reading_in_a_finalized_year_is_a_row_error(periods):
    from datasync import typed_readings

    _finalized_year(periods)
    posted = {"observation_date": "2025-03-05", "value": "1.5", "parameter": "00065"}

    clean, errors = typed_readings.validate(posted)
    assert clean is None
    assert errors == [REFUSAL]
    clean, errors = typed_readings.validate({**posted, "observation_date": "2026-03-05"})
    assert errors == [] and clean.observation_date == dt.date(2026, 3, 5)

    with override(REASON):
        clean, errors = typed_readings.validate(posted)
    assert errors == [] and clean.observation_date == dt.date(2025, 3, 5)


def test_the_python_checks_stand_aside_only_inside_the_door(periods):
    from accounting.locks import (
        override_open,
        refuse_if_finalized,
        refuse_if_period_finalized,
        PeriodFinalized,
    )

    closed = _finalized_year(periods)
    assert override_open() is False
    with pytest.raises(PeriodFinalized):
        refuse_if_finalized(CLOSED_DAY)
    with pytest.raises(PeriodFinalized):
        refuse_if_period_finalized(closed)
    with override(REASON):
        assert override_open() is True
        refuse_if_finalized(CLOSED_DAY)
        refuse_if_period_finalized(closed)
    assert override_open() is False
    with pytest.raises(PeriodFinalized):
        refuse_if_finalized(CLOSED_DAY)
    assert ReportingPeriod.objects.get(pk=closed.pk).is_finalized
