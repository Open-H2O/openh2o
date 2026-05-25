from django.contrib.gis.db import models


class WaterRightType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class WaterRight(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("curtailed", "Curtailed"),
        ("revoked", "Revoked"),
    ]

    right_id = models.CharField(max_length=50, unique=True)
    right_type = models.ForeignKey(WaterRightType, on_delete=models.PROTECT)
    holder_name = models.CharField(max_length=200)
    priority_date = models.DateField(null=True, blank=True)
    face_value_acre_feet = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    source_name = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.right_id


class WaterRightParcel(models.Model):
    water_right = models.ForeignKey(
        WaterRight, on_delete=models.CASCADE, related_name="water_right_parcels"
    )
    parcel = models.ForeignKey(
        "parcels.Parcel", on_delete=models.CASCADE, related_name="water_right_parcels"
    )
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("water_right", "parcel")]

    def __str__(self):
        return f"{self.water_right} → {self.parcel}"


class PointOfDiversion(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    water_right = models.ForeignKey(WaterRight, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    location = models.PointField(srid=4326)
    stream_name = models.CharField(max_length=200, blank=True)
    max_rate_cfs = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class PointOfDiversionParcel(models.Model):
    point_of_diversion = models.ForeignKey(
        PointOfDiversion, on_delete=models.CASCADE, related_name="pod_parcels"
    )
    parcel = models.ForeignKey(
        "parcels.Parcel", on_delete=models.CASCADE, related_name="pod_parcels"
    )
    fraction = models.DecimalField(max_digits=5, decimal_places=4, default=1.0)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("point_of_diversion", "parcel")]

    def __str__(self):
        return f"{self.point_of_diversion} → {self.parcel} ({self.fraction})"


class DiversionRecord(models.Model):
    DIVERSION_TYPE_CHOICES = [
        ("direct_use", "Direct Use"),
        ("to_storage", "To Storage"),
    ]

    point_of_diversion = models.ForeignKey(PointOfDiversion, on_delete=models.CASCADE)
    reporting_period = models.ForeignKey(
        "accounting.ReportingPeriod", on_delete=models.SET_NULL, null=True, blank=True
    )
    month = models.DateField()
    volume_acre_feet = models.DecimalField(max_digits=12, decimal_places=4)
    max_flow_rate_cfs = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    diversion_type = models.CharField(
        max_length=50, choices=DIVERSION_TYPE_CHOICES, default="direct_use"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month"]
        unique_together = [("point_of_diversion", "month", "diversion_type")]

    def __str__(self):
        return f"{self.point_of_diversion} {self.month}: {self.volume_acre_feet} AF"


class CurtailmentOrder(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("expired", "Expired"),
        ("rescinded", "Rescinded"),
    ]

    order_id = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=300)
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    watershed = models.CharField(max_length=200, blank=True)
    priority_date_cutoff = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.order_id
