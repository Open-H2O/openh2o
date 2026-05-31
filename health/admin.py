# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib import admin

from .models import HealthCheckResult


@admin.register(HealthCheckResult)
class HealthCheckResultAdmin(admin.ModelAdmin):
    list_display = ["category", "status", "message", "checked_at"]
    list_filter = ["category", "status"]
    date_hierarchy = "checked_at"
