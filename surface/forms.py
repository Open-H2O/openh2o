# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for surface water diversion record entry."""
from decimal import Decimal

from django import forms

from surface.models import DiversionRecord, PointOfDiversion, WaterRight

#: Choices for the four season month selects: (value, label) with a blank
#: leading option so a right with no recorded season renders as "not set"
#: rather than defaulting to January.
MONTH_CHOICES = [("", "-- Month --")] + [
    (i, name) for i, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
]


class DiversionRecordForm(forms.ModelForm):
    """Form for creating a diversion record from the POD detail page.

    point_of_diversion is set in the view (from URL pk).
    reporting_period is auto-assigned based on the record's month.
    """

    class Meta:
        model = DiversionRecord
        fields = [
            "month", "volume_acre_feet", "returned_af",
            "max_flow_rate_cfs", "diversion_type", "notes",
        ]
        widgets = {
            "month": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "volume_acre_feet": forms.NumberInput(attrs={
                "class": "form-input",
                "step": "0.0001",
                "placeholder": "e.g. 12.5",
            }),
            "returned_af": forms.NumberInput(attrs={
                "class": "form-input",
                "step": "0.0001",
                "placeholder": "0 (default)",
            }),
            "max_flow_rate_cfs": forms.NumberInput(attrs={
                "class": "form-input",
                "step": "0.0001",
                "placeholder": "Optional",
            }),
            "diversion_type": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={
                "class": "form-textarea",
                "rows": 2,
                "placeholder": "Optional notes...",
            }),
        }
        # The widget is `type="date"` (a full calendar-day picker) but the
        # model only ever keeps the month -- clean_month below normalizes
        # whatever day is picked to the 1st. The walker read the un-labelled
        # date input as "Month, no year" (146-02 context); this label says
        # what the field actually wants.
        labels = {"month": "Month (pick any day in it)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blank means "fully consumed" — default to 0 rather than a required field,
        # so existing entry flows are unchanged when the operator leaves it empty.
        self.fields["returned_af"].required = False

    def clean_month(self):
        """Normalize any picked day to the 1st -- a season is a month, not a date.

        The unique constraint on (point_of_diversion, month, diversion_type)
        is only meaningful per calendar month if every record for a given
        month stores the SAME day; without this, "March 1" and "March 15"
        collide with nothing and duplicate March records could both save.
        """
        month = self.cleaned_data.get("month")
        if month is not None:
            month = month.replace(day=1)
        return month

    def clean_returned_af(self):
        """Surface the model guard as a readable field error, not a 500.

        ``DiversionRecord.clean()`` (67-01) is the backstop, but ``Model.save()``
        never calls it; the form is the operator's entry boundary, so re-check
        here that the returned volume can't exceed the diverted volume — a typo
        that flips consumed negative gets rejected with a friendly message.
        """
        returned = self.cleaned_data.get("returned_af")
        if returned is None:
            return Decimal("0")
        volume = self.cleaned_data.get("volume_acre_feet")
        if volume is not None and returned > abs(volume):
            raise forms.ValidationError(
                "Return flow cannot exceed the diverted volume."
            )
        return returned


class PointOfDiversionForm(forms.ModelForm):
    """Form for editing POD metadata.

    water_right and location are excluded (set via separate UI).
    """

    class Meta:
        model = PointOfDiversion
        fields = ["name", "stream_name", "max_rate_cfs", "status", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "stream_name": forms.TextInput(attrs={"class": "form-input"}),
            "max_rate_cfs": forms.NumberInput(attrs={
                "class": "form-input",
                "step": "0.0001",
            }),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
        }


class WaterRightForm(forms.ModelForm):
    """Create/edit a water right (146-02 Task 1, door D1).

    The four season fields per season type (start month, start day, end
    month, end day) are laid out in the template as "from <month> <day> to
    <month> <day>"; ``clean()`` here enforces the one cross-field rule the
    plan calls for: a day outside 1-31, and a start recorded with no end (or
    an end with no start) for either season.
    """

    direct_season_start_month = forms.TypedChoiceField(
        choices=MONTH_CHOICES, coerce=int, required=False, empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    direct_season_end_month = forms.TypedChoiceField(
        choices=MONTH_CHOICES, coerce=int, required=False, empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    storage_season_start_month = forms.TypedChoiceField(
        choices=MONTH_CHOICES, coerce=int, required=False, empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    storage_season_end_month = forms.TypedChoiceField(
        choices=MONTH_CHOICES, coerce=int, required=False, empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = WaterRight
        fields = [
            "right_id", "right_type", "holder_name", "priority_date",
            "face_value_acre_feet", "status", "state_status", "source_name",
            "watershed", "permit_number", "license_number", "purpose_of_use",
            "net_acreage", "max_rate_cfs",
            "direct_season_start_month", "direct_season_start_day",
            "direct_season_end_month", "direct_season_end_day",
            "storage_season_start_month", "storage_season_start_day",
            "storage_season_end_month", "storage_season_end_day",
            "calwatrs_pin", "notes",
        ]
        widgets = {
            "right_id": forms.TextInput(attrs={"class": "form-input"}),
            "right_type": forms.Select(attrs={"class": "form-select"}),
            "holder_name": forms.TextInput(attrs={"class": "form-input"}),
            "priority_date": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "face_value_acre_feet": forms.NumberInput(attrs={"class": "form-input", "step": "0.0001"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "state_status": forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. Licensed"}),
            "source_name": forms.TextInput(attrs={"class": "form-input"}),
            "watershed": forms.TextInput(attrs={"class": "form-input"}),
            "permit_number": forms.TextInput(attrs={"class": "form-input"}),
            "license_number": forms.TextInput(attrs={"class": "form-input"}),
            "purpose_of_use": forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. Irrigation"}),
            "net_acreage": forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
            "max_rate_cfs": forms.NumberInput(attrs={"class": "form-input", "step": "0.0001"}),
            "direct_season_start_day": forms.NumberInput(attrs={"class": "form-input", "min": 1, "max": 31, "placeholder": "Day"}),
            "direct_season_end_day": forms.NumberInput(attrs={"class": "form-input", "min": 1, "max": 31, "placeholder": "Day"}),
            "storage_season_start_day": forms.NumberInput(attrs={"class": "form-input", "min": 1, "max": 31, "placeholder": "Day"}),
            "storage_season_end_day": forms.NumberInput(attrs={"class": "form-input", "min": 1, "max": 31, "placeholder": "Day"}),
            "calwatrs_pin": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
        }
        # Django's auto-derived label only capitalises the first word ("Right
        # id"), and copy rule 2 requires "ID" capitalised wherever it appears
        # in prose (tests/test_platform_readability.py::
        # test_identifier_is_capitalised_on_every_rendered_page).
        labels = {"right_id": "Right ID"}

    def _clean_season(self, cleaned, prefix, label):
        start_month = cleaned.get(f"{prefix}_start_month")
        start_day = cleaned.get(f"{prefix}_start_day")
        end_month = cleaned.get(f"{prefix}_end_month")
        end_day = cleaned.get(f"{prefix}_end_day")

        for field, value in (
            (f"{prefix}_start_day", start_day),
            (f"{prefix}_end_day", end_day),
        ):
            if value is not None and not (1 <= value <= 31):
                self.add_error(field, "Day must be between 1 and 31.")

        start_given = start_month is not None or start_day is not None
        end_given = end_month is not None or end_day is not None
        if start_given and not end_given:
            self.add_error(
                f"{prefix}_end_month",
                f"The {label} season has a start but no end.",
            )
        elif end_given and not start_given:
            self.add_error(
                f"{prefix}_start_month",
                f"The {label} season has an end but no start.",
            )

    def clean(self):
        cleaned = super().clean()
        self._clean_season(cleaned, "direct_season", "direct diversion")
        self._clean_season(cleaned, "storage_season", "storage")
        return cleaned
