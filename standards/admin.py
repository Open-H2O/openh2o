# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib import admin

from .models import Datastream, ObservedProperty, SourceParameter


@admin.register(ObservedProperty)
class ObservedPropertyAdmin(admin.ModelAdmin):
    list_display = [
        "key", "name", "usgs_pcode", "ucum_unit",
        "wqx_characteristic_name", "is_publishable",
    ]
    list_filter = ["usgs_pcode"]
    search_fields = ["key", "name", "usgs_pcode", "wqx_characteristic_name"]

    @admin.display(boolean=True, description="Publishable")
    def is_publishable(self, obj):
        return obj.is_publishable()


@admin.register(SourceParameter)
class SourceParameterAdmin(admin.ModelAdmin):
    list_display = [
        "source_code", "parameter_code", "observed_property",
        "native_name", "native_unit",
    ]
    list_filter = ["source_code"]
    search_fields = ["source_code", "parameter_code", "native_name"]
    autocomplete_fields = ["observed_property"]


@admin.register(Datastream)
class DatastreamAdmin(admin.ModelAdmin):
    list_display = [
        "name", "observed_property", "uom", "sensor", "well", "monitored_station",
    ]
    list_filter = ["observed_property"]
    search_fields = ["name", "description"]
    autocomplete_fields = ["observed_property", "sensor", "well", "monitored_station"]

    @admin.display(description="Unit (UCUM)")
    def uom(self, obj):
        return obj.uom
