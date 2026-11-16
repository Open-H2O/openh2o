# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calculation writes only what changed.

Every night the schedule calculates each open water year again. A month whose
records did not change must come out the same and leave every stored row as it
was: no row deleted and written back, no change history, the same row ids, the
same creation times and the same transaction dates. When one record changes,
the next run updates only the rows that record reaches, in place, and the
figures equal what a calculation from nothing gives on the same records.

Fixture (``world``): a water year of January and February 2024, five 10-acre
fields with crop ET in both months.

- A, B and C have unmetered wells and take canal water from one point of
  diversion divided by crop need, with 10 percent seepage, so each run writes
  calculated groundwater rows, split rows, a month's canal loss and, with the
  site set to credit seepage by acre, a credit to A's account. January's
  delivery is more than the three fields can use, so it leaves unallocated
  canal water.
- D has a well with a meter read in January, so the run writes D's share of
  the well's meter.
- E has no well and no canal water: its run records unmet demand.

One test also runs on the Merced demonstration (``load_demonstration``).
"""
import datetime as dt
import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db.models import F
from django.utils import timezone

from accounting.models import AccountCredit, CalculationRun, ReportingPeriod, WaterAccount
from core.changes import event_models
from core.models import SiteConfig
from datasync.models import CropETFigure
from measurements.models import Meter, MeterReading
from parcels.models import Parcel, ParcelLedger
from surface.models import CanalMonthLoss, DiversionRecord, UnallocatedDelivery
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterAccountParcelFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)
from tests.test_calculation_run import _et_cache, _irrigate, _parcel
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

JAN = dt.date(2024, 1, 1)
FEB = dt.date(2024, 2, 1)
ET_MM = 304.8  # 10.0000 AF over 10 acres


class World:
    """The fixture's rows, by name."""


