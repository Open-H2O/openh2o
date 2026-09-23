# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Forms for the drinking-water domain.

Created in 146-04 Task 2 for the production add-month door (D7); Task 3 added
the facility forms (D9) here and Task 4 adds the sampling schedule form, rather
than each starting its own file.
"""
from django import forms

from core.modules import is_enabled
from drinking.models import (
    PRODUCTION_PROVENANCE_TYPED,
    Analyte,
    SamplingPoint,
    SamplingSchedule,
    SystemFacility,
    SystemProduction,
)

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


# ---------------------------------------------------------------------------
# The facility door (146-04 Task 3, D9)
# ---------------------------------------------------------------------------


def _offer_the_well_link(form):
    """Keep the ``well`` field only on a deployment that has the wells module.

    ``wells`` is schema-resident, so on shape 2 (no wells, no parcels, no
    accounting) its table exists and is empty by design; a select over it
    would offer nothing and name a module the deployment does not run. The
    facility page gates its "Metered well" row on ``enabled_modules`` for the
    same reason, and this mirrors it.
    """
    if "well" not in form.fields:
        return
    if is_enabled("wells"):
        form.fields["well"].required = False
        form.fields["well"].queryset = form.fields["well"].queryset.order_by("name")
    else:
        del form.fields["well"]


class SystemFacilityForm(forms.ModelForm):
    """A facility the operator adds by hand, or later edits.

    ``system`` is set in the view (the deployment's own WaterSystem), so the
    model's ``unique_together`` on (system, facility_id) is not one Django's
    ModelForm can check on its own; ``clean_facility_id`` does it and names the
    id in the refusal.
    """

    class Meta:
        model = SystemFacility
        fields = [
            "facility_id", "name", "local_name", "facility_type",
            "activity_status", "is_source", "water_type", "well",
        ]
        widgets = {
            "facility_id": forms.TextInput(attrs={
                "class": "form-input", "placeholder": "e.g. 007",
            }),
            "name": forms.TextInput(attrs={
                "class": "form-input", "placeholder": "e.g. WL 007 CEDAR WELL 02",
            }),
            "local_name": forms.TextInput(attrs={
                "class": "form-input", "placeholder": "e.g. Cedar Well 02",
            }),
            "facility_type": forms.Select(attrs={"class": "form-select"}),
            "activity_status": forms.Select(attrs={"class": "form-select"}),
            "water_type": forms.Select(attrs={"class": "form-select"}),
            "well": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "facility_id": "Facility ID",
            "name": "The state's name",
            "local_name": "Local name",
            "facility_type": "Type",
            "activity_status": "Status",
            "is_source": "Water enters the system here",
            "water_type": "Water type",
            "well": "Metered well",
        }

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._system = system
        self.fields["facility_id"].required = True
        _offer_the_well_link(self)

    def clean_facility_id(self):
        facility_id = self.cleaned_data["facility_id"].strip()
        if self._system is not None:
            clash = self._system.facilities.filter(facility_id=facility_id)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError(
                    f"{self._system.name} already has a facility {facility_id}. "
                    "Open that one to change it."
                )
        return facility_id

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self._system is not None and instance.system_id is None:
            instance.system = self._system
        if instance.pk is None:
            instance.added_by_hand = True
        if commit:
            instance.save()
        return instance


class FacilityLocalNameForm(forms.ModelForm):
    """Edit a facility the federal record wrote: only what the operator owns.

    The id, the state's name, the type, status and water type came from EPA's
    record and stay as it published them (a re-onboarding would write them
    again). The operator's own name for it, and the link to its metered well
    where the deployment has wells, are this deployment's to set.
    """

    class Meta:
        model = SystemFacility
        fields = ["local_name", "well"]
        widgets = {
            "local_name": forms.TextInput(attrs={
                "class": "form-input", "placeholder": "e.g. Cedar Well 02",
            }),
            "well": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {"local_name": "Local name", "well": "Metered well"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _offer_the_well_link(self)


# ---------------------------------------------------------------------------
# The sampling schedule (146-04 Task 4, D8)
# ---------------------------------------------------------------------------


class SamplingScheduleForm(forms.ModelForm):
    """One row of the operator's sampling checklist.

    Both dates are typed. The form never fills ``next_due`` from ``frequency``
    and ``last_done``; see ``SamplingSchedule``'s docstring for why.
    """

    class Meta:
        model = SamplingSchedule
        fields = [
            "group_label", "analyte", "sampling_point", "frequency",
            "last_done", "next_due", "notes",
        ]
        widgets = {
            "group_label": forms.TextInput(attrs={
                "class": "form-input", "placeholder": "e.g. Coliform",
            }),
            "analyte": forms.Select(attrs={"class": "form-select"}),
            "sampling_point": forms.Select(attrs={"class": "form-select"}),
            "frequency": forms.Select(attrs={"class": "form-select"}),
            "last_done": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"
            ),
            "next_due": forms.DateInput(
                attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"
            ),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
        }
        labels = {
            "group_label": "What is sampled",
            "analyte": "Or one analyte",
            "sampling_point": "Sampling point",
            "last_done": "Last done",
            "next_due": "Next due",
        }

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._system = system
        self.fields["analyte"].queryset = Analyte.objects.order_by("name")
        points = SamplingPoint.objects.order_by("ps_code")
        if system is not None:
            points = points.filter(facility__system=system)
        self.fields["sampling_point"].queryset = points

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("group_label") and not cleaned.get("analyte"):
            raise forms.ValidationError(
                "Say what is sampled: type it, or choose one analyte."
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self._system is not None and instance.system_id is None:
            instance.system = self._system
        if commit:
            instance.save()
        return instance
