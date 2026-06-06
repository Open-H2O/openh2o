# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for surface water diversion record entry."""
from decimal import Decimal

from django import forms

from surface.models import DiversionRecord, PointOfDiversion


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blank means "fully consumed" — default to 0 rather than a required field,
        # so existing entry flows are unchanged when the operator leaves it empty.
        self.fields["returned_af"].required = False

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
