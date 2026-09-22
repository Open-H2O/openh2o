# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 2: the CalWATRS worksheet's Measurement Method column prefers a
DiversionRecord's own ``method`` (and its device's type, when method is
'device') over any other inference. GEARS never reads a DiversionRecord (it
is a groundwater filing built from ParcelLedger only, see
reporting/generators.py lines 363-483) so its existing source_type inference
(``gears_method``) is unchanged and untested here again.

No filing path is implied: OpenH2O prepares this CSV, it does not submit it
("prepared, never filed", docs/DATA-STANDARDS.md).
"""
import csv
from datetime import date
from decimal import Decimal

import pytest

from reporting.generators import calwatrs_method_label, generate_calwatrs_csv
from surface.models import MeasuringDevice, PointOfDiversionDevice
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
)

pytestmark = pytest.mark.django_db


def _period():
    return ReportingPeriodFactory(
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
    )


def _data_rows(content):
    rows = list(csv.reader(content.splitlines()))
    return [r for r in rows[1:] if r and not r[0].startswith("DEMONSTRATION")]


def _header(content):
    return list(csv.reader(content.splitlines()))[0]


# ---------------------------------------------------------------------------
# The helper directly
# ---------------------------------------------------------------------------


def test_calwatrs_method_label_prefers_the_records_own_method():
    device = MeasuringDevice.objects.create(
        nickname="Atwater flow meter", device_type="inline_flow_meter",
    )
    record = DiversionRecordFactory.build(method="device", device=device)
    assert calwatrs_method_label(record) == "A measuring device: Inline flow meter"


def test_calwatrs_method_label_without_a_device_uses_the_method_label_alone():
    record = DiversionRecordFactory.build(method="methodology", device=None)
    assert calwatrs_method_label(record) == "A measurement methodology on file"


def test_calwatrs_method_label_blank_method_reports_not_stated():
    record = DiversionRecordFactory.build(method="", device=None)
    assert calwatrs_method_label(record) == "Not stated"


# ---------------------------------------------------------------------------
# Through the CSV: the record-first path
# ---------------------------------------------------------------------------


def test_calwatrs_csv_carries_measurement_method_column_from_the_record():
    period = _period()
    pod = PointOfDiversionFactory(water_right=WaterRightFactory())
    device = MeasuringDevice.objects.create(
        nickname="Atwater flow meter", device_type="inline_flow_meter",
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=device, is_current=True,
    )
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=period,
        month=date(2024, 3, 1),
        volume_acre_feet=Decimal("40.0000"),
        diversion_type="direct_use",
        method="device",
        device=device,
    )

    content = generate_calwatrs_csv(period, template_type="a1").read()
    header = _header(content)
    assert "Measurement Method" in header
    method_idx = header.index("Measurement Method")

    rows = _data_rows(content)
    assert len(rows) == 1
    assert rows[0][method_idx] == "A measuring device: Inline flow meter"


def test_calwatrs_csv_reports_not_stated_when_the_record_has_no_method():
    period = _period()
    pod = PointOfDiversionFactory(water_right=WaterRightFactory())
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=period,
        month=date(2024, 4, 1),
        volume_acre_feet=Decimal("10.0000"),
        diversion_type="direct_use",
        method="",
        device=None,
    )

    content = generate_calwatrs_csv(period, template_type="a1").read()
    header = _header(content)
    method_idx = header.index("Measurement Method")

    rows = _data_rows(content)
    assert rows[0][method_idx] == "Not stated"


def test_calwatrs_return_flow_column_untouched_by_the_new_method_column():
    """The pre-existing Return Flow column stays at its documented index
    (tests/test_state_exports.py::TestCalwatrsReturnFlowColumn) -- the new
    Measurement Method column is appended, never inserted, so it cannot shift
    any existing reader's column offsets."""
    period = _period()
    pod = PointOfDiversionFactory(water_right=WaterRightFactory())
    DiversionRecordFactory(
        point_of_diversion=pod,
        reporting_period=period,
        month=date(2024, 5, 1),
        volume_acre_feet=Decimal("20.0000"),
        diversion_type="direct_use",
    )

    content = generate_calwatrs_csv(period, template_type="a1").read()
    header = _header(content)
    assert header[11] == "Return Flow (AF)"
    assert header[12] == "Measurement Method"
