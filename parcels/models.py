# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Parcels models.

The parcel domain — the agricultural fields whose satellite-measured
consumptive use (ET) is the spine of the accounting. Parcel is the spatial
land unit; CropType and UsageLocation describe what is grown where on it;
ParcelLedger is the per-parcel water-accounting ledger (ET estimates, surface
deliveries, recharge, allocations, and the calculated groundwater residual);
ParcelStaging holds raw rows awaiting import.
"""
from django.conf import settings
from django.contrib.gis.db import models


class CropType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Parcel(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("pending", "Pending"),
    ]

    parcel_number = models.CharField(max_length=50, unique=True)
    owner_name = models.CharField(max_length=200, blank=True)
    area_acres = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    area_override = models.BooleanField(
        default=False,
        help_text="When checked, area_acres is manually set and will not be auto-calculated from geometry."
    )
    geometry = models.MultiPolygonField(srid=4326, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.parcel_number


# Sign is semantic, not cosmetic: the ledger nets to a balance, so a sign-flipped
# row does not look wrong — it quietly moves the balance by twice its magnitude.
# These two sets are what ParcelLedger's check constraints enforce (math eval
# 2026-07-18, F-data-04). Module scope because ParcelLedger.Meta needs them and a
# nested class body cannot see the enclosing class's namespace.
#
# SUPPLY rows credit water and must be > 0.
POSITIVE_SOURCE_TYPES = ("allocation", "recharge")
# USAGE rows debit water and must be <= 0. Zero is legitimate and common: a meter
# that did not advance, or a month with no measured diversion.
NON_POSITIVE_SOURCE_TYPES = (
    "meter_reading",
    "et_estimate",
    "surface_diversion",
    "calculated",
)
# Everything else (manual_entry, csv_import, adjustment) is deliberately
# unconstrained — an operator correction has to be able to go either way.


class ParcelLedger(models.Model):
    SOURCE_TYPE_CHOICES = [
        ("meter_reading", "Meter Reading"),
        ("et_estimate", "ET Estimate"),
        ("manual_entry", "Manual Entry"),
        ("csv_import", "CSV Import"),
        ("surface_diversion", "Surface Diversion"),
        ("recharge", "Recharge"),
        ("allocation", "Allocation"),
        ("adjustment", "Adjustment"),
        ("calculated", "Calculated"),
    ]

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE)
    transaction_date = models.DateField()
    effective_date = models.DateField()
    amount_acre_feet = models.DecimalField(max_digits=12, decimal_places=4)
    water_type = models.ForeignKey(
        "accounting.WaterType", on_delete=models.PROTECT, null=True, blank=True
    )
    source_type = models.CharField(max_length=50, choices=SOURCE_TYPE_CHOICES)
    description = models.TextField(blank=True)
    reporting_period = models.ForeignKey(
        "accounting.ReportingPeriod", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Re-exported from module scope (see above ParcelLedger) so callers can say
    # ParcelLedger.POSITIVE_SOURCE_TYPES; Meta itself must use the module names,
    # because a nested class body cannot see the enclosing class's namespace.
    POSITIVE_SOURCE_TYPES = POSITIVE_SOURCE_TYPES  # noqa: F821
    NON_POSITIVE_SOURCE_TYPES = NON_POSITIVE_SOURCE_TYPES  # noqa: F821

    class Meta:
        ordering = ["-effective_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    ~models.Q(source_type__in=POSITIVE_SOURCE_TYPES)
                    | models.Q(amount_acre_feet__gt=0)
                ),
                name="parcelledger_supply_rows_positive",
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(source_type__in=NON_POSITIVE_SOURCE_TYPES)
                    | models.Q(amount_acre_feet__lte=0)
                ),
                name="parcelledger_usage_rows_non_positive",
            ),
        ]

    def __str__(self):
        return f"{self.parcel} {self.amount_acre_feet:+} AF {self.effective_date}"


class ParcelStaging(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("imported", "Imported"),
        ("rejected", "Rejected"),
        ("duplicate", "Duplicate"),
    ]

    parcel_number = models.CharField(max_length=50)
    raw_data = models.JSONField(default=dict)
    geometry = models.MultiPolygonField(srid=4326, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.parcel_number} ({self.status})"


class UsageLocation(models.Model):
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    crop_type = models.ForeignKey(
        CropType, on_delete=models.SET_NULL, null=True, blank=True
    )
    area_acres = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    geometry = models.PointField(srid=4326, null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name
