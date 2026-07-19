# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the drinking water app models.

This is the CRUD backstop until 78-02 builds real pages.
"""
from django.contrib import admin

from .models import (
    Analyte,
    RegulatoryLimit,
    SampleEvent,
    SampleResult,
    SamplingPoint,
    SystemFacility,
    WaterSystem,
)


@admin.register(WaterSystem)
class WaterSystemAdmin(admin.ModelAdmin):
    list_display = [
        "pwsid", "name", "activity_status", "pws_type",
        "state_classification", "primary_source_code", "regulating_agency",
    ]
    list_filter = [
        "activity_status", "pws_type", "state_classification",
        "primary_source_code", "owner_type", "is_wholesaler",
        "is_school_or_daycare",
    ]
    search_fields = ["pwsid", "name", "seller_pwsid"]
    fieldsets = (
        ("Identification", {
            "fields": ("pwsid", "name", "activity_status", "regulating_agency"),
        }),
        ("Classification", {
            "fields": ("pws_type", "state_classification", "owner_type",
                       "primary_source_code", "is_wholesaler",
                       "is_school_or_daycare", "seller_pwsid"),
        }),
        ("Population Served", {
            "fields": ("population_residential", "population_non_transient",
                       "population_transient"),
        }),
        ("Service Connections", {
            "fields": ("connections_agricultural", "connections_combined",
                       "connections_commercial", "connections_industrial",
                       "connections_residential"),
        }),
    )


@admin.register(SystemFacility)
class SystemFacilityAdmin(admin.ModelAdmin):
    list_display = [
        "facility_id", "name", "system", "facility_type",
        "activity_status", "is_source", "water_type", "availability", "well",
    ]
    list_filter = ["facility_type", "activity_status", "is_source",
                   "water_type", "availability"]
    search_fields = ["facility_id", "name", "system__pwsid", "system__name"]
    raw_id_fields = ["system", "well"]


@admin.register(SamplingPoint)
class SamplingPointAdmin(admin.ModelAdmin):
    list_display = ["ps_code", "name", "facility", "point_type"]
    list_filter = ["point_type"]
    search_fields = ["ps_code", "name", "facility__facility_id",
                     "facility__system__pwsid"]
    raw_id_fields = ["facility"]


@admin.register(Analyte)
class AnalyteAdmin(admin.ModelAdmin):
    list_display = ["name", "ddw_code", "storet_code", "observed_property"]
    search_fields = ["name", "ddw_code", "storet_code"]
    raw_id_fields = ["observed_property"]


@admin.register(RegulatoryLimit)
class RegulatoryLimitAdmin(admin.ModelAdmin):
    list_display = [
        "analyte", "limit_type", "value", "unit", "jurisdiction",
        "effective_start", "effective_end",
    ]
    list_filter = ["limit_type", "jurisdiction", "unit"]
    search_fields = ["analyte__name", "jurisdiction"]
    raw_id_fields = ["analyte"]


@admin.register(SampleEvent)
class SampleEventAdmin(admin.ModelAdmin):
    list_display = ["sampling_point", "sample_date", "sample_time",
                    "sample_type", "collector"]
    list_filter = ["sample_type", "sample_date"]
    search_fields = ["sampling_point__ps_code", "collector"]
    raw_id_fields = ["sampling_point"]
    date_hierarchy = "sample_date"


@admin.register(SampleResult)
class SampleResultAdmin(admin.ModelAdmin):
    list_display = [
        "event", "analyte", "result_kind", "result_value", "presence",
        "unit", "less_than_rl", "analysis_date", "lab_name",
    ]
    list_filter = ["result_kind", "less_than_rl", "unit", "lab_name"]
    search_fields = ["analyte__name", "lab_name", "lab_cert_no", "method",
                     "event__sampling_point__ps_code"]
    raw_id_fields = ["event", "analyte"]
