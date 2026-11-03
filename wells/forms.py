# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for the wells pages."""
import datetime as dt

from django import forms
from django.utils import timezone

from accounting.locks import PeriodFinalized, refuse_if_finalized
from measurements.models import (
    NO_MEASUREMENT_REASONS,
    WATER_LEVEL_METHODS,
    MeterReading,
    WaterMeasurement,
)
from standards.models import ObservedProperty

#: The observed property every hand-entered depth to water carries (the seed
#: and the imported levels use it too).
DEPTH_PROPERTY_KEY = "groundwater_level_depth"


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
    quality = forms.ChoiceField(
        label="Meter or estimate",
        required=False,
        initial="provisional",
        choices=[("provisional", "Read from the meter"), ("estimated", "Estimated")],
        widget=forms.RadioSelect,
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
    )

    def __init__(self, *args, well=None, meter=None, exclude_pk=None, **kwargs):
        """``meter`` and ``exclude_pk`` are for a correction: it keeps the record's own meter,
        and the reading it replaces is not the previous one."""
        super().__init__(*args, **kwargs)
        self.well = well
        self.exclude_pk = exclude_pk
        if meter is not None:
            self.meter = meter
            return
        link = (
            well.wellmeter_set.filter(is_current=True).select_related("meter").first()
            if well is not None
            else None
        )
        self.meter = link.meter if link else None

    def clean_quality(self):
        """A form that does not send the choice reads from the meter."""
        return self.cleaned_data.get("quality") or "provisional"

    def clean(self):
        cleaned = super().clean()
        if self.meter is None:
            raise forms.ValidationError("This well has no active meter to record a reading on.")
        when = cleaned.get("reading_date")
        value = cleaned.get("current_value")
        if when is None or value is None:
            return cleaned
        # A reading dated inside a finalized water year is refused beside the
        # date; a correction by an administrator is the way into one.
        try:
            refuse_if_finalized(when)
        except PeriodFinalized as exc:
            self.add_error("reading_date", str(exc))
            return cleaned
        moment = timezone.make_aware(dt.datetime(when.year, when.month, when.day, 12, 0))
        earlier = MeterReading.objects.current().filter(meter=self.meter, reading_date__lt=moment)
        if self.exclude_pk:
            earlier = earlier.exclude(pk=self.exclude_pk)
        previous = earlier.order_by("-reading_date").first()
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
            quality=data.get("quality") or "provisional",
            notes=data.get("notes", ""),
            read_by=user if getattr(user, "is_authenticated", False) else None,
        )


def level_name(well):
    """The name a well's depth-to-water record carries: its registration ID, else its name."""
    return f"{well.well_registration_id or well.name} depth to water"


def level_moment(day):
    """Noon, in the site's time zone, on ``day``: when a level has a date and no time."""
    return timezone.make_aware(dt.datetime(day.year, day.month, day.day, 12, 0))


class WaterLevelForm(forms.Form):
    """One depth to water read by hand, or a visit where none could be read.

    A person gives a depth or ticks No measurement and picks the reason, never
    both and never neither. The script on the page hides the unused field; with
    scripts off both show, and this form refuses the pair.
    """

    level_date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
    )
    method = forms.ChoiceField(
        label="Method",
        required=False,
        choices=[("", "Not stated")] + WATER_LEVEL_METHODS,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    depth_ft = forms.DecimalField(
        label="Depth to water (ft below land surface)",
        required=False,
        max_digits=14,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    no_measurement = forms.BooleanField(label="No measurement", required=False)
    reason = forms.ChoiceField(
        label="Reason",
        required=False,
        choices=[("", "")] + NO_MEASUREMENT_REASONS,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-textarea", "rows": 2, "id": "id_level_notes"}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        if "depth_ft" in self.errors or "reason" in self.errors:
            return cleaned
        depth = cleaned.get("depth_ft")
        unmeasured = cleaned.get("no_measurement")
        if depth is None and not unmeasured:
            raise forms.ValidationError("Enter a depth to water or tick No measurement.")
        if depth is not None and unmeasured:
            raise forms.ValidationError(
                "Enter a depth to water or tick No measurement, not both."
            )
        if unmeasured and not cleaned.get("reason"):
            raise forms.ValidationError("Pick a reason, or untick No measurement.")
        # A level dated inside a finalized water year is refused beside the date.
        try:
            refuse_if_finalized(cleaned.get("level_date"))
        except PeriodFinalized as exc:
            self.add_error("level_date", str(exc))
        return cleaned

    def save(self, well, user=None):
        data = self.cleaned_data
        unmeasured = data["no_measurement"]
        return WaterMeasurement.objects.create(
            name=level_name(well),
            measurement_type="groundwater_level",
            observed_property=ObservedProperty.objects.filter(key=DEPTH_PROPERTY_KEY).first(),
            value=None if unmeasured else data["depth_ft"],
            unit="ft",
            measurement_date=level_moment(data["level_date"]),
            well=well,
            source="manual",
            recorded_by=user if getattr(user, "is_authenticated", False) else None,
            notes=data.get("notes", ""),
            method=data.get("method", ""),
            no_measurement_reason=data["reason"] if unmeasured else "",
        )
