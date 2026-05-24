from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Role, SiteConfig, User, UserRole


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "first_name", "last_name", "agency_admin", "title", "is_staff"]
    list_filter = ["agency_admin", "is_staff", "is_active"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Agency", {"fields": ("agency_admin", "phone", "title")}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ["user", "role"]
    list_filter = ["role"]
    raw_id_fields = ["user"]


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ["agency_name", "timezone", "native_srid", "allow_google_oauth"]

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()
