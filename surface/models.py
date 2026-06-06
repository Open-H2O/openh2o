# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Surface models.

The surface-water supply domain. WaterRight (and WaterRightType) carry the
diversion entitlement and its CalWATRS PIN; PointOfDiversion is where that water
is taken from a stream, with PointOfDiversionParcel linking a diversion to the
parcels it serves. DiversionRecord logs each diversion event, including the
returned_af that distinguishes diverted from actually consumed water.
CurtailmentOrder records when a right is curtailed.
"""
from decimal import Decimal

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError


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
    calwatrs_pin = models.CharField(
        max_length=50,
        blank=True,
        help_text="CalWATRS PIN mailed by SWRCB for this water right. The state "
        "issues one PIN per right; supplied by the agency, not fetched by OpenH2O.",
    )
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

    water_right = models.ForeignKey(WaterRight, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200)
    location = models.PointField(srid=4326)
    rediverted_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rediversions",
        help_text="Upstream point of diversion this point re-diverts from "
        "(one hop; the return-flow source).",
    )
    stream_name = models.CharField(max_length=200, blank=True)
    source_flowline = models.ForeignKey(
        "geography.Flowline",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diversions",
        help_text="The real NHD/canal waterway this diversion sits on "
        "(provenance). stream_name stays the human-readable eWRIMS label.",
    )
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
    returned_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Agency-asserted acre-feet of this diversion returned to the "
        "stream (0 = fully consumed; = full volume for non-consumptive / "
        "hydropower passthrough).",
    )
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

    def consumed_acre_feet(self):
        """The consumed magnitude of this diversion: abs(volume) − returned.

        Single source of truth for every ledger writer. Returned water (hydro
        passthrough, return flow) is withheld here so only the consumed portion
        ever reaches ``net_consumptive_use_af``. ``abs`` because surface
        diversions are stored negative by production convention.
        """
        return abs(self.volume_acre_feet) - self.returned_af

    def is_non_consumptive(self):
        """True when the full diverted volume is returned to the stream.

        A hydropower / run-of-river passthrough returns everything it takes, so
        its consumed magnitude is zero — the detail page labels it
        "Non-consumptive (returned to stream)" to distinguish it from an ordinary
        irrigation diversion that consumes what it diverts.
        """
        return self.returned_af > 0 and self.consumed_acre_feet() == 0

    def is_partial_return(self):
        """True when SOME but not all of the diverted volume is returned."""
        return Decimal("0") < self.returned_af < abs(self.volume_acre_feet)

    def clean(self):
        """Reject a return flow larger than the diverted volume.

        A typo where returned > diverted would make ``consumed`` negative and
        flip the consumptive spine the wrong way, so guard it at the model.
        """
        super().clean()
        if (
            self.returned_af is not None
            and self.volume_acre_feet is not None
            and self.returned_af > abs(self.volume_acre_feet)
        ):
            raise ValidationError(
                {"returned_af": "Return flow cannot exceed the diverted volume."}
            )

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
