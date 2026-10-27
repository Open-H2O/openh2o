# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for the wells pages."""
import datetime as dt

from django import forms
from django.utils import timezone

from measurements.models import MeterReading


class MeterReadingForm(forms.Form):
    """One reading of a well's current meter.

    The reading is saved on the meter's own table with the previous reading's
    value beside it, and its volume (the change from the previous reading for
    a totalizer, the reading itself for any other meter) stored with it, so
    the month's calculation reads the volume rather than working it out again.
    """

    reading_date = forms.DateField(
        label="Date read",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
    )
    current_value = forms.DecimalField(
        label="Meter reading",
        max_digits=14,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.0001"}),
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )

    def __init__(self, *args, well=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.well = well
        link = (
            well.wellmeter_set.filter(is_current=True).select_related("meter").first()
            if well is not None
            else None
        )
        self.meter = link.meter if link else None

    def clean(self):
        cleaned = super().clean()
        if self.meter is None:
            raise forms.ValidationError("This well has no active meter to record a reading on.")
        when = cleaned.get("reading_date")
        value = cleaned.get("current_value")
        if when is None or value is None:
            return cleaned
        moment = timezone.make_aware(dt.datetime(when.year, when.month, when.day, 12, 0))
        previous = (
            MeterReading.objects.filter(meter=self.meter, reading_date__lt=moment)
            .order_by("-reading_date")
            .first()
        )
        self.moment = moment
        self.previous_value = previous.current_value if previous else None
        if self.meter.meter_type == "totalizer" and self.previous_value is not None:
            volume = value - self.previous_value
            if volume < 0:
                self.add_error(
                    "current_value",
                    f"The reading is lower than the previous one, {self.previous_value:,.2f}.",
                )
                return cleaned
            self.volume = volume
        elif self.meter.meter_type == "totalizer":
            self.volume = None
        else:
            self.volume = value
        return cleaned

    def save(self, user=None):
        data = self.cleaned_data
        return MeterReading.objects.create(
            meter=self.meter,
            reading_date=self.moment,
            previous_value=self.previous_value,
            current_value=data["current_value"],
            calculated_volume=self.volume,
            notes=data.get("notes", ""),
            read_by=user if getattr(user, "is_authenticated", False) else None,
        )
