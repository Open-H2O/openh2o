# SPDX-License-Identifier: AGPL-3.0-or-later
"""
150-02 Task 2: the band a measured figure carries, from the devices' stated
accuracy (Brent's S2 ruling, 2026-09-20; settled in 150-02-PLAN.md).

A figure carries a band only when every record summed into it has a stated
accuracy: a diversion record through its measuring device's
``accuracy_percent``, a well meter through ``Well.accuracy_band``. The band of
a sum is the sum of each record's |volume| x its percent. Any summed record
without a stated accuracy leaves the figure with no band: ``None``, never zero.

Every expected value below is a literal worked by hand from the fixture, once
(DESIGN.md rule 12, review question 2). Each Decimal result is also checked as
a string, because ``Decimal("5") == Decimal("5.0000")`` and only the string
shows the four places the module quantizes to.
"""
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point

from accounting.bands import (
    band_words,
    meter_band,
    record_band,
    share_band,
    share_bands,
    sum_band,
)
from surface.models import MeasuringDevice
from tests.factories import DiversionRecordFactory, PointOfDiversionFactory
from wells.models import Well

pytestmark = pytest.mark.django_db


def _device(accuracy_percent):
    return MeasuringDevice.objects.create(
        nickname="Gate meter",
        device_type="inline_flow_meter",
        accuracy_percent=accuracy_percent,
    )


def _record(volume, device, method="device"):
    return DiversionRecordFactory(
        point_of_diversion=PointOfDiversionFactory(),
        volume_acre_feet=volume,
        method=method,
        device=device,
    )


def _well(accuracy_band):
    return Well.objects.create(
        name="Band test well",
        location=Point(-119.5, 36.5),
        accuracy_band=accuracy_band,
    )


# 1. one device at 5% on 100 AF
def test_one_device_at_five_percent_on_100_af():
    record = _record(Decimal("100.0000"), _device(Decimal("5.00")))

    band = record_band(record)

    assert band == Decimal("5.0000")
    assert str(band) == "5.0000"


# 2. two records at 5% (100 AF) and 2% (50 AF), summed
def test_two_records_sum_their_bands():
    first = _record(Decimal("100.0000"), _device(Decimal("5.00")))
    second = _record(Decimal("50.0000"), _device(Decimal("2.00")))

    band = sum_band([record_band(first), record_band(second)])

    assert band == Decimal("6.0000")
    assert str(band) == "6.0000"


# 3. one of two records without a device: the sum has no band
def test_one_record_without_a_device_leaves_the_sum_without_a_band():
    measured = _record(Decimal("100.0000"), _device(Decimal("5.00")))
    no_device = _record(Decimal("50.0000"), None)

    assert sum_band([record_band(measured), record_band(no_device)]) is None


# 4. an estimated_from_use record has no band, even with a device set
def test_estimated_from_use_record_has_no_band_even_with_a_device():
    record = _record(
        Decimal("100.0000"),
        _device(Decimal("5.00")),
        method="estimated_from_use",
    )

    assert record_band(record) is None


# 5. a share of 0.3 of a 100 AF record at 5%
def test_a_fields_share_carries_the_headgate_records_percent():
    record = _record(Decimal("100.0000"), _device(Decimal("5.00")))

    band = share_band(record, Decimal("0.3"))

    assert band == Decimal("1.5000")
    assert str(band) == "1.5000"


# 6. a well meter's DWR band: the range's upper bound; none for over 30 or blank
def test_well_meter_band_uses_the_dwr_bands_upper_bound():
    low = meter_band(_well("0-5"), Decimal("40.0000"))
    high = meter_band(_well("20-30"), Decimal("40.0000"))

    assert low == Decimal("2.0000")
    assert str(low) == "2.0000"
    assert high == Decimal("12.0000")
    assert str(high) == "12.0000"
    assert meter_band(_well("over_30"), Decimal("40.0000")) is None
    assert meter_band(_well(""), Decimal("40.0000")) is None


# 7. zero volume has a zero band; an empty sum has none
def test_zero_volume_has_a_zero_band_and_an_empty_sum_has_none():
    record = _record(Decimal("0.0000"), _device(Decimal("5.00")))

    band = record_band(record)

    assert band == Decimal("0.0000")
    assert str(band) == "0.0000"
    assert sum_band([]) is None


# 8. a device with a blank accuracy_percent has no band
def test_device_with_no_stated_accuracy_has_no_band():
    record = _record(Decimal("100.0000"), _device(None))

    assert record_band(record) is None


# 9. the tooltip's words, the percent without trailing zeros
def test_band_words_name_the_devices_stated_accuracy():
    assert band_words(Decimal("5.00")) == (
        "The band comes from the measuring device's stated accuracy (±5%)."
    )
    assert band_words(Decimal("2.50")) == (
        "The band comes from the measuring device's stated accuracy (±2.5%)."
    )


# 10. a field's share of a month's headgate records (coordinator, 2026-10-08)
def test_a_fields_share_of_a_months_headgate_records():
    records = [
        _record(Decimal("100.0000"), _device(Decimal("5.00"))),
        _record(Decimal("50.0000"), _device(Decimal("2.00"))),
    ]

    band = share_bands(records, Decimal("0.3"))

    assert band == Decimal("1.8000")
    assert str(band) == "1.8000"
