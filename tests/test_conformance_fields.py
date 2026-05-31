"""
Tests for the Phase 31-02 conformance field set + the Datastream model.

Locks the new constraints that Phases 32-33 read from:
- vertical_datum accepts NAVD88/NGVD29 (and blank) and rejects anything else,
- SensorMeasurement / MeterReading default to "provisional" quality,
- a Datastream's ``uom`` accessor reads through to its ObservedProperty's UCUM
  unit and never drifts from it (no stored copy),
- the Datastream uniqueness guard blocks a fully-specified duplicate series,
- basin_code persists on Boundary and Zone.

DB access is auto-enabled for all tests via the root conftest.py.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from datasync.models import DataSource, MonitoredStation
from measurements.models import Meter, MeterReading, Sensor, SensorMeasurement
from standards.models import Datastream, ObservedProperty
from tests.factories import BoundaryFactory, WellFactory, ZoneFactory


class TestVerticalDatum:
    """vertical_datum is a controlled choice: NAVD88, NGVD29, or blank."""

    def test_accepts_known_datums_and_blank(self):
        well = WellFactory()
        for datum in ("NAVD88", "NGVD29", ""):
            well.vertical_datum = datum
            well.full_clean()  # must not raise

    def test_rejects_unknown_datum(self):
        # WGS84 is a horizontal/geographic datum, not a vertical one.
        well = WellFactory()
        well.vertical_datum = "WGS84"
        with pytest.raises(ValidationError):
            well.full_clean()


class TestObservationQualityDefault:
    """Freshly created observations default to provisional (the honest default)."""

    def test_sensor_measurement_defaults_provisional(self):
        sensor = Sensor.objects.create(name="S1", sensor_type="level")
        m = SensorMeasurement.objects.create(
            sensor=sensor,
            measurement_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            value=Decimal("1.0"),
            unit="ft",
        )
        assert m.quality == "provisional"

    def test_meter_reading_defaults_provisional(self):
        meter = Meter.objects.create(serial_number="MTR-1")
        r = MeterReading.objects.create(
            meter=meter,
            reading_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            current_value=Decimal("100.0"),
        )
        assert r.quality == "provisional"


class TestDatastreamUom:
    """The unit-of-measurement reads live from the linked ObservedProperty."""

    def test_uom_returns_observed_property_ucum(self):
        op = ObservedProperty.objects.create(
            key="discharge", name="Discharge", usgs_pcode="00060",
            ucum_unit="[cft_i]/s",
        )
        ds = Datastream.objects.create(
            name="Kaweah discharge",
            observed_property=op,
            sensor=Sensor.objects.create(name="S1", sensor_type="flow"),
            well=WellFactory(),
        )
        assert ds.uom == "[cft_i]/s"

    def test_uom_does_not_drift_from_observed_property(self):
        # No stored column: change the concept's unit and uom follows.
        op = ObservedProperty.objects.create(key="x", name="X", ucum_unit="mm")
        ds = Datastream.objects.create(name="d", observed_property=op)
        op.ucum_unit = "Cel"
        op.save()
        assert Datastream.objects.get(pk=ds.pk).uom == "Cel"


class TestDatastreamUniquenessGuard:
    """A fully-specified (concept, sensor, well, station) tuple can't repeat."""

    def test_duplicate_full_series_blocked(self):
        op = ObservedProperty.objects.create(key="x", name="X", ucum_unit="mm")
        well = WellFactory()
        sensor = Sensor.objects.create(name="S", sensor_type="level")
        source = DataSource.objects.create(name="USGS", code="usgs")
        station = MonitoredStation.objects.create(
            data_source=source,
            external_station_id="11111",
            station_name="Test gauge",
            location=Point(-119.5, 36.5),
        )
        kwargs = dict(
            observed_property=op, sensor=sensor, well=well,
            monitored_station=station,
        )
        Datastream.objects.create(name="first", **kwargs)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Datastream.objects.create(name="dup", **kwargs)


class TestBasinCode:
    """DWR Bulletin 118 basin codes persist on Boundary and Zone."""

    def test_boundary_basin_code_and_huc_persist(self):
        b = BoundaryFactory(basin_code="5-022.11", huc="18030012")
        b.refresh_from_db()
        assert b.basin_code == "5-022.11"
        assert b.huc == "18030012"

    def test_zone_basin_code_persists(self):
        z = ZoneFactory(basin_code="5-022.11")
        z.refresh_from_db()
        assert z.basin_code == "5-022.11"
