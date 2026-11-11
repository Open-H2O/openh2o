# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django admin registrations for the parcels app models."""
from django import forms
from django.contrib import admin

from .models import (
    CropType,
    IrrigationMethod,
    Parcel,
    ParcelIrrigationMethod,
    ParcelLedger,
    ParcelStaging,
    UsageLocation,
)


@admin.register(CropType)
class CropTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    search_fields = ["name", "code"]


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
    list_display = ["parcel_number", "owner_name", "area_acres", "area_override", "status", "updated_at"]
    list_filter = ["status", "area_override"]
    search_fields = ["parcel_number", "owner_name"]


class ParcelLedgerAdminForm(forms.ModelForm):
    """Nobody types an ET figure: an ET estimate entry comes from OpenET's recorded figure."""

    class Meta:
        model = ParcelLedger
        fields = "__all__"

    def clean_source_type(self):
        from accounting.forms import refuse_et_estimate

        source_type = self.cleaned_data.get("source_type")
        if self.instance.pk and self.instance.source_type == "et_estimate":
            return source_type
        return refuse_et_estimate(source_type)


@admin.register(ParcelLedger)
class ParcelLedgerAdmin(admin.ModelAdmin):
    form = ParcelLedgerAdminForm
    list_display = ["parcel", "amount_acre_feet", "source_type", "water_type", "effective_date", "created_at"]
    list_filter = ["source_type", "water_type", "reporting_period"]
    search_fields = ["parcel__parcel_number"]
    raw_id_fields = ["parcel"]
    date_hierarchy = "effective_date"

    def get_readonly_fields(self, request, obj=None):
        """An ET estimate entry's figure and kind are OpenET's recorded figure; nobody changes them here."""
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.source_type == "et_estimate":
            fields += ["amount_acre_feet", "source_type"]
        return fields


@admin.register(ParcelStaging)
class ParcelStagingAdmin(admin.ModelAdmin):
    list_display = ["parcel_number", "status", "created_at", "imported_at"]
    list_filter = ["status"]


@admin.register(UsageLocation)
class UsageLocationAdmin(admin.ModelAdmin):
    list_display = ["name", "parcel", "crop_type", "area_acres"]
    list_filter = ["crop_type"]
    raw_id_fields = ["parcel"]


@admin.register(IrrigationMethod)
class IrrigationMethodAdmin(admin.ModelAdmin):
    list_display = ["name", "assigned_efficiency", "range_low", "range_high", "sort_order"]
    search_fields = ["name"]


@admin.register(ParcelIrrigationMethod)
class ParcelIrrigationMethodAdmin(admin.ModelAdmin):
    list_display = ["parcel", "start_month", "method"]
    fields = ["parcel", "start_month", "method"]
    raw_id_fields = ["parcel"]
