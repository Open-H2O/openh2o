# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib import admin

from .models import CurtailmentOrder, DiversionRecord, PointOfDiversion, PointOfDiversionParcel, WaterRight, WaterRightType


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
    list_display = ["name", "water_right", "stream_name", "max_rate_cfs", "status"]
    list_filter = ["status"]
    search_fields = ["name", "stream_name"]
    raw_id_fields = ["water_right"]


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


@admin.register(CurtailmentOrder)
class CurtailmentOrderAdmin(admin.ModelAdmin):
    list_display = ["order_id", "title", "effective_date", "end_date", "status"]
    list_filter = ["status"]
    search_fields = ["order_id", "title", "watershed"]
