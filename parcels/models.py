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
from django.urls import reverse

from accounting.locks import finalized_period_lock
from core.history import track_changes


class CropType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


@track_changes()
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

    def get_absolute_url(self):
        """The record's own page (the /id/ address 303s here)."""
        return reverse("parcels:detail", args=[self.pk])


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


@track_changes()
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
    divided_from_headgate = models.BooleanField(
        default=False,
        help_text=(
            "Written by the canal split: this field's share of a headgate "
            "total. Replaced whenever that headgate's month is recalculated. "
            "Unticked rows are the field's own recorded delivery and are "
            "never replaced by the split."
        ),
    )
    # A plain number, not a foreign key: parcels is a module every deployment
    # has and surface is optional, so a reference into surface would dangle
    # when it is left out (the composition rule, tests/test_composition_rule.py).
    divided_from_point_pk = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "On a canal split row, the point of diversion whose headgate total "
            "it is a share of, so recalculating one point never replaces "
            "another point's shares on a field both serve. Blank on a field's "
            "own recorded delivery, and on split rows written before this field existed."
        ),
    )

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
        # A finalized water year is closed to change (accounting/locks.py).
        triggers = [
            finalized_period_lock(
                date_column="effective_date", period_column="reporting_period_id"
            )
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


@track_changes()
class IrrigationMethod(models.Model):
    """One row of a published irrigation-efficiency table.

    Seeded by a data migration, not a seed command, so every deployment
    carries the same rows after ``migrate``: East Turlock Subbasin GSA's
    Section 4.05 table, 18 rows counted off the PDF on 2026-09-23. Seeded first
    by ``surface/0016_seed_irrigation_methods``; now by
    ``parcels/0013_irrigation_method``, which also adopts the rows a deployment
    already had.

    Lives in ``parcels``, which helps groundwater-only growers and water
    managers: a field irrigated from a well has an irrigation method too, and
    a groundwater-only deployment runs without ``surface``.
    ``parcels.services.field_efficiency`` reads a field's assigned row here,
    falling back to the agency-wide default when the field has none.
    """

    name = models.CharField(max_length=100, unique=True)
    assigned_efficiency = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="The share of applied water the table assigns this method, "
        "as a fraction (0.600 is 60%).",
    )
    range_low = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="Low end of the table's published range, as a fraction.",
    )
    range_high = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="High end of the table's published range, as a fraction.",
    )
    source = models.CharField(
        max_length=300,
        help_text="The published table this row is copied from.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def percent(self):
        """The assigned efficiency as a whole percent: 0.600 -> 60."""
        return int((self.assigned_efficiency * 100).to_integral_value())

    def __str__(self):
        return f"{self.name}, {self.percent()}%"


@track_changes()
class ParcelIrrigationMethod(models.Model):
    """How one use area is irrigated; no row means not set.

    A row of its own rather than a ``Parcel.irrigation_method`` column; every
    reader goes through the ``irrigation`` accessor, so the row keeps this
    shape.
    """

    parcel = models.OneToOneField(
        Parcel, on_delete=models.CASCADE, related_name="irrigation"
    )
    method = models.ForeignKey(
        IrrigationMethod, on_delete=models.PROTECT, related_name="use_areas"
    )

    def __str__(self):
        return f"{self.parcel} → {self.method}"
