# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for reporting periods, allocation plans, and water accounts."""
from django import forms

from accounting.models import AllocationPlan, ReportingPeriod, WaterAccount, WaterType
from core.modules import is_enabled
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

    def clean(self):
        # Catch end-before-start at the form layer so it never reaches the DB
        # CheckConstraint (start_date < end_date), which would 500 on save.
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end <= start:
            self.add_error("end_date", "The end date must be after the start date.")
        return cleaned


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
        labels = {
            "allocation_acre_feet": "Allocation (AF)",
        }
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
    """Create or edit a water account, including Q8's unit kind and delivery.

    `unit_kind` is nullable at the model (accounts predating the field) but
    required here (146-05 Task 3). `delivery_well` is a real field on
    `WaterAccount` (`wells` is schema-resident, so the arrow is safe -- see
    `core.modules.SCHEMA_EXCEPTIONS`); it is dropped from the form entirely
    when `wells` is disabled, rather than shown and refused, the same
    "gated by is_enabled" the plan asks for. `delivery_pod` is NOT a model
    field -- `surface` is truly removable, so that link lives on
    `surface.WaterAccountDeliveryPoint` instead (one row per account) and this
    form adds it as a plain `ModelChoiceField` only when `surface` is enabled,
    reading and writing it itself in `__init__` / `save()`.
    """

    class Meta:
        model = WaterAccount
        fields = [
            "account_number",
            "name",
            "status",
            "unit_kind",
            "delivery_well",
            "contact_name",
            "contact_email",
            "notes",
        ]
        widgets = {
            "account_number": forms.TextInput(attrs={"class": "form-input"}),
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "unit_kind": forms.Select(attrs={"class": "form-select"}),
            "delivery_well": forms.Select(attrs={"class": "form-select"}),
            "contact_name": forms.TextInput(attrs={"class": "form-input"}),
            "contact_email": forms.EmailInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-textarea"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Required on the form though nullable on the model (accounts made
        # before this field existed, and the data migration's own farm_unit
        # default, both need to stay valid rows without a form re-save).
        self.fields["unit_kind"].required = True

        if is_enabled("wells"):
            from wells.models import Well

            self.fields["delivery_well"].queryset = Well.objects.order_by("name")
            self.fields["delivery_well"].empty_label = "None"
        else:
            del self.fields["delivery_well"]

        # Local import: `surface` is optional and truly removable (Phase 87),
        # so this must not run at module scope -- the same guard
        # `accounting/views.py` already uses for the same module.
        self.surface_enabled = is_enabled("surface")
        if self.surface_enabled:
            from surface.models import PointOfDiversion

            initial_pod = None
            if self.instance.pk:
                link = getattr(self.instance, "surface_delivery_point", None)
                initial_pod = link.point_of_diversion_id if link else None
            self.fields["delivery_pod"] = forms.ModelChoiceField(
                queryset=PointOfDiversion.objects.order_by("name"),
                required=False,
                empty_label="None",
                widget=forms.Select(attrs={"class": "form-select"}),
                label="Delivery point of diversion",
                help_text="This account's delivery point of diversion, if "
                "it has one. An account is delivered through a point of "
                "diversion or a well, never both.",
                initial=initial_pod,
            )

    def clean(self):
        cleaned = super().clean()
        delivery_well = cleaned.get("delivery_well") if "delivery_well" in self.fields else None
        delivery_pod = cleaned.get("delivery_pod") if "delivery_pod" in self.fields else None
        if delivery_well and delivery_pod:
            self.add_error(
                "delivery_pod",
                "An account can be delivered through a point of diversion or "
                "a well, not both.",
            )
        return cleaned

    def save(self, commit=True):
        account = super().save(commit=commit)
        if commit and self.surface_enabled:
            self._save_delivery_pod(account)
        return account

    def _save_delivery_pod(self, account):
        from surface.models import WaterAccountDeliveryPoint

        pod = self.cleaned_data.get("delivery_pod")
        if pod:
            WaterAccountDeliveryPoint.objects.update_or_create(
                account=account, defaults={"point_of_diversion": pod}
            )
        else:
            WaterAccountDeliveryPoint.objects.filter(account=account).delete()


class CsvUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "file-picker-input"})
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
