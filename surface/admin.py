# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the surface water-right models."""
from django.contrib import admin

from .models import (
    CurtailmentOrder,
    DiversionRecord,
    IrrigationMethod,
    MeasuringDevice,
    ParcelIrrigationMethod,
    PointOfDiversion,
    PointOfDiversionDevice,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightType,
)


@admin.register(WaterRightType)
class WaterRightTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "description"]


@admin.register(WaterRight)
class WaterRightAdmin(admin.ModelAdmin):
    list_display = ["right_id", "right_type", "holder_name", "priority_date", "face_value_acre_feet", "status"]
    list_filter = ["right_type", "status"]
    search_fields = ["right_id", "holder_name"]


@admin.register(PointOfDiversion)
class PointOfDiversionAdmin(admin.ModelAdmin):
    list_display = ["name", "water_right", "stream_name", "rediverted_from", "max_rate_cfs", "status"]
    list_filter = ["status"]
    search_fields = ["name", "stream_name"]
    raw_id_fields = ["water_right", "rediverted_from"]


@admin.register(PointOfDiversionParcel)
class PointOfDiversionParcelAdmin(admin.ModelAdmin):
    list_display = ["point_of_diversion", "parcel", "fraction"]
    raw_id_fields = ["point_of_diversion", "parcel"]


@admin.register(DiversionRecord)
class DiversionRecordAdmin(admin.ModelAdmin):
    list_display = ["point_of_diversion", "month", "volume_acre_feet", "diversion_type"]
    list_filter = ["diversion_type", "reporting_period"]
    raw_id_fields = ["point_of_diversion"]
    date_hierarchy = "month"


@admin.register(MeasuringDevice)
class MeasuringDeviceAdmin(admin.ModelAdmin):
    list_display = ["__str__", "device_type", "accuracy_percent", "installed_on", "status"]
    list_filter = ["device_type", "status"]
    search_fields = ["nickname", "make", "model_number", "state_device_id"]
    filter_horizontal = ["water_rights"]


@admin.register(PointOfDiversionDevice)
class PointOfDiversionDeviceAdmin(admin.ModelAdmin):
    list_display = ["point_of_diversion", "device", "is_current", "installed_on", "removed_on"]
    list_filter = ["is_current"]
    raw_id_fields = ["point_of_diversion", "device"]


@admin.register(IrrigationMethod)
class IrrigationMethodAdmin(admin.ModelAdmin):
    list_display = ["name", "assigned_efficiency", "range_low", "range_high", "sort_order"]
    search_fields = ["name"]


@admin.register(ParcelIrrigationMethod)
class ParcelIrrigationMethodAdmin(admin.ModelAdmin):
    list_display = ["parcel", "method"]
    raw_id_fields = ["parcel"]


@admin.register(CurtailmentOrder)
class CurtailmentOrderAdmin(admin.ModelAdmin):
    list_display = ["order_id", "title", "effective_date", "end_date", "status"]
    list_filter = ["status"]
    search_fields = ["order_id", "title", "watershed"]
