from django.contrib import admin

from .models import Boundary, ParcelZone, Zone, ZoneGroup


@admin.register(Boundary)
class BoundaryAdmin(admin.ModelAdmin):
    list_display = ["name", "area_sq_miles", "created_at"]
    search_fields = ["name"]


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ["name", "boundary", "zone_type", "created_at"]
    list_filter = ["zone_type", "boundary"]
    search_fields = ["name"]


@admin.register(ZoneGroup)
class ZoneGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]
    filter_horizontal = ["zones"]


@admin.register(ParcelZone)
class ParcelZoneAdmin(admin.ModelAdmin):
    list_display = ["parcel", "zone"]
    list_filter = ["zone"]
    raw_id_fields = ["parcel"]
