# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Geography models.

The platform's spatial backbone: Boundary (the agency footprint, with its DWR
Bulletin 118 basin identity), Zone (GSA management areas / subbasins, and the
surface district that owns its own year-end recovery-horizon policy), and
Flowline (canals and natural hydrography). ZoneGroup and ParcelZone are the
membership links other apps reference to tie parcels into management areas.
"""
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.urls import reverse

from core.constants import RECOVERY_HORIZON_CHOICES
from core.history import track_changes


class BoundaryManager(models.Manager):
    """Resolve a Boundary by name, so fixtures can reference it without a pk.

    Primary keys are per-deployment accidents: the Merced Subbasin is pk 1 on
    staging and pk 6 on production, measured 2026-07-31. A committed fixture
    that names a pk therefore attaches its rows to whatever boundary happens to
    occupy that number — silently, and differently on every instance.
    ``data/merced/flowlines.json`` is dumped with ``--natural-foreign`` and
    loaded back through this method instead.
    """

    def get_by_natural_key(self, name):
        return self.get(name=name)


class Boundary(models.Model):
    objects = BoundaryManager()

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    geometry = gis_models.MultiPolygonField(srid=4326)
    area_sq_miles = models.FloatField(null=True, blank=True)
    # DWR Bulletin 118 basin/subbasin identity — the basin code WaDE and AB1755
    # expect for cross-agency reconciliation.
    basin_code = models.CharField(
        max_length=20,
        blank=True,
        help_text='DWR Bulletin 118 basin/subbasin number, e.g. "5-022.04" '
        "(Merced Subbasin). The basin identity WaDE/AB1755 expect.",
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

    def get_absolute_url(self):
        """The record's own page (the /id/ address 303s here).

        A boundary has no page of its own; the map is where it is drawn.
        """
        return reverse("geography:map")

    def natural_key(self):
        return (self.name,)


@track_changes()
class Zone(models.Model):
    ZONE_TYPE_CHOICES = [
        ("management_area", "Management area"),
        ("subbasin", "Subbasin"),
        ("custom", "Other area"),
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
    # Per-district override of the agency-wide recovery horizon.
    # A surface district is its own zone, so this is where "this district's
    # unused water expires at year-end" lives. Blank = inherit the SiteConfig
    # default, so an admin only sets the exceptions.
    recovery_horizon = models.CharField(
        max_length=16,
        choices=RECOVERY_HORIZON_CHOICES,
        blank=True,
        null=True,
        help_text="A different year-end choice for this zone. "
        "Blank uses the site default.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        """The record's own page (the /id/ address 303s here)."""
        return reverse("geography:zone_detail", args=[self.pk])


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


@track_changes()
class ParcelZone(models.Model):
    parcel = models.ForeignKey("parcels.Parcel", on_delete=models.CASCADE, related_name="parcel_zones")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="parcel_zones")
    # A field's membership of a zone runs for a span of dates. A blank start
    # means the field has always been in the zone, and a blank end means it
    # still is. A year's figures count the fields whose span touches the year,
    # so taking a field out later leaves a finished year as it was.
    start_date = models.DateField(
        null=True, blank=True,
        help_text="First day the field is in this zone. Blank means it always has been.",
    )
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Last day the field is in this zone. Blank means it still is.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parcel", "zone"],
                condition=models.Q(end_date__isnull=True),
                name="one_open_membership_per_field_and_zone",
            ),
        ]

    def __str__(self):
        return f"{self.parcel} - {self.zone}"

    def other_membership_of_the_same_kind(self):
        """Another membership of this field, in a zone of the same kind, that overlaps this one's dates.

        A field that left a zone on the day this membership starts is a hand-over, not an overlap.
        """
        if not self.parcel_id or not self.zone_id or not self.zone.zone_type:
            return None
        others = ParcelZone.objects.filter(
            parcel_id=self.parcel_id, zone__zone_type=self.zone.zone_type
        ).exclude(pk=self.pk).select_related("zone")
        for other in others:
            starts_before_we_end = other.start_date is None or self.end_date is None or other.start_date <= self.end_date
            ends_after_we_start = other.end_date is None or self.start_date is None or other.end_date > self.start_date
            if starts_before_we_end and ends_after_we_start:
                return other
        return None

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("The last day cannot be before the first day.")
        other = self.other_membership_of_the_same_kind()
        if other is not None:
            raise ValidationError(
                f"{self.parcel} is already in {other.zone.name}, which is the same kind of zone."
            )
