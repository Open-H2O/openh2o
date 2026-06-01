# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib import admin

from .models import (
    AllocationPlan,
    CalculationPlan,
    CalculationStep,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterType,
)


@admin.register(WaterType)
class WaterTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "description"]
    search_fields = ["name", "code"]


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "is_finalized", "finalized_at"]
    list_filter = ["is_finalized"]
    search_fields = ["name"]


@admin.register(WaterAccount)
class WaterAccountAdmin(admin.ModelAdmin):
    list_display = ["account_number", "name", "status", "contact_name"]
    list_filter = ["status"]
    search_fields = ["account_number", "name", "contact_name"]


@admin.register(WaterAccountParcel)
class WaterAccountParcelAdmin(admin.ModelAdmin):
    list_display = ["water_account", "parcel", "reporting_period", "added_date", "removed_date"]
    list_filter = ["reporting_period"]
    raw_id_fields = ["water_account", "parcel"]


@admin.register(AllocationPlan)
class AllocationPlanAdmin(admin.ModelAdmin):
    list_display = ["name", "zone", "water_type", "reporting_period", "allocation_acre_feet"]
    list_filter = ["water_type", "reporting_period", "zone"]
    search_fields = ["name"]
