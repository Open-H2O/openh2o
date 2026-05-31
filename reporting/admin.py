# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib import admin

from .models import ReportingCrosswalk, ReportingProfile, ReportSubmission, ReportTemplate


@admin.register(ReportingProfile)
class ReportingProfileAdmin(admin.ModelAdmin):
    list_display = ["legal_entity_name", "boundary", "gears_correspondence_id", "certifier_name"]
    search_fields = ["legal_entity_name", "gears_correspondence_id", "certifier_name"]


@admin.register(ReportTemplate)
class ReportTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "report_type", "template_version", "is_active"]
    list_filter = ["report_type", "is_active"]


@admin.register(ReportSubmission)
class ReportSubmissionAdmin(admin.ModelAdmin):
    list_display = ["report_template", "reporting_period", "status", "generated_at", "filed_at"]
    list_filter = ["status", "report_template"]
    date_hierarchy = "created_at"


@admin.register(ReportingCrosswalk)
class ReportingCrosswalkAdmin(admin.ModelAdmin):
    list_display = ["report_template", "internal_field", "external_field", "transform"]
    list_filter = ["report_template"]
