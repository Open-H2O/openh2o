# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GEARS by-ET file has one row per well and month.

The Board's GEARS guide takes extraction per well, even when crop ET is the method,
and splits a parcel's figure across the wells that serve it. So the by-ET file:

  * leaves out a use area with no linked well;
  * writes each use area's month at its groundwater extraction estimate, the
    figure the account pages count (the calculation's ETAW met by groundwater
    divided by the use area's irrigation efficiency);
  * leaves out a month with crop ET recorded and no calculation;
  * puts each linked well's part of a use area's month on that well's row, divided
    by the links' shares;
  * adds the parts of every use area a well serves on that well's row;
  * leaves a month a well's meter covers to the by-well file;
  * names a well with the by-well file's well columns.
"""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from measurements.models import Meter, MeterReading
from reporting.generators import generate_gears_csv
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    ReportingPeriodFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

JAN = date(2024, 1, 1)
D = Decimal


def _lines(method, period):
    text = generate_gears_csv(period, method).getvalue()
    return [r for r in csv.reader(io.StringIO(text)) if r and not r[0].startswith("DEMONSTRATION")]


def _by_et(period):
    return _lines("by_et", period)[1:]


def _estimate(parcel, af, day=JAN):
    """A calculated unmetered use area-month whose extraction estimate is ``af``.

    The ledger row holds ETAW met by groundwater (0.8 of the extraction, as at an
    irrigation efficiency of 0.8); the month's run holds the extraction.
    """
    from accounting.models import CalculationRun

    ParcelLedgerFactory(
        parcel=parcel, source_type="calculated", amount_acre_feet=-(D(str(af)) * D("0.8")),
        effective_date=day, transaction_date=day,
    )
    CalculationRun.objects.create(
        parcel=parcel, period=day.strftime("%Y-%m"), gross_et_af=D(str(af)),
        net_consumptive_use_af=D(str(af)), effective_precip_af=D("0"), surface_water_af=D("0"),
        final_af=D(str(af)) * D("0.8"), residual_disposition="groundwater",
        gw_extracted_af=D(str(af)), groundwater_application_efficiency=D("0.800"),
    )


def _volumes(rows):
    """{(registration id, month): AF} from the by-ET rows (by-well columns)."""
    return {(r[0], r[4]): D(r[5]) for r in rows}


def test_a_use_area_with_no_linked_well_puts_no_line_in_the_file():
    period = ReportingPeriodFactory()
    _estimate(ParcelFactory(parcel_number="NO-WELL-1"), 12)
    linked = ParcelFactory(parcel_number="WITH-WELL-1")
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-A"), parcel=linked)
    _estimate(linked, 5)

    rows = _by_et(period)
    assert len(rows) == 1
    assert not any("NO-WELL-1" in cell for row in rows for cell in row)


def test_a_use_area_on_two_wells_is_divided_by_the_link_shares():
    period = ReportingPeriodFactory()
    field = ParcelFactory()
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-60"), parcel=field, fraction=D("0.6000"))
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-40"), parcel=field, fraction=D("0.4000"))
    _estimate(field, 10)

    assert _volumes(_by_et(period)) == {("REG-60", "2024-01"): D("6"), ("REG-40", "2024-01"): D("4")}


def test_shares_that_do_not_add_to_one_still_divide_the_whole_figure_once():
    """Two links left at the default share of 1 each split the month in half, never double it."""
    period = ReportingPeriodFactory()
    field = ParcelFactory()
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-X"), parcel=field, fraction=D("1"))
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-Y"), parcel=field, fraction=D("1"))
    _estimate(field, 9)

    volumes = _volumes(_by_et(period))
    assert sum(volumes.values()) == D("9")
    assert volumes[("REG-X", "2024-01")] == volumes[("REG-Y", "2024-01")]


def test_two_use_areas_on_one_well_add_on_that_wells_row():
    period = ReportingPeriodFactory()
    well = WellFactory(well_registration_id="REG-SUM")
    for af in (5, 3):
        field = ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=field)
        _estimate(field, af)

    assert _volumes(_by_et(period)) == {("REG-SUM", "2024-01"): D("8")}


def test_a_month_the_wells_meter_covers_stays_in_the_by_well_file_only():
    period = ReportingPeriodFactory()
    well = WellFactory(well_registration_id="REG-MET")
    field = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=field)
    meter = Meter.objects.create(serial_number="BYET-M1", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    MeterReading.objects.create(
        meter=meter, reading_date=datetime(2024, 1, 20, 12, tzinfo=timezone.utc),
        current_value=D("30"), calculated_volume=D("30"),
    )
    from datasync.models import CropETFigure

    CropETFigure.objects.create(
        parcel=field, month=JAN, variable="ET", model_name="Ensemble",
        depth_mm=D("9") * D("304.8") / field.area_acres,
    )
    _estimate(field, 4, day=date(2024, 2, 1))

    assert ("REG-MET", "2024-01") in {(r[0], r[4]) for r in _lines("by_well", period)[1:]}
    assert _volumes(_by_et(period)) == {("REG-MET", "2024-02"): D("4")}


def test_a_moved_meters_reading_is_on_the_line_of_the_well_it_was_on_that_day():
    period = ReportingPeriodFactory()
    old = WellFactory(well_registration_id="REG-OLD")
    new = WellFactory(well_registration_id="REG-NEW")
    meter = Meter.objects.create(serial_number="BYWELL-MOVED", unit="acre_feet")
    WellMeter.objects.create(well=old, meter=meter, removed_date=date(2024, 1, 1), is_current=False)
    WellMeter.objects.create(well=new, meter=meter, installed_date=date(2024, 1, 1), is_current=True)
    for day, af in ((datetime(2023, 12, 20, 20, tzinfo=timezone.utc), "10"),
                    (datetime(2024, 1, 20, 20, tzinfo=timezone.utc), "30")):
        MeterReading.objects.create(
            meter=meter, reading_date=day, current_value=D(af), calculated_volume=D(af),
        )

    lines = {(r[0], r[4]): D(r[5]) for r in _lines("by_well", period)[1:]}
    assert lines == {("REG-OLD", "2023-12"): D("10"), ("REG-NEW", "2024-01"): D("30")}


def test_a_month_with_crop_et_and_no_calculation_puts_no_line_in_the_file():
    period = ReportingPeriodFactory()
    field = ParcelFactory()
    WellIrrigatedParcelFactory(well=WellFactory(well_registration_id="REG-NOCALC"), parcel=field)
    from datasync.models import CropETFigure

    CropETFigure.objects.create(
        parcel=field, month=JAN, variable="ET", model_name="Ensemble",
        depth_mm=D("9") * D("304.8") / field.area_acres,
    )
    _estimate(field, 3, day=date(2024, 2, 1))

    assert _volumes(_by_et(period)) == {("REG-NOCALC", "2024-02"): D("3")}


def test_the_rows_carry_the_by_well_files_well_columns():
    period = ReportingPeriodFactory()
    well = WellFactory(well_registration_id="REG-COL", name="North pump")
    field = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=field)
    _estimate(field, 2)

    by_et = _lines("by_et", period)
    assert by_et[0] == _lines("by_well", period)[0]
    (row,) = by_et[1:]
    assert row[:5] == ["REG-COL", str(well), str(well.location.y), str(well.location.x), "2024-01"]
    assert row[6] == "Unmetered/Estimated"


def test_the_checks_count_use_areas_with_no_well_and_name_the_months_left_out():
    from datasync.models import CropETFigure
    from reporting.validators import validate_report

    period = ReportingPeriodFactory()
    unlinked, uncalculated, calculated = ParcelFactory(), ParcelFactory(), ParcelFactory()
    well = WellFactory(well_registration_id="REG-CHK")
    for field in (uncalculated, calculated):
        WellIrrigatedParcelFactory(well=well, parcel=field)
    for field in (unlinked, uncalculated):
        CropETFigure.objects.create(
            parcel=field, month=JAN, variable="ET", model_name="Ensemble",
            depth_mm=D("9") * D("304.8") / field.area_acres,
        )
    _estimate(calculated, 2)

    warnings = [m["message"] for m in validate_report(period, "gears_by_et") if m["level"] == "warning"]
    assert any(m.startswith("1 use area") for m in warnings)  # the one not linked to a well
    assert any("January 2024" in m and "for 1 use area," in m for m in warnings)  # the uncalculated month


def test_a_use_area_unlinked_after_its_months_were_calculated_is_counted_as_left_out():
    """Its calculated months put nothing in the file, so the check still counts it."""
    from reporting.validators import validate_report

    period = ReportingPeriodFactory()
    field = ParcelFactory()
    _estimate(field, 5)  # calculated while linked; the link is gone now

    assert _by_et(period) == []
    warnings = [m["message"] for m in validate_report(period, "gears_by_et") if m["level"] == "warning"]
    assert any(m.startswith("1 use area") for m in warnings)


def test_months_are_named_together_only_when_the_same_use_areas_wait_for_them():
    """August left out for one use area and September for another are two lines, not one."""
    from reporting.validators import _months_by_count

    aug, sep = date(2026, 8, 1), date(2026, 9, 1)
    assert len(_months_by_count({aug: {1}, sep: {2}})) == 2
    assert len(_months_by_count({aug: {1, 2}, sep: {1, 2}})) == 1
