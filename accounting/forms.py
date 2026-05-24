from django import forms

from accounting.models import AllocationPlan, ReportingPeriod, WaterAccount, WaterType
from parcels.models import ParcelLedger


FORM_INPUT_STYLE = (
    "background: var(--color-elevated); border: 1px solid var(--color-border);"
    " border-radius: var(--radius-md); padding: var(--space-sm) var(--space-md);"
    " color: var(--color-text-primary); width: 100%; font-family: var(--font-display);"
)

FORM_SELECT_STYLE = (
    "background: var(--color-elevated); border: 1px solid var(--color-border);"
    " border-radius: var(--radius-md); padding: var(--space-sm) var(--space-md);"
    " color: var(--color-text-primary); width: 100%; font-family: var(--font-display);"
    " cursor: pointer;"
)


class ReportingPeriodForm(forms.ModelForm):
    class Meta:
        model = ReportingPeriod
        fields = ["name", "start_date", "end_date", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"style": FORM_INPUT_STYLE}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "style": FORM_INPUT_STYLE}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "style": FORM_INPUT_STYLE}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "style": FORM_INPUT_STYLE + " resize: vertical;"}
            ),
        }


class AllocationPlanForm(forms.ModelForm):
    class Meta:
        model = AllocationPlan
        fields = [
            "name",
            "zone",
            "water_type",
            "reporting_period",
            "allocation_acre_feet",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"style": FORM_INPUT_STYLE}),
            "zone": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "water_type": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "reporting_period": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "allocation_acre_feet": forms.NumberInput(
                attrs={"step": "0.0001", "style": FORM_INPUT_STYLE}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "style": FORM_INPUT_STYLE + " resize: vertical;"}
            ),
        }


class WaterAccountForm(forms.ModelForm):
    class Meta:
        model = WaterAccount
        fields = [
            "account_number",
            "name",
            "status",
            "contact_name",
            "contact_email",
            "notes",
        ]
        widgets = {
            "account_number": forms.TextInput(attrs={"style": FORM_INPUT_STYLE}),
            "name": forms.TextInput(attrs={"style": FORM_INPUT_STYLE}),
            "status": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "contact_name": forms.TextInput(attrs={"style": FORM_INPUT_STYLE}),
            "contact_email": forms.EmailInput(attrs={"style": FORM_INPUT_STYLE}),
            "notes": forms.Textarea(
                attrs={"rows": 3, "style": FORM_INPUT_STYLE + " resize: vertical;"}
            ),
        }


class CsvUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "style": FORM_INPUT_STYLE})
    )
    reporting_period = forms.ModelChoiceField(
        queryset=ReportingPeriod.objects.order_by("-start_date"),
        required=False,
        empty_label="No period (unassigned)",
        widget=forms.Select(attrs={"style": FORM_SELECT_STYLE}),
    )
    dry_run = forms.BooleanField(required=False, initial=False)


class ParcelLedgerForm(forms.ModelForm):
    class Meta:
        model = ParcelLedger
        fields = [
            "parcel",
            "transaction_date",
            "effective_date",
            "amount_acre_feet",
            "water_type",
            "source_type",
            "description",
            "reporting_period",
        ]
        widgets = {
            "parcel": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "transaction_date": forms.DateInput(
                attrs={"type": "date", "style": FORM_INPUT_STYLE}
            ),
            "effective_date": forms.DateInput(
                attrs={"type": "date", "style": FORM_INPUT_STYLE}
            ),
            "amount_acre_feet": forms.NumberInput(
                attrs={"step": "0.0001", "style": FORM_INPUT_STYLE}
            ),
            "water_type": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "source_type": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
            "description": forms.Textarea(
                attrs={"rows": 3, "style": FORM_INPUT_STYLE + " resize: vertical;"}
            ),
            "reporting_period": forms.Select(attrs={"style": FORM_SELECT_STYLE}),
        }
