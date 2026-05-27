from django import forms

from surface.models import DiversionRecord, PointOfDiversion


class DiversionRecordForm(forms.ModelForm):
    """Form for creating a diversion record from the POD detail page.

    point_of_diversion is set in the view (from URL pk).
    reporting_period is auto-assigned based on the record's month.
    """

    class Meta:
        model = DiversionRecord
        fields = ["month", "volume_acre_feet", "max_flow_rate_cfs", "diversion_type", "notes"]
        widgets = {
            "month": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "volume_acre_feet": forms.NumberInput(attrs={
                "class": "form-input",
                "step": "0.0001",
                "placeholder": "e.g. 12.5",
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
