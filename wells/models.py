from django.contrib.gis.db import models


MEASUREMENT_METHOD_CHOICES = [
    ("certified_meter", "Certified Meter"),
    ("unmetered_estimate", "Unmetered Estimate"),
    ("power_conversion", "Power Conversion"),
    ("et_method", "ET Method"),
]

PUMP_TYPE_CHOICES = [
    ("submersible", "Submersible"),
    ("turbine", "Turbine"),
    ("centrifugal", "Centrifugal"),
    ("other", "Other"),
]

# Vertical datum a depth/elevation is referenced to. A water-level "elevation"
# is meaningless without it. NAVD88 is the modern North American standard;
# NGVD29 is the legacy datum many older well records still use. Defined once
# here and reused by both Well and MonitoringWell.
VERTICAL_DATUM_CHOICES = [
    ("NAVD88", "NAVD88"),
    ("NGVD29", "NGVD29"),
]


class WellType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Well(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("destroyed", "Destroyed"),
        ("proposed", "Proposed"),
    ]

    well_registration_id = models.CharField(
        max_length=50, unique=True, blank=True, null=True
    )
    name = models.CharField(max_length=200)
    well_type = models.ForeignKey(
        WellType, on_delete=models.SET_NULL, null=True, blank=True
    )
    location = models.PointField(srid=4326)
    depth_ft = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    capacity_gpm = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    owner_name = models.CharField(max_length=200, blank=True)

    # State reporting (SGMA / GEARS backstop)
    year_pumping_began = models.IntegerField(null=True, blank=True)
    measurement_method = models.CharField(
        max_length=30, blank=True, choices=MEASUREMENT_METHOD_CHOICES
    )

    # Registry identifiers
    wcr_number = models.CharField(
        max_length=50, blank=True
    )  # DWR Well Completion Report #
    state_well_number = models.CharField(
        max_length=50, blank=True
    )  # State Well Number (Township/Range/Section)

    # Partner cross-walk identifiers — let a self-published feature line up with
    # the federal/state monitoring systems it also appears in.
    usgs_site_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="USGS NWIS site number (waterdata.usgs.gov), if this well is "
        "also a USGS monitoring site.",
    )
    wqx_monitoring_location_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="EPA WQX MonitoringLocationIdentifier (Water Quality Portal).",
    )

    # Vertical datum for screen-interval depths, so they can be expressed as
    # elevations for the Phase 32 SensorThings FeatureOfInterest.
    vertical_datum = models.CharField(
        max_length=10,
        blank=True,
        choices=VERTICAL_DATUM_CHOICES,
        help_text="Vertical datum (NAVD88 / NGVD29) the screen-interval depths "
        "reference. Required to express depths as elevations.",
    )

    # Construction (DWR Well Completion Report, Form 188)
    casing_diameter_in = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    casing_material = models.CharField(max_length=50, blank=True)
    screen_top_ft = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )  # depth to top of perforation/screen
    screen_bottom_ft = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    tested_yield_gpm = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )  # WCR pump-test yield (distinct from rated capacity_gpm)
    pump_type = models.CharField(max_length=30, blank=True, choices=PUMP_TYPE_CHOICES)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or self.well_registration_id or f"Well {self.pk}"


class WellMeter(models.Model):
    well = models.ForeignKey(Well, on_delete=models.CASCADE)
    meter = models.ForeignKey("measurements.Meter", on_delete=models.CASCADE)
    installed_date = models.DateField(null=True, blank=True)
    removed_date = models.DateField(null=True, blank=True)
    calibration_date = models.DateField(
        null=True, blank=True
    )  # GEARS rejects certified-meter dates >5yr (decision 29-02)
    is_current = models.BooleanField(default=True)

    class Meta:
        unique_together = [("well", "meter")]

    def __str__(self):
        return f"{self.well} - {self.meter}"


class WellIrrigatedParcel(models.Model):
    well = models.ForeignKey(Well, on_delete=models.CASCADE)
    parcel = models.ForeignKey("parcels.Parcel", on_delete=models.CASCADE)
    fraction = models.DecimalField(max_digits=5, decimal_places=4, default=1.0)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("well", "parcel")]

    def __str__(self):
        return f"{self.well} → {self.parcel} ({self.fraction})"


class MonitoringWell(models.Model):
    well = models.OneToOneField(Well, on_delete=models.CASCADE)
    monitoring_agency = models.CharField(max_length=200, blank=True)
    measurement_frequency = models.CharField(max_length=50, blank=True)
    reference_elevation_ft = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # The datum reference_elevation_ft is measured against. Without it the
    # elevation is ambiguous, so the datum belongs right here beside it.
    vertical_datum = models.CharField(
        max_length=10,
        blank=True,
        choices=VERTICAL_DATUM_CHOICES,
        help_text="Vertical datum (NAVD88 / NGVD29) for reference_elevation_ft.",
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Monitoring: {self.well}"
