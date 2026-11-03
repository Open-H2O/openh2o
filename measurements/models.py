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

from accounting.locks import finalized_period_lock
from core.corrections import CorrectableRecord
from core.history import track_changes

# Observation quality/status, following SensorThings + USGS semantics. Freshly
# synced or hand-entered data is "provisional" until a later workflow promotes
# it to "approved"; "estimated" marks values derived/filled rather than measured.
QUALITY_CHOICES = [
    ("provisional", "Provisional"),
    ("approved", "Approved"),
    ("estimated", "Estimated"),
]

#: The reasons a hand measurement of depth to water was not made, in DWR's
#: order. Each value is DWR's wording exactly (a published identifier keeps
#: the publisher's casing, DESIGN.md copy rule 2), so a DWR file imports
#: without translation.
NO_MEASUREMENT_REASONS = [
    (reason, reason)
    for reason in (
        "Pumping",
        "Temporarily inaccessible",
        "Dry well",
        "Can't get tape in casing",
        "Measurement Discontinued",
        "Tape hung up",
        "Well has been destroyed",
        "Pump house locked",
        "Flowing artesian well",
        "Unable to locate well",
        "Casing leaking or wet",
        "Special/Other",
    )
]

#: The ways a depth to water was measured, in DWR's order and wording.
WATER_LEVEL_METHODS = [
    (method, method)
    for method in (
        "Electric sounder measurement",
        "Steel tape measurement",
        "Acoustic or sonic sounder",
        "Airline measurement, pressure gage, or manometer",
        "Electronic pressure transducer",
        "Other",
        "Unknown",
    )
]


@track_changes()
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


@track_changes()
class MeterReading(CorrectableRecord):
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
        # A finalized water year is closed to change (accounting/locks.py).
        triggers = [finalized_period_lock(datetime_column="reading_date")]

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


@track_changes()
class WaterMeasurement(CorrectableRecord):
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
    #: Empty only for a groundwater level with a ``no_measurement_reason``: the
    #: visit happened and no depth was read.
    value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
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
    no_measurement_reason = models.CharField(
        verbose_name="Reason",
        max_length=40, blank=True, default="", choices=NO_MEASUREMENT_REASONS
    )
    method = models.CharField(
        verbose_name="Method",
        max_length=60, blank=True, default="", choices=WATER_LEVEL_METHODS
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measurement_date"]
        # A finalized water year is closed to change (accounting/locks.py).
        triggers = [finalized_period_lock(datetime_column="measurement_date")]
        constraints = [
            # A groundwater level is either a depth or a reason no depth was
            # read, never both and never neither. Other kinds are not held to it.
            models.CheckConstraint(
                condition=(
                    ~models.Q(measurement_type="groundwater_level")
                    | (
                        models.Q(value__isnull=False, no_measurement_reason="")
                        | models.Q(value__isnull=True, no_measurement_reason__gt="")
                    )
                ),
                name="groundwater_level_depth_or_reason",
            ),
        ]

    def __str__(self):
        if self.value is None:
            return f"{self.name}: {self.no_measurement_reason} @ {self.measurement_date}"
        return f"{self.name}: {self.value} {self.unit} @ {self.measurement_date}"
