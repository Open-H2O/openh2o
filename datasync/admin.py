# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the datasync models."""
from django.contrib import admin

from .models import DataRecordStaging, DataSource, DataSyncLog, MonitoredStation


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "auth_type", "sync_interval_hours", "is_active", "last_sync_at"]
    list_filter = ["is_active", "auth_type"]
    search_fields = ["name", "code"]


@admin.register(MonitoredStation)
class MonitoredStationAdmin(admin.ModelAdmin):
    list_display = ["station_name", "data_source", "external_station_id", "is_active", "last_data_at"]
    list_filter = ["data_source", "is_active"]
    search_fields = ["station_name", "external_station_id"]


@admin.register(DataSyncLog)
class DataSyncLogAdmin(admin.ModelAdmin):
    list_display = ["data_source", "started_at", "status", "records_fetched", "records_staged", "records_published", "duration_seconds"]
    list_filter = ["data_source", "status"]
    date_hierarchy = "started_at"


@admin.register(DataRecordStaging)
class DataRecordStagingAdmin(admin.ModelAdmin):
    list_display = ["data_source", "station", "parameter_code", "observation_date", "value", "status"]
    list_filter = ["data_source", "status", "parameter_code"]
    raw_id_fields = ["station"]
    date_hierarchy = "observation_date"
