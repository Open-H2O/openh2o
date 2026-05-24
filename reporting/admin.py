from django.contrib import admin

from .models import ReportingCrosswalk, ReportSubmission, ReportTemplate


@admin.register(ReportTemplate)
class ReportTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "report_type", "template_version", "is_active"]
    list_filter = ["report_type", "is_active"]


@admin.register(ReportSubmission)
class ReportSubmissionAdmin(admin.ModelAdmin):
    list_display = ["report_template", "reporting_period", "status", "generated_at", "submitted_at"]
    list_filter = ["status", "report_template"]
    date_hierarchy = "created_at"


@admin.register(ReportingCrosswalk)
class ReportingCrosswalkAdmin(admin.ModelAdmin):
    list_display = ["report_template", "internal_field", "external_field", "transform"]
    list_filter = ["report_template"]
