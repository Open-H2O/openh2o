# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings
from django.contrib.gis.db import models


class WaterType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class ReportingPeriod(models.Model):
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    is_finalized = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_date__lt=models.F("end_date")),
                name="reporting_period_start_before_end",
            )
        ]

    def __str__(self):
        return self.name


class WaterAccount(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("suspended", "Suspended"),
    ]

    name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    verification_key = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.account_number} - {self.name}"


class WaterAccountParcel(models.Model):
    water_account = models.ForeignKey(WaterAccount, on_delete=models.CASCADE)
    parcel = models.ForeignKey("parcels.Parcel", on_delete=models.CASCADE)
    reporting_period = models.ForeignKey(
        ReportingPeriod, on_delete=models.SET_NULL, null=True, blank=True
    )
    added_date = models.DateField(auto_now_add=True)
    removed_date = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("water_account", "parcel", "reporting_period")]

    def __str__(self):
        return f"{self.water_account} - {self.parcel}"


class AllocationPlan(models.Model):
    name = models.CharField(max_length=200)
    zone = models.ForeignKey("geography.Zone", on_delete=models.CASCADE)
    water_type = models.ForeignKey(WaterType, on_delete=models.CASCADE)
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE)
    allocation_acre_feet = models.DecimalField(
        max_digits=12, decimal_places=4, verbose_name="Water budget (AF)"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("zone", "water_type", "reporting_period")]
        verbose_name = "Water Budget"
        verbose_name_plural = "Water Budgets"

    def __str__(self):
        return self.name


class CalculationPlan(models.Model):
    """A named, config-as-data recipe for deriving billable groundwater.

    Mirrors the standards.ObservedProperty controlled-vocabulary pattern: the
    methodology lives in rows an agency can tune from a screen (Phase 38-06)
    rather than in code. Single-tenant, so exactly one plan is active at a time.
    The ordered, enabled CalculationStep rows are walked by
    accounting.calculation.evaluate_chain.
    """

    name = models.CharField(max_length=200)
    water_type = models.ForeignKey(
        WaterType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Reserved for future per-water-type scoping; unused in 38-02.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @classmethod
    def active(cls):
        """Return the active plan (single-tenant: the first is_active), or None."""
        return cls.objects.filter(is_active=True).order_by("id").first()


class CalculationStep(models.Model):
    """One ordered operation in a CalculationPlan's chain.

    step_type names a primitive in accounting.steps.STEP_REGISTRY. config holds
    that primitive's per-step knobs (model/variable, floor, bank, ...). Disabled
    steps are skipped by the evaluator, which is how 38-02 ships the contested
    effective-precipitation math seeded-but-dark until 38-03 turns it on.
    """

    STEP_TYPE_CHOICES = [
        ("et_gross", "Gross ET"),
        ("subtract_effective_precip", "Subtract effective precipitation"),
        ("subtract_surface_water", "Subtract surface water delivered"),
        ("facility_only_zero", "Zero out facility-only parcels"),
        ("clamp_floor", "Clamp at floor"),
    ]

    plan = models.ForeignKey(
        CalculationPlan, on_delete=models.CASCADE, related_name="steps"
    )
    order = models.PositiveIntegerField()
    step_type = models.CharField(max_length=40, choices=STEP_TYPE_CHOICES)
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    label = models.CharField(
        max_length=200, help_text="Human-readable name for the audit trail."
    )

    class Meta:
        ordering = ["plan", "order"]
        unique_together = [("plan", "order")]

    def __str__(self):
        return f"{self.order}. {self.label}"
