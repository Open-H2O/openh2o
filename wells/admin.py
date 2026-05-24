from django.contrib import admin

from .models import MonitoringWell, Well, WellIrrigatedParcel, WellMeter, WellType


@admin.register(WellType)
class WellTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


@admin.register(Well)
class WellAdmin(admin.ModelAdmin):
    list_display = ["name", "well_registration_id", "well_type", "status", "depth_ft", "capacity_gpm"]
    list_filter = ["well_type", "status"]
    search_fields = ["name", "well_registration_id"]


@admin.register(WellMeter)
class WellMeterAdmin(admin.ModelAdmin):
    list_display = ["well", "meter", "is_current", "installed_date"]
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
