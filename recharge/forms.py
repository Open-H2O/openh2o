# SPDX-License-Identifier: AGPL-3.0-or-later
from django import forms

from recharge.models import RechargeEvent


class RechargeEventForm(forms.ModelForm):
    class Meta:
        model = RechargeEvent
        fields = [
            "start_date",
            "end_date",
            "volume_acre_feet",
            "water_type",
            "source_description",
            "notes",
        ]
        widgets = {
            "start_date": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}
            ),
            "volume_acre_feet": forms.NumberInput(
                attrs={"step": "0.0001", "class": "form-input"}
            ),
            "water_type": forms.Select(attrs={"class": "form-select"}),
            "source_description": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-textarea"}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        volume = cleaned.get("volume_acre_feet")
        if start and end and end < start:
            self.add_error("end_date", "The end date can't be before the start date.")
        # A zero/negative volume would fan negative supply rows across every parcel
        # in the zone via create_recharge_ledger_entries — silent balance corruption.
        if volume is not None and volume <= 0:
            self.add_error("volume_acre_feet", "Volume must be greater than zero.")
        return cleaned
