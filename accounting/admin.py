# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib import admin

from .models import (
    AllocationCarryover,
    AllocationPlan,
    CalculationPlan,
    CalculationRun,
    CalculationStep,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterCredit,
    WaterCreditDraw,
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


@admin.register(AllocationCarryover)
class AllocationCarryoverAdmin(admin.ModelAdmin):
    list_display = [
        "zone",
        "water_type",
        "water_year",
        "amount_af",
        "source_water_year",
        "depreciation_rate",
        "expires_period",
    ]
    list_filter = ["water_year", "water_type", "zone"]
    search_fields = ["zone__name"]


class CalculationStepInline(admin.TabularInline):
    model = CalculationStep
    extra = 0
    fields = ["order", "step_type", "enabled", "label", "config"]
    ordering = ["order"]


@admin.register(CalculationPlan)
class CalculationPlanAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "water_type", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    inlines = [CalculationStepInline]


@admin.register(CalculationStep)
class CalculationStepAdmin(admin.ModelAdmin):
    list_display = ["plan", "order", "step_type", "enabled", "label"]
    list_filter = ["enabled", "step_type", "plan"]
    ordering = ["plan", "order"]


@admin.register(WaterCredit)
class WaterCreditAdmin(admin.ModelAdmin):
    list_display = [
        "parcel",
        "origin",
        "origin_period",
        "amount_af",
        "depreciation_rate",
        "expires_period",
    ]
    list_filter = ["origin"]
    raw_id_fields = ["parcel"]


@admin.register(WaterCreditDraw)
class WaterCreditDrawAdmin(admin.ModelAdmin):
    list_display = ["credit", "draw_period", "amount_af"]
    raw_id_fields = ["credit"]


@admin.register(CalculationRun)
class CalculationRunAdmin(admin.ModelAdmin):
    """Read-only audit record — the run reconstructs a bill, so it must not be
    hand-editable (that would let someone rewrite the math after the fact)."""

    list_display = [
        "parcel",
        "period",
        "gross_et_af",
        "final_af",
        "banked_af",
        "drawn_af",
        "created_at",
    ]
    list_filter = ["period"]
    raw_id_fields = ["parcel"]
    readonly_fields = [
        "parcel",
        "period",
        "gross_et_af",
        "effective_precip_af",
        "surface_water_af",
        "banked_af",
        "drawn_af",
        "final_af",
        "breakdown",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
