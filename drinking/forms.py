# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Forms for the drinking-water domain.

Created in 146-04 Task 2 for the production add-month door (D7); Tasks 3 and
4 of the same plan extend this file with the facility form and the sampling
schedule form rather than starting their own.
"""
from django import forms

from drinking.models import PRODUCTION_PROVENANCE_TYPED, SystemProduction

MONTH_CHOICES = [("", "-- Year total, not one month --")] + [
    (i, name) for i, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
]


class SystemProductionForm(forms.ModelForm):
    """One month's production or delivery, by source, entered by hand.

    ``system`` is set in the view (a deployment's own WaterSystem, the same
    single-system assumption ``drinking/production_import.py`` makes).
    ``facility`` is offered but not required -- neither the eAR export nor
    the operator's own log names one, so most rows this form itself creates
    will leave it blank too.
    """

    month = forms.TypedChoiceField(
        choices=MONTH_CHOICES, coerce=int, required=False, empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = SystemProduction
        fields = [
            "year", "month", "type_code", "facility",
            "volume_as_reported", "unit_as_reported", "notes",
        ]
        widgets = {
            "year": forms.NumberInput(attrs={"class": "form-input", "min": 1990, "max": 2100}),
            "type_code": forms.Select(attrs={"class": "form-select"}),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "volume_as_reported": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.01", "placeholder": "e.g. 4007800",
            }),
            "unit_as_reported": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
        }
        labels = {
            "volume_as_reported": "Volume, as reported",
            "unit_as_reported": "Unit",
        }

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._system = system
        self.fields["facility"].required = False
        if system is not None:
            self.fields["facility"].queryset = system.facilities.order_by("facility_id")
        else:
            self.fields["facility"].queryset = self.fields["facility"].queryset.none()
        self.fields["unit_as_reported"].initial = "G"

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self._system is not None:
            instance.system = self._system
        instance.provenance = PRODUCTION_PROVENANCE_TYPED
        if commit:
            instance.save()
        return instance
