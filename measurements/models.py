# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Measurement domain models.

Owns the in-system measurement records: Meter and its MeterReading (totalizer/
flow/pressure/level readings with calculated volumes), Sensor and its
SensorMeasurement (well-tied telemetry with anomaly flags), and the generic
WaterMeasurement tied to a parcel or well. Each links to a standards
ObservedProperty and carries a SensorThings/USGS quality flag (provisional /
approved / estimated).
"""
from django.conf import settings
from django.contrib.gis.db import models

# Observation quality/status, following SensorThings + USGS semantics. Freshly
# synced or hand-entered data is "provisional" until a later workflow promotes
# it to "approved"; "estimated" marks values derived/filled rather than measured.
QUALITY_CHOICES = [
    ("provisional", "Provisional"),
    ("approved", "Approved"),
    ("estimated", "Estimated"),
]


class Meter(models.Model):
    METER_TYPE_CHOICES = [
        ("flow", "Flow"),
        ("totalizer", "Totalizer"),
        ("pressure", "Pressure"),
        ("level", "Level"),
    ]
    UNIT_CHOICES = [
        ("acre_feet", "Acre-Feet"),
        ("gallons", "Gallons"),
        ("cubic_feet", "Cubic Feet"),
        ("cfs", "Cubic Feet per Second"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("broken", "Broken"),
    ]

    serial_number = models.CharField(max_length=100, unique=True)
    meter_type = models.CharField(
        max_length=50, choices=METER_TYPE_CHOICES, default="totalizer"
    )
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="acre_feet")
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    last_calibration_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.serial_number


class MeterReading(models.Model):
    meter = models.ForeignKey(Meter, on_delete=models.CASCADE)
    observed_property = models.ForeignKey(
        "standards.ObservedProperty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meter_readings",
    )
    reading_date = models.DateTimeField()
    previous_value = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    current_value = models.DecimalField(max_digits=14, decimal_places=4)
    calculated_volume = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    quality = models.CharField(
        max_length=20,
        choices=QUALITY_CHOICES,
        default="provisional",
        help_text="Observation quality/status (SensorThings/USGS). Defaults to "
        "provisional until a review workflow approves it.",
    )
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reading_date"]

    def __str__(self):
        return f"{self.meter} @ {self.reading_date}: {self.current_value}"


class Sensor(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("maintenance", "Maintenance"),
    ]

    name = models.CharField(max_length=200)
    sensor_type = models.CharField(max_length=50)
    serial_number = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    well = models.ForeignKey(
        "wells.Well", on_delete=models.SET_NULL, null=True, blank=True
    )
    location = models.PointField(srid=4326, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    exclude_anomalies = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class SensorMeasurement(models.Model):
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
    observed_property = models.ForeignKey(
        "standards.ObservedProperty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sensor_measurements",
    )
    measurement_date = models.DateTimeField()
    value = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=20)
    quality = models.CharField(
        max_length=20,
        choices=QUALITY_CHOICES,
        default="provisional",
        help_text="Observation quality/status (SensorThings/USGS). Defaults to "
        "provisional until a review workflow approves it.",
    )
    is_anomalous = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measurement_date"]

    def __str__(self):
        return f"{self.sensor} @ {self.measurement_date}: {self.value}"


class WaterMeasurement(models.Model):
    SOURCE_CHOICES = [
        ("manual", "Manual"),
        ("automated", "Automated"),
        ("imported", "Imported"),
    ]

    name = models.CharField(max_length=200)
    measurement_type = models.CharField(max_length=50)
    observed_property = models.ForeignKey(
        "standards.ObservedProperty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="water_measurements",
    )
    value = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=20)
    measurement_date = models.DateTimeField()
    parcel = models.ForeignKey(
        "parcels.Parcel", on_delete=models.SET_NULL, null=True, blank=True
    )
    well = models.ForeignKey(
        "wells.Well", on_delete=models.SET_NULL, null=True, blank=True
    )
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default="manual")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measurement_date"]

    def __str__(self):
        return f"{self.name}: {self.value} {self.unit} @ {self.measurement_date}"
