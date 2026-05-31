from django.contrib.gis.db import models as gis_models
from django.db import models


class Boundary(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    geometry = gis_models.MultiPolygonField(srid=4326)
    area_sq_miles = models.FloatField(null=True, blank=True)
    # DWR Bulletin 118 basin/subbasin identity — the basin code WaDE and AB1755
    # expect for cross-agency reconciliation.
    basin_code = models.CharField(
        max_length=20,
        blank=True,
        help_text='DWR Bulletin 118 basin/subbasin number, e.g. "5-022.11" '
        "(Kaweah). The basin identity WaDE/AB1755 expect.",
    )
    huc = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional USGS Hydrologic Unit Code (HUC) for the area.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "boundaries"

    def __str__(self):
        return self.name


class Zone(models.Model):
    ZONE_TYPE_CHOICES = [
        ("management_area", "Management Area"),
        ("subbasin", "Subbasin"),
        ("custom", "Custom"),
    ]

    name = models.CharField(max_length=200)
    boundary = models.ForeignKey(Boundary, on_delete=models.CASCADE, related_name="zones")
    description = models.TextField(blank=True)
    geometry = gis_models.MultiPolygonField(srid=4326)
    zone_type = models.CharField(max_length=50, blank=True, choices=ZONE_TYPE_CHOICES)
    # A zone may map to one specific DWR Bulletin 118 subbasin.
    basin_code = models.CharField(
        max_length=20,
        blank=True,
        help_text='DWR Bulletin 118 subbasin number this zone maps to, e.g. "5-022.11".',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Flowline(models.Model):
    name = models.CharField(max_length=200, blank=True)
    boundary = models.ForeignKey(Boundary, on_delete=models.CASCADE, related_name="flowlines")
    feature_type = models.CharField(max_length=100, blank=True)
    length_km = models.FloatField(null=True, blank=True)
    stream_order = models.IntegerField(null=True, blank=True)
    source_id = models.CharField(max_length=20, blank=True)
    geometry = gis_models.MultiLineStringField(srid=4326)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or self.source_id or f"Flowline {self.pk}"


class ZoneGroup(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    zones = models.ManyToManyField(Zone, blank=True, related_name="groups")

    def __str__(self):
        return self.name


class ParcelZone(models.Model):
    parcel = models.ForeignKey("parcels.Parcel", on_delete=models.CASCADE, related_name="parcel_zones")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="parcel_zones")

    class Meta:
        unique_together = ("parcel", "zone")

    def __str__(self):
        return f"{self.parcel} - {self.zone}"
