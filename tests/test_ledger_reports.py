# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The two GEARS files and the CalWATRS file write the figures the ledger holds.

  * The by-well file writes each well's own readings once, never re-weighted by
    the shares of the fields the well waters.
  * The by-ET file leaves out every field-month the by-well file holds.
  * The by-ET pre-flight counts the rows the file will hold.
  * A point that re-diverts water writes it in the re-diverted column, not as a
    second direct diversion.
"""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from measurements.models import Meter, MeterReading
from reporting.generators import generate_calwatrs_csv, generate_gears_csv
from reporting.validators import validate_report
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

JAN = date(2024, 1, 1)
D = Decimal


def _rows(text):
    return [r for r in csv.reader(io.StringIO(text)) if r and not r[0].startswith("DEMONSTRATION")]


def _by_well(period):
    return _rows(generate_gears_csv(period, "by_well").getvalue())[1:]


def _by_et(period):
    return _rows(generate_gears_csv(period, "by_et").getvalue())[1:]


def _typed_meter_row(parcel, af, day=date(2024, 1, 15)):
    return ParcelLedgerFactory(
        parcel=parcel, source_type="meter_reading", amount_acre_feet=-D(str(af)),
        effective_date=day, transaction_date=day, description="typed on the field",
    )


def _well_with_fields(n, fraction="0.2500"):
    well = WellFactory(well_registration_id="REG-RP")
    fields = [ParcelFactory() for _ in range(n)]
    for f in fields:
        WellIrrigatedParcelFactory(well=well, parcel=f, fraction=D(fraction))
    return well, fields


def test_by_well_writes_each_fields_own_reading_in_full():
    """Four fields on one well, each typed with its own reading (10, 20, 30, 40 AF)."""
    period = ReportingPeriodFactory()
    _, fields = _well_with_fields(4)
    for f, af in zip(fields, (10, 20, 30, 40)):
        _typed_meter_row(f, af)
    rows = _by_well(period)
    assert len(rows) == 1
    assert sum(D(r[5]) for r in rows) == D("100")


def test_by_well_writes_the_wells_own_reading_once():
    """One reading of 80 AF on the well's meter, already divided into four share rows."""
    period = ReportingPeriodFactory()
    well, fields = _well_with_fields(4)
    meter = Meter.objects.create(serial_number="RP-M1", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    MeterReading.objects.create(
        meter=meter, reading_date=datetime(2024, 1, 20, 12, tzinfo=timezone.utc),
        current_value=D("80"), calculated_volume=D("80"),
    )
    for f in fields:
        ParcelLedgerFactory(
            parcel=f, source_type="meter_reading", amount_acre_feet=-D("20"),
            effective_date=JAN, transaction_date=JAN,
            description="From the well's meter: Well pumped 80 AF this month, this field's share is 25%",
        )
    rows = _by_well(period)
    assert len(rows) == 1
    assert D(rows[0][5]) == D("80")


def test_by_well_writes_the_wells_reading_before_any_calculation_has_run():
    period = ReportingPeriodFactory()
    well, _ = _well_with_fields(4)
    meter = Meter.objects.create(serial_number="RP-M2", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    MeterReading.objects.create(
        meter=meter, reading_date=datetime(2024, 1, 20, 12, tzinfo=timezone.utc),
        current_value=D("80"), calculated_volume=D("80"),
    )
    rows = _by_well(period)
    assert [D(r[5]) for r in rows] == [D("80")]


def test_a_metered_field_month_is_in_by_well_and_not_in_by_et():
    period = ReportingPeriodFactory()
    _, fields = _well_with_fields(2, "0.5000")
    metered, unmetered = fields
    _typed_meter_row(metered, 15)
    for f in fields:
        ParcelLedgerFactory(
            parcel=f, source_type="et_estimate", amount_acre_feet=-D("9"),
            effective_date=JAN, transaction_date=JAN,
        )
    ParcelLedgerFactory(
        parcel=metered, source_type="calculated", amount_acre_feet=-D("7"),
        effective_date=JAN, transaction_date=JAN,
    )
    assert [D(r[5]) for r in _by_well(period)] == [D("15")]
    et_rows = _by_et(period)
    assert [r[0] for r in et_rows] == [unmetered.parcel_number]


def test_by_et_pre_flight_names_the_rows_the_file_holds():
    period = ReportingPeriodFactory()
    for _ in range(3):
        ParcelLedgerFactory(
            parcel=ParcelFactory(), source_type="calculated", amount_acre_feet=-D("5"),
            effective_date=JAN, transaction_date=JAN,
        )
    assert len(_by_et(period)) == 3
    messages = validate_report(period, "gears_by_et")
    text = " ".join(m["message"] for m in messages)
    assert "No ET estimates" not in text
    assert "3 rows" in text
    assert not [m for m in messages if m["level"] == "error"]


def test_by_well_pre_flight_does_not_call_a_wells_reading_missing():
    period = ReportingPeriodFactory()
    well, _ = _well_with_fields(2, "0.5000")
    meter = Meter.objects.create(serial_number="RP-M3", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    MeterReading.objects.create(
        meter=meter, reading_date=datetime(2024, 1, 20, 12, tzinfo=timezone.utc),
        current_value=D("40"), calculated_volume=D("40"),
    )
    ParcelLedgerFactory(
        parcel=ParcelFactory(), source_type="et_estimate", amount_acre_feet=-D("1"),
        effective_date=JAN, transaction_date=JAN,
    )
    messages = validate_report(period, "gears_by_well")
    assert not [m for m in messages if "No meter readings" in m["message"]]


def test_calwatrs_writes_a_re_diversion_in_its_own_column():
    """An upstream point diverts 100 AF and returns it; the downstream point re-diverts 100 AF."""
    period = ReportingPeriodFactory()
    right = WaterRightFactory()
    upstream = PointOfDiversionFactory(water_right=right, name="Upstream point")
    downstream = PointOfDiversionFactory(
        water_right=right, name="Downstream point", rediverted_from=upstream
    )
    DiversionRecordFactory(
        point_of_diversion=upstream, reporting_period=period, month=JAN,
        volume_acre_feet=D("100"), returned_af=D("100"), diversion_type="direct_use",
    )
    DiversionRecordFactory(
        point_of_diversion=downstream, reporting_period=period, month=JAN,
        volume_acre_feet=D("100"), diversion_type="direct_use",
    )
    text = generate_calwatrs_csv(period, "a1").getvalue()
    rows = _rows(text)
    header, data = rows[0], rows[1:]
    direct = header.index("Volume (AF)")
    rediverted = header.index("Re-diverted Volume (AF)")
    assert sum(D(r[direct]) for r in data) == D("100")
    assert sum(D(r[rediverted]) for r in data) == D("100")
    by_name = {r[2]: r for r in data}
    assert D(by_name["Downstream point"][direct]) == D("0")
    assert D(by_name["Downstream point"][rediverted]) == D("100")
    assert D(by_name["Upstream point"][rediverted]) == D("0")
