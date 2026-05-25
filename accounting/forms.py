from django import forms

from accounting.models import AllocationPlan, ReportingPeriod, WaterAccount, WaterType
from parcels.models import ParcelLedger


class ReportingPeriodForm(forms.ModelForm):
    class Meta:
        model = ReportingPeriod
        fields = ["name", "start_date", "end_date", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "start_date": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-textarea"}
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
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "zone": forms.Select(attrs={"class": "form-select"}),
            "water_type": forms.Select(attrs={"class": "form-select"}),
            "reporting_period": forms.Select(attrs={"class": "form-select"}),
            "allocation_acre_feet": forms.NumberInput(
                attrs={"step": "0.0001", "class": "form-input"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-textarea"}
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
            "account_number": forms.TextInput(attrs={"class": "form-input"}),
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "contact_name": forms.TextInput(attrs={"class": "form-input"}),
            "contact_email": forms.EmailInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-textarea"}
            ),
        }


class CsvUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "form-input"})
    )
    reporting_period = forms.ModelChoiceField(
        queryset=ReportingPeriod.objects.order_by("-start_date"),
        required=False,
        empty_label="No period (unassigned)",
        widget=forms.Select(attrs={"class": "form-select"}),
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
            "parcel": forms.Select(attrs={"class": "form-select"}),
            "transaction_date": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}
            ),
            "effective_date": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}
            ),
            "amount_acre_feet": forms.NumberInput(
                attrs={"step": "0.0001", "class": "form-input"}
            ),
            "water_type": forms.Select(attrs={"class": "form-select"}),
            "source_type": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(
                attrs={"rows": 3, "class": "form-textarea"}
            ),
            "reporting_period": forms.Select(attrs={"class": "form-select"}),
        }