@pytest.fixture
def world():
    w = World()
    call_command("seed_calculation_plan", stdout=io.StringIO())
    config = SiteConfig.objects.first() or SiteConfig()
    config.canal_seepage_credit = "by_acre"
    config.save()
    w.period = ReportingPeriodFactory(
        name="Winter 2024", start_date=JAN, end_date=dt.date(2024, 2, 29)
    )
    w.fields = {}
    for name in "ABCDE":
        parcel = _parcel(f"WC-{name}", acres="10")
        _irrigate(parcel)
        _et_cache(parcel, period="2024-01", et_mm=ET_MM)
        _et_cache(parcel, period="2024-02", et_mm=ET_MM)
        w.fields[name] = parcel
    for name in "ABC":
        WellIrrigatedParcelFactory(parcel=w.fields[name])
    w.pod = PointOfDiversionFactory(
        name="Test Canal Headgate",
        division_method="crop_need",
        evaporation_fraction=Decimal("0"),
        seepage_fraction=Decimal("0.10"),
        spill_fraction=Decimal("0"),
    )
    for name in "ABC":
        PointOfDiversionParcelFactory(
            point_of_diversion=w.pod, parcel=w.fields[name], fraction=Decimal("0.3333")
        )
    w.jan_record = DiversionRecordFactory(
        point_of_diversion=w.pod, reporting_period=w.period, month=JAN,
        volume_acre_feet=Decimal("80"),
    )
    w.feb_record = DiversionRecordFactory(
        point_of_diversion=w.pod, reporting_period=w.period, month=FEB,
        volume_acre_feet=Decimal("25"),
    )
    w.account = WaterAccount.objects.create(name="A's account", account_number="WC-1")
    WaterAccountParcelFactory(water_account=w.account, parcel=w.fields["A"])
    # D: a metered well. 5 AF pumped in January.
    well = WellFactory(name="WC-D well")
    WellIrrigatedParcelFactory(well=well, parcel=w.fields["D"], fraction=Decimal("1"))
    meter = Meter.objects.create(serial_number="WC-D-M", meter_type="totalizer", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    w.reading = MeterReading.objects.create(
        meter=meter,
        reading_date=timezone.make_aware(dt.datetime(2024, 1, 31, 12, 0)),
        previous_value=Decimal("100"),
        current_value=Decimal("105"),
        calculated_volume=Decimal("5"),
    )
    return w


def _run():
    call_command(
        "run_accounting", "--open-periods", "--trigger", "schedule", stdout=io.StringIO()
    )


def _event_counts():
    return {label: event.objects.count() for label, event in event_models().items()}


def _new_events(before):
    after = _event_counts()
    return {label: after[label] - before.get(label, 0) for label in after if after[label] != before.get(label, 0)}


def _figures():
    """Every stored figure the calculation writes, with no row ids and no times."""
    runs = sorted(
        tuple(
            str(getattr(r, f.attname))
            for f in CalculationRun._meta.concrete_fields
            if f.attname not in ("id", "created_at")
        )
        for r in CalculationRun.objects.all()
    )
    ledger = sorted(
        (r.parcel_id, r.effective_date, r.source_type, r.water_type_id, str(r.amount_acre_feet),
         r.description, r.reporting_period_id, r.divided_from_point_pk)
        for r in ParcelLedger.objects.all()
    )
    unallocated = sorted(
        (u.point_of_diversion_id, u.month, str(u.amount_acre_feet), str(u.delivery_acre_feet))
        for u in UnallocatedDelivery.objects.all()
    )
    losses = sorted(
        (c.point_of_diversion_id, c.month, str(c.diverted_af), str(c.seepage_af), str(c.available_af))
        for c in CanalMonthLoss.objects.all()
    )
    credits = sorted(
        (c.water_account_id, c.source_key, str(c.amount_af), c.description)
        for c in AccountCredit.objects.all()
    )
    return {"runs": runs, "ledger": ledger, "unallocated": unallocated, "losses": losses, "credits": credits}


def _ids_and_times():
    runs = sorted(CalculationRun.objects.values_list("id", "parcel_id", "period", "created_at"))
    ledger = sorted(
        ParcelLedger.objects.values_list("id", "parcel_id", "effective_date", "source_type", "transaction_date")
    )
    return runs, ledger


def _age_the_rows(since=JAN):
    """Move the creation times and transaction dates from ``since`` back a week, as if written on an earlier night."""
    week = dt.timedelta(days=7)
    CalculationRun.objects.filter(period_start__gte=since).update(created_at=F("created_at") - week)
    ParcelLedger.objects.filter(effective_date__gte=since).update(transaction_date=F("transaction_date") - week)


def test_the_world_writes_every_kind_of_row(world):
    """The fixture reaches every write path the comparison covers (else the tests below prove less)."""
    _run()
    kinds = set(ParcelLedger.objects.values_list("source_type", flat=True))
    assert {"calculated", "surface_diversion", "meter_reading"} <= kinds
    assert ParcelLedger.objects.filter(description__startswith="From the well's meter:").exists()
    assert UnallocatedDelivery.objects.exists()
    assert CanalMonthLoss.objects.count() == 2
    assert AccountCredit.objects.filter(origin="canal_seepage").exists()
    assert CalculationRun.objects.filter(residual_disposition="unmet_demand").exists()


# -- (a) a run that changes nothing writes nothing ------------------------------


def test_a_second_run_with_nothing_changed_adds_no_change_history(world):
    _run()
    figures = _figures()
    before = _event_counts()
    _run()
    assert _new_events(before) == {}
    assert _figures() == figures


# -- (c) and keeps every row's id, creation time and transaction date -----------


def test_a_run_with_nothing_changed_keeps_ids_creation_times_and_transaction_dates(world):
    _run()
    _age_the_rows()
    kept = _ids_and_times()
    _run()
    assert _ids_and_times() == kept


# -- (b) one changed record reaches only its own rows, as updates ---------------


def _engine_rows_wiped():
    """Delete every row the calculation writes, so the next run starts from nothing."""
    CalculationRun.objects.all().delete()
    ParcelLedger.objects.filter(source_type="calculated").delete()
    ParcelLedger.objects.filter(divided_from_headgate=True).delete()
    ParcelLedger.objects.filter(description__startswith="From the well's meter:").delete()
    UnallocatedDelivery.objects.all().delete()
    CanalMonthLoss.objects.all().delete()
    AccountCredit.objects.filter(origin="canal_seepage").delete()


def _events_since(before_ids):
    """``{label: [(pgh_label, row as a dict)]}`` for every event written after ``before_ids``."""
    out = {}
    for label, event in event_models().items():
        rows = list(event.objects.filter(pgh_id__gt=before_ids.get(label, 0)).values())
        if rows:
            out[label] = [(r["pgh_label"], r) for r in rows]
    return out


def _top_ids():
    return {
        label: (event.objects.order_by("-pgh_id").values_list("pgh_id", flat=True).first() or 0)
        for label, event in event_models().items()
    }


def _assert_matches_a_run_from_nothing():
    """The figures after the change equal a calculation from nothing on the same records."""
    after_change = _figures()
    _engine_rows_wiped()
    _run()
    assert _figures() == after_change


def test_a_changed_crop_et_figure_updates_only_that_use_area_and_month(world):
    _run()
    CropETFigure.objects.filter(parcel=world.fields["E"], month=JAN).update(depth_mm=Decimal("400"))
    top = _top_ids()
    _run()
    events = _events_since(top)
    assert set(events) == {"accounting.CalculationRun"}
    labels = {kind for kind, _row in events["accounting.CalculationRun"]}
    assert labels <= {"before_update", "update"}
    assert {(row["parcel_id"], row["period"]) for _k, row in events["accounting.CalculationRun"]} == {
        (world.fields["E"].pk, "2024-01")
    }
    _assert_matches_a_run_from_nothing()


def test_a_changed_meter_reading_updates_only_that_use_areas_share(world):
    _run()
    MeterReading.objects.filter(pk=world.reading.pk).update(
        current_value=Decimal("107"), calculated_volume=Decimal("7")
    )
    top = _top_ids()
    _run()
    events = _events_since(top)
    assert set(events) == {"parcels.ParcelLedger"}
    rows = events["parcels.ParcelLedger"]
    assert {kind for kind, _row in rows} <= {"before_update", "update"}
    assert {(row["parcel_id"], row["effective_date"]) for _k, row in rows} == {(world.fields["D"].pk, JAN)}
    _assert_matches_a_run_from_nothing()


def test_a_changed_diversion_record_updates_only_its_month(world):
    _run()
    DiversionRecord.objects.filter(pk=world.feb_record.pk).update(volume_acre_feet=Decimal("20"))
    top = _top_ids()
    _run()
    events = _events_since(top)
    served = {world.fields[n].pk for n in "ABC"}
    for kind, row in events.get("parcels.ParcelLedger", []):
        assert kind in ("before_update", "update"), row
        assert row["parcel_id"] in served and row["effective_date"] == FEB, row
    for kind, row in events.get("accounting.CalculationRun", []):
        assert kind in ("before_update", "update"), row
        assert row["parcel_id"] in served and row["period"] == "2024-02", row
    for kind, row in events.get("surface.CanalMonthLoss", []):
        assert kind in ("before_update", "update") and row["month"] == FEB, row
    for kind, row in events.get("accounting.AccountCredit", []):
        assert kind in ("before_update", "update") and row["source_key"].endswith("2024-02"), row
    assert "parcels.ParcelLedger" in events
    _assert_matches_a_run_from_nothing()


# -- (f) a use area voided between runs still loses its rows ---------------------


def test_a_use_area_voided_between_runs_loses_its_engine_rows(world):
    _run()
    b = world.fields["B"]
    assert CalculationRun.objects.filter(parcel=b).exists()
    Parcel.objects.filter(pk=b.pk).update(voided_at=timezone.now())
    _run()
    assert not CalculationRun.objects.filter(parcel=b).exists()
    assert not ParcelLedger.objects.filter(parcel=b, source_type="calculated").exists()


# -- On the Merced demonstration -------------------------------------------------


def test_on_the_demonstration_a_second_run_writes_no_history_and_keeps_every_row():
    call_command("load_demonstration", stdout=io.StringIO())
    _run()
    # Only the open year: a finalized year's rows refuse a change.
    open_from = min(p.start_date for p in ReportingPeriod.objects.filter(is_finalized=False))
    _age_the_rows(open_from)
    figures = _figures()
    kept = _ids_and_times()
    before = _event_counts()
    _run()
    assert _new_events(before) == {}
    assert _figures() == figures
    assert _ids_and_times() == kept
