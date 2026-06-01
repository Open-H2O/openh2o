# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

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


class WaterCredit(models.Model):
    """An immutable surplus deposit — banked water carried forward to a later month.

    When a parcel's chain nets out below the floor in a wet month (effective
    precipitation + surface water exceeded gross ET), that surplus is banked here
    as a positive ``amount_af`` rather than silently lost. The principal NEVER
    mutates after deposit; consumption is recorded separately as WaterCreditDraw
    rows so re-running a period is idempotent (delete the draws, recompute). The
    depreciated, draw-net available value is computed by accounting.banking_math /
    the runner — deliberately NOT a method here, to keep this a plain deposit row.
    """

    ORIGIN_CHOICES = [
        ("precip_surplus", "Precip surplus"),
        ("allocation_carryover", "Allocation carryover"),
    ]

    parcel = models.ForeignKey("parcels.Parcel", on_delete=models.CASCADE)
    origin_period = models.CharField(
        max_length=7, help_text="Month the surplus was banked, as YYYY-MM."
    )
    amount_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Surplus banked (acre-feet, positive). The principal — never mutated.",
    )
    origin = models.CharField(
        max_length=24, choices=ORIGIN_CHOICES, default="precip_surplus"
    )
    depreciation_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Per-period geometric decay (0 = no decay; >=1 = gone after one period).",
    )
    expires_period = models.CharField(
        max_length=7,
        null=True,
        blank=True,
        help_text="Month at/after which the credit is dead, as YYYY-MM. Null = never expires.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["origin_period"]

    def __str__(self):
        return f"{self.parcel} {self.amount_af} AF @ {self.origin_period}"


class WaterCreditDraw(models.Model):
    """A consumption record: how much of a WaterCredit a later deficit month drew.

    Tracked as rows rather than a mutable balance so re-runs stay idempotent (the
    runner deletes this period's draws then recomputes) and so 38-05's audit trail
    has the per-period drawdown to read. ``amount_af`` is the depreciated value
    actually drawn in ``draw_period`` (not the credit's full principal).
    """

    credit = models.ForeignKey(
        WaterCredit, on_delete=models.CASCADE, related_name="draws"
    )
    draw_period = models.CharField(
        max_length=7, help_text="Month the draw was applied, as YYYY-MM."
    )
    amount_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Depreciated value drawn in this period (acre-feet, positive).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["draw_period"]

    def __str__(self):
        return f"{self.amount_af} AF @ {self.draw_period} from {self.credit_id}"


class CalculationRun(models.Model):
    """The reconstructable audit record for one `calculated` ledger row (38-05).

    Persisted once per (parcel, period) by run_calculations, in the SAME
    transaction that writes the calculated ParcelLedger row, so the 1:1 invariant
    holds: every calculated row has exactly one run; a parcel skipped for no ET
    gets neither. It captures the gross-ET starting magnitude, what each
    subtraction step removed (effective precip, surface water), the WaterCredit
    banking activity folded into the bill (deposited/drawn), the final billable
    magnitude, and ``breakdown`` — the evaluate_chain per-step list stored VERBATIM
    so "How was this calculated?" can replay the gross->net waterfall without
    re-deriving anything. Decimal(4dp) throughout to match the ledger's quantize;
    a float column would reintroduce the drift the engine was built to avoid.

    No DB unique_together(parcel, period): the runner does delete-then-insert in a
    transaction (mirroring the calculated ledger row and WaterCredit, which also
    carry no unique constraint), so a hard constraint buys nothing and would only
    complicate future multi-period scoping.
    """

    parcel = models.ForeignKey("parcels.Parcel", on_delete=models.CASCADE)
    period = models.CharField(max_length=7, help_text="Month, as YYYY-MM.")
    gross_et_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Chain's starting gross ET magnitude (positive AF).",
    )
    effective_precip_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Effective precipitation subtracted (AF); null if no precip step ran.",
    )
    surface_water_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Surface water subtracted (AF); null if no surface-water step ran.",
    )
    banked_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Surplus deposited as a WaterCredit this period (AF).",
    )
    drawn_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Credit drawn down to reduce the bill this period (AF).",
    )
    final_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Final billable magnitude (POSITIVE; equals -ledger.amount_acre_feet).",
    )
    breakdown = models.JSONField(
        default=list,
        help_text="The evaluate_chain per-step list, stored verbatim.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.parcel} {self.period} → {self.final_af} AF"
