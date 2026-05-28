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
