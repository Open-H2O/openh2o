# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for surface water diversion record entry."""
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.db.models import Q

from surface.models import (
    DiversionRecord,
    MeasuringDevice,
    PointOfDiversion,
    PointOfDiversionDevice,
    WaterRight,
)

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
            "max_flow_rate_cfs", "diversion_type",
            "method", "device", "data_state", "notes",
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
            "method": forms.Select(attrs={"class": "form-select"}),
            "device": forms.Select(attrs={"class": "form-select"}),
            "data_state": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={
                "class": "form-textarea",
                "rows": 2,
                "placeholder": "Optional notes...",
            }),
        }
        # The widget is `type="date"` (a full calendar-day picker) but the
        # model only ever keeps the month -- clean_month below normalizes
        # whatever day is picked to the 1st. Unlabelled, the date input
        # reads as "Month, no year"; this label says what the field actually
        # wants.
        labels = {"month": "Month (pick any day in it)"}

    def __init__(self, *args, pod=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pod = pod
        # Blank means "fully consumed" — default to 0 rather than a required field,
        # so existing entry flows are unchanged when the operator leaves it empty.
        self.fields["returned_af"].required = False
        self.fields["method"].required = False
        # No form offers the retired estimate method; a record that already
        # holds it keeps it in its own form so that saving does not blank it.
        offered = [("", "---------")] + list(DiversionRecord.OFFERED_METHOD_CHOICES)
        if self.instance.pk and self.instance.method == "estimated_from_use":
            offered += [c for c in DiversionRecord.METHOD_CHOICES if c[0] == "estimated_from_use"]
        self.fields["method"].choices = offered
        self.fields["device"].required = False
        # data_state has no blank choice (unlike method) since every record
        # DOES have a data state -- but the model's own default is
        # 'provisional', and a caller that posts without this key (every
        # older test, and any future programmatic caller) should get
        # that default rather than a spurious "this field is required".
        self.fields["data_state"].required = False

        # The device choices are this point's own devices,
        # current link first -- an operator entering a record for POD A
        # should never be offered POD B's meter. `pod=None` (an unbound
        # form used outside a POD's own page, if one ever exists) leaves the
        # queryset empty rather than showing every device in the district.
        if pod is not None:
            self.fields["device"].queryset = (
                MeasuringDevice.objects
                .filter(pointofdiversiondevice__point_of_diversion=pod)
                .order_by("-pointofdiversiondevice__is_current", "nickname")
            )
        else:
            self.fields["device"].queryset = MeasuringDevice.objects.none()

        # Defaults on create only (an existing instance keeps its own saved
        # values): if the point has a current device, default to it and to
        # method='device' -- the common case is that today's entry came off
        # the device already on the headgate. With no current device, method
        # starts blank rather than guessing one the operator hasn't stated.
        if pod is not None and self.instance.pk is None:
            current_link = (
                PointOfDiversionDevice.objects
                .filter(point_of_diversion=pod, is_current=True)
                .select_related("device")
                .first()
            )
            if current_link is not None:
                # Direct assignment, not setdefault: model_to_dict already
                # populated self.initial["device"]/["method"] with the blank
                # values off a fresh unsaved instance, so setdefault would
                # see those keys as already present and never override them.
                self.initial["device"] = current_link.device_id
                self.initial["method"] = "device"

    def clean_data_state(self):
        """A blank submission falls back to the model's own default.

        ``data_state`` has no blank choice in the state's vocabulary -- every
        record IS in some data state -- so an omitted or empty post (a
        pre-146-03 caller, or an HTML form whose select was never touched)
        should read as "the default", never as an empty string saved to a
        CharField with no blank choice.
        """
        return self.cleaned_data.get("data_state") or "provisional"

    def clean_month(self):
        """Normalize any picked day to the 1st -- a season is a month, not a date.

        The unique constraint on (point_of_diversion, month, diversion_type)
        is only meaningful per calendar month if every record for a given
        month stores the SAME day; without this, "March 1" and "March 15"
        collide with nothing and duplicate March records could both save.
        """
        month = self.cleaned_data.get("month")
        if month is not None:
            stored = self.instance.month if self.instance.pk else None
            if stored is not None and (stored.year, stored.month) == (
                month.year,
                month.month,
            ):
                # Editing a record keeps the day it was stored with; only a
                # change of month moves it, and it moves to the 1st.
                return stored
            month = month.replace(day=1)
        return month

    def clean(self):
        """Refuse a second record for the same point, month and type, whatever its day."""
        cleaned = super().clean()
        month = cleaned.get("month")
        kind = cleaned.get("diversion_type")
        if self.pod is not None and month is not None and kind:
            following = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            others = DiversionRecord.objects.filter(
                point_of_diversion=self.pod,
                diversion_type=kind,
                month__gte=month.replace(day=1),
                month__lt=following,
            )
            if self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            if others.exists():
                self.add_error(
                    "month",
                    "A record for this month and diversion type is already on "
                    "file. Edit that record instead.",
                )
        return cleaned

    def clean_returned_af(self):
        """Surface the model guard as a readable field error, not a 500.

        ``DiversionRecord.clean()`` is the backstop, but ``Model.save()``
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
    """Form for editing POD metadata (``surface:pod_edit`` is its door).

    water_right and location are excluded (set via separate UI: the POD
    page's own "Water right" panel and the map click that placed the point).
    The canal-loss fractions sit under the template's own "Canal losses"
    heading. A fraction sum of 1 or more is refused with a plain sentence
    (the canal split refuses a month where nothing would reach the
    fields) by ``PointOfDiversion.clean()``, which this form's full_clean
    runs on the shares save() will store (a stated lining sets the
    default seepage and evaporation), so the error is shown once.
    """

    class Meta:
        model = PointOfDiversion
        fields = [
            "name", "stream_name", "max_rate_cfs", "status",
            "local_name",
            "evaporation_fraction", "evaporation_band_percent",
            "seepage_fraction", "seepage_band_percent",
            "spill_fraction", "spill_band_percent", "spill_device",
            "loss_basis", "lining", "division_method", "owner_account", "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "stream_name": forms.TextInput(attrs={"class": "form-input"}),
            "max_rate_cfs": forms.NumberInput(attrs={
                "class": "form-input",
                "step": "0.0001",
            }),
            "status": forms.Select(attrs={"class": "form-select"}),
            "local_name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "e.g. Turnout 14",
            }),
            "evaporation_fraction": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.0001", "min": "0", "max": "1",
            }),
            "seepage_fraction": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.0001", "min": "0", "max": "1",
            }),
            "spill_fraction": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.0001", "min": "0", "max": "1",
            }),
            "evaporation_band_percent": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.01", "placeholder": "blank if not stated",
            }),
            "seepage_band_percent": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.01", "placeholder": "blank if not stated",
            }),
            "spill_band_percent": forms.NumberInput(attrs={
                "class": "form-input", "step": "0.01", "placeholder": "blank if not stated",
            }),
            "spill_device": forms.Select(attrs={"class": "form-select"}),
            "loss_basis": forms.Select(attrs={"class": "form-select"}),
            "lining": forms.Select(attrs={"class": "form-select"}),
            "division_method": forms.Select(attrs={"class": "form-select"}),
            "owner_account": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
        }
        labels = {
            "local_name": "Known locally as",
            "evaporation_fraction": "Evaporation share (0 to 1)",
            "evaporation_band_percent": "Evaporation uncertainty (±%)",
            "seepage_fraction": "Seepage share (0 to 1)",
            "seepage_band_percent": "Seepage uncertainty (±%)",
            "spill_fraction": "Spill share (0 to 1)",
            "spill_band_percent": "Spill uncertainty (±%)",
            "spill_device": "Spill measured at",
            "loss_basis": "Basis of the loss shares",
            "lining": "Lining",
            "division_method": "How the water is divided among the fields",
            "owner_account": "Canal owner",
        }
        help_texts = {
            "lining": "When the basis is Platform default, OpenH2O sets the "
            "seepage share from the lining: 25 percent for an unlined canal, "
            "5 percent for a lined canal and 0 for a pipe. OpenH2O does not "
            "change a measured or estimated share.",
            "seepage_fraction": "Share of the diverted volume lost to canal "
            "seepage. When the basis is Platform default and the lining is "
            "stated, OpenH2O sets this share to the default for that lining "
            "when you save.",
            # The basis now sits above the three shares, beside the lining.
            "loss_basis": "How the three shares below were set: measured on "
            "this canal, estimated for this canal, or the platform's default.",
            "evaporation_fraction": "Share of the diverted volume lost to "
            "evaporation off the canal. The platform's default is 1 percent "
            "for an open canal and 0 for a pipe. A share marked as measured "
            "or estimated replaces this default.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The spill device select is this point's own devices only -- an
        # unsaved POD (this form is edit-only, reached from an existing
        # point's own page) has none yet.
        if self.instance is not None and self.instance.pk:
            self.fields["spill_device"].queryset = MeasuringDevice.objects.filter(
                pointofdiversiondevice__point_of_diversion=self.instance
            ).distinct()
        else:
            self.fields["spill_device"].queryset = MeasuringDevice.objects.none()
        self.fields["spill_device"].required = False
        self.fields["evaporation_band_percent"].required = False
        self.fields["seepage_band_percent"].required = False
        self.fields["spill_band_percent"].required = False
        # A post that leaves the method out keeps the point's current one.
        self.fields["division_method"].required = False
        self.fields["lining"].required = False
        self.fields["lining"].choices = [("", "Not stated")] + list(
            PointOfDiversion.LINING_CHOICES
        )

    def clean_division_method(self):
        return self.cleaned_data.get("division_method") or self.instance.division_method

    def clean_lining(self):
        return self.cleaned_data.get("lining") or None

    # The sum of the three shares is checked once, by PointOfDiversion.clean(),
    # which the form's full_clean runs on what save() will store: while the
    # basis is the default, a stated lining replaces the typed seepage and
    # evaporation shares. A second check here showed the error twice.


class MeasuringDeviceForm(forms.ModelForm):
    """Create/edit a measuring device (the 23 CCR 934(b)(1) registry).

    ``water_rights`` is a multi-select limited to the point of diversion's own
    right plus any other active right -- narrowed in
    ``__init__`` rather than on the model field, since the model has no single
    point to scope from.
    """

    class Meta:
        model = MeasuringDevice
        fields = [
            "nickname", "device_type", "make", "model_number",
            "recording_make", "recording_model", "recording_type",
            "measured_parameter", "raw_units", "accuracy_percent",
            "installed_on", "installer_contact", "last_evidence_on",
            "state_device_id", "status", "water_rights", "notes",
        ]
        labels = {
            "last_evidence_on": "Last evidence of proper functioning",
            "state_device_id": "State device ID",
        }
        widgets = {
            "nickname": forms.TextInput(attrs={"class": "form-input"}),
            "device_type": forms.Select(attrs={"class": "form-select"}),
            "make": forms.TextInput(attrs={"class": "form-input"}),
            "model_number": forms.TextInput(attrs={"class": "form-input"}),
            "recording_make": forms.TextInput(attrs={"class": "form-input"}),
            "recording_model": forms.TextInput(attrs={"class": "form-input"}),
            "recording_type": forms.TextInput(attrs={"class": "form-input"}),
            "measured_parameter": forms.Select(attrs={"class": "form-select"}),
            "raw_units": forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. cfs"}),
            "accuracy_percent": forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
            "installed_on": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "installer_contact": forms.TextInput(attrs={"class": "form-input"}),
            "last_evidence_on": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "state_device_id": forms.TextInput(attrs={"class": "form-input"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "water_rights": forms.SelectMultiple(attrs={"class": "form-select", "size": 6}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
        }

    def __init__(self, *args, pod=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The rights-served field: this point's own right plus any other
        # active right, ordered the way the water rights list already is.
        query = Q(status="active")
        if pod is not None and pod.water_right_id:
            query |= Q(pk=pod.water_right_id)
        self.fields["water_rights"].queryset = (
            WaterRight.objects.filter(query).distinct().order_by("right_id")
        )
        self.fields["water_rights"].required = False


class WaterRightForm(forms.ModelForm):
    """Create/edit a water right.

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
            "notes",
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


