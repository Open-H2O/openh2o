# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the core user and site models."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import SiteConfig, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "first_name", "last_name", "agency_admin", "read_only", "title", "is_staff"]
    list_filter = ["agency_admin", "read_only", "is_staff", "is_active"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Role and contact", {"fields": ("agency_admin", "read_only", "phone", "title")}),
    )


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ["agency_name", "timezone", "native_srid", "allow_google_oauth"]

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()
