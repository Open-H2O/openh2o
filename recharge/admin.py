# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the recharge app models."""
from django.contrib import admin

from .models import RechargeEvent, RechargeMeasurement, RechargeSite


@admin.register(RechargeSite)
class RechargeSiteAdmin(admin.ModelAdmin):
    list_display = ["name", "site_type", "capacity_acre_feet", "status", "operator"]
    list_filter = ["site_type", "status"]
    search_fields = ["name", "operator"]

    def save_model(self, request, obj, form, change):
        """Save the site; its recorded recharge follows a changed zone, as on the site's page."""
        from django.db import transaction

        from accounting.services import move_site_recharge

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if change:
                move_site_recharge(obj)


@admin.register(RechargeEvent)
class RechargeEventAdmin(admin.ModelAdmin):
    list_display = ["recharge_site", "start_date", "end_date", "volume_acre_feet", "water_type"]
    list_filter = ["water_type"]
    raw_id_fields = ["recharge_site"]
    date_hierarchy = "start_date"


@admin.register(RechargeMeasurement)
class RechargeMeasurementAdmin(admin.ModelAdmin):
    list_display = ["recharge_site", "measurement_date", "measurement_type", "value", "unit"]
    list_filter = ["measurement_type"]
    raw_id_fields = ["recharge_site"]
