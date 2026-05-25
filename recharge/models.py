from django.contrib.gis.db import models


class RechargeSite(models.Model):
    SITE_TYPE_CHOICES = [
        ("spreading_basin", "Spreading Basin"),
        ("injection_well", "Injection Well"),
        ("streambed", "Streambed"),
        ("asr_well", "ASR Well"),
        ("storage_pond", "Storage Pond"),
        ("storage_tank", "Storage Tank"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("proposed", "Proposed"),
    ]

    name = models.CharField(max_length=200)
    site_type = models.CharField(
        max_length=50, choices=SITE_TYPE_CHOICES, default="spreading_basin"
    )
    location = models.PointField(srid=4326)
    geometry = models.MultiPolygonField(srid=4326, null=True, blank=True)
    capacity_acre_feet = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    zone = models.ForeignKey(
        "geography.Zone", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="recharge_sites",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    operator = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class RechargeEvent(models.Model):
    recharge_site = models.ForeignKey(RechargeSite, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    volume_acre_feet = models.DecimalField(max_digits=12, decimal_places=4)
    water_type = models.ForeignKey(
        "accounting.WaterType", on_delete=models.SET_NULL, null=True, blank=True
    )
    source_description = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.recharge_site} {self.start_date}: {self.volume_acre_feet} AF"


class RechargeMeasurement(models.Model):
    MEASUREMENT_TYPE_CHOICES = [
        ("water_level", "Water Level"),
        ("flow_rate", "Flow Rate"),
        ("water_quality", "Water Quality"),
        ("infiltration_rate", "Infiltration Rate"),
    ]

    recharge_site = models.ForeignKey(RechargeSite, on_delete=models.CASCADE)
    measurement_date = models.DateTimeField()
    measurement_type = models.CharField(
        max_length=50, choices=MEASUREMENT_TYPE_CHOICES
    )
    value = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=20)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measurement_date"]

    def __str__(self):
        return f"{self.recharge_site} {self.measurement_type}: {self.value} {self.unit}"
