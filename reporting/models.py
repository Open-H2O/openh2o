from django.conf import settings
from django.contrib.gis.db import models


class ReportTemplate(models.Model):
    REPORT_TYPE_CHOICES = [
        ("gears_by_well", "GEARS by Well"),
        ("gears_by_et", "GEARS by ET"),
        ("calwatrs_a1", "CalWATRS A1"),
        ("calwatrs_a2", "CalWATRS A2"),
        ("email_json", "Email JSON"),
    ]

    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=50, unique=True, choices=REPORT_TYPE_CHOICES)
    description = models.TextField(blank=True)
    template_version = models.CharField(max_length=20, default="1.0")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ReportSubmission(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed"),
        ("submitted", "Submitted"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    ]

    report_template = models.ForeignKey(ReportTemplate, on_delete=models.PROTECT)
    reporting_period = models.ForeignKey(
        "accounting.ReportingPeriod", on_delete=models.PROTECT
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    generated_file = models.CharField(max_length=500, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    reviewer_notes = models.TextField(blank=True)
    validation_warnings = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.report_template.report_type} - {self.reporting_period}"


class ReportingCrosswalk(models.Model):
    report_template = models.ForeignKey(ReportTemplate, on_delete=models.CASCADE)
    internal_field = models.CharField(max_length=100)
    external_field = models.CharField(max_length=100)
    transform = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("report_template", "internal_field")]

    def __str__(self):
        return f"{self.report_template}: {self.internal_field} → {self.external_field}"
