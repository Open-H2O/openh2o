# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the wells app models."""
from django.contrib import admin

from .models import MonitoringWell, Well, WellIrrigatedParcel, WellMeter, WellType


@admin.register(WellType)
class WellTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


@admin.register(Well)
class WellAdmin(admin.ModelAdmin):
    list_display = [
        "name", "well_registration_id", "well_type", "status",
        "depth_ft", "capacity_gpm", "measurement_method", "wcr_number",
    ]
    list_filter = ["well_type", "status", "pump_type", "measurement_method"]
    search_fields = ["name", "well_registration_id"]
    fieldsets = (
        ("Identification", {
            "fields": ("name", "well_registration_id", "wcr_number",
                       "state_well_number", "well_type", "owner_name"),
        }),
        ("State Reporting", {
            "fields": ("status", "capacity_gpm", "year_pumping_began",
                       "measurement_method"),
        }),
        ("Construction", {
            "fields": ("depth_ft", "casing_diameter_in", "casing_material",
                       "screen_top_ft", "screen_bottom_ft", "vertical_datum",
                       "tested_yield_gpm", "pump_type"),
        }),
        ("Standards / Cross-walk", {
            "fields": ("usgs_site_id", "wqx_monitoring_location_id"),
        }),
        ("Location", {"fields": ("location",)}),
        ("Notes", {"fields": ("notes",)}),
    )


@admin.register(WellMeter)
class WellMeterAdmin(admin.ModelAdmin):
    list_display = ["well", "meter", "is_current", "installed_date", "calibration_date"]
    list_filter = ["is_current"]
    raw_id_fields = ["well", "meter"]


@admin.register(WellIrrigatedParcel)
class WellIrrigatedParcelAdmin(admin.ModelAdmin):
    list_display = ["well", "parcel", "fraction"]
    raw_id_fields = ["well", "parcel"]


@admin.register(MonitoringWell)
class MonitoringWellAdmin(admin.ModelAdmin):
    list_display = ["well", "monitoring_agency", "measurement_frequency", "reference_elevation_ft"]
    search_fields = ["well__name", "monitoring_agency"]
