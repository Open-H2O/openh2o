# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the meter and sensor measurement models."""
from django.contrib import admin

from .models import Meter, MeterReading, Sensor, SensorMeasurement, WaterMeasurement


@admin.register(Meter)
class MeterAdmin(admin.ModelAdmin):
    list_display = ["serial_number", "meter_type", "unit", "status", "last_calibration_date"]
    list_filter = ["meter_type", "status"]
    search_fields = ["serial_number"]


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ["meter", "reading_date", "previous_value", "current_value", "calculated_volume"]
    raw_id_fields = ["meter"]
    date_hierarchy = "reading_date"


@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ["name", "sensor_type", "well", "status", "exclude_anomalies"]
    list_filter = ["sensor_type", "status", "exclude_anomalies"]
    search_fields = ["name", "serial_number"]


@admin.register(SensorMeasurement)
class SensorMeasurementAdmin(admin.ModelAdmin):
    list_display = ["sensor", "measurement_date", "value", "unit", "is_anomalous"]
    list_filter = ["is_anomalous"]
    raw_id_fields = ["sensor"]
    date_hierarchy = "measurement_date"


@admin.register(WaterMeasurement)
class WaterMeasurementAdmin(admin.ModelAdmin):
    list_display = ["name", "measurement_type", "value", "unit", "measurement_date", "source"]
    list_filter = ["measurement_type", "source"]
    date_hierarchy = "measurement_date"
