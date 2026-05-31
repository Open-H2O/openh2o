# SPDX-License-Identifier: AGPL-3.0-or-later
from django import forms

from geography.models import Zone


class ZoneForm(forms.ModelForm):
    """Form for creating a zone.

    geometry is excluded (set via map JS hidden input).
    boundary is excluded (auto-assigned to the site's primary boundary).
    """

    class Meta:
        model = Zone
        fields = ["name", "zone_type", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. North Basin Zone A"}),
            "zone_type": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={
                "class": "form-textarea",
                "rows": 3,
                "placeholder": "Optional description of this zone...",
            }),
        }
