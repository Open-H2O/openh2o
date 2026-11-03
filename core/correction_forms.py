# SPDX-License-Identifier: AGPL-3.0-or-later
"""The form behind "Correct this record": one per kind, built from the kind's own entry form.

:func:`build` returns the form for a record, prefilled from it (bound when the
person pressed Save correction), and :func:`changes` turns a valid form into the
``changes`` that :func:`core.corrections.correct` takes: only the fields whose
value differs from the record's. Each form is the kind's own entry form where one
exists (MeterReadingForm, WaterLevelForm, ParcelLedgerForm's fields,
DiversionRecordForm, RechargeEventForm, SystemProductionForm), so its validation
is the entry form's validation, and a small form for the kinds that have none.

A correction's free text is its Reason, so the forms leave off Notes and the
Reason box of an edit form; the view reads the reason and the file itself.

Nothing here imports a project model at module scope: a kind whose module is
switched off is never imported.
"""

import copy
from decimal import Decimal

from django import forms
from django.utils import timezone

#: The kinds that have a correct screen. A kind missing here has none (404): a
#: recharge measurement is not listed on any page, and a use area is not
#: corrected with a new row.
KINDS = (
    "meter_reading", "water_level", "ledger_entry", "fallow_period", "diversion_record",
    "recharge_event", "lab_result", "production_record", "station_reading",
)


def has_screen(kind_key):
    return kind_key in KINDS


# -- Shared ----------------------------------------------------------------------------------


def shown(value):
    """A figure as a person would retype it: ``39781.3900`` is ``39781.39``.

    The table prints two places, so trailing zeros past the second go; a place
    that holds a digit stays.
    """
    if value is None or value == "":
        return ""
    text = f"{Decimal(value):f}"
    if "." not in text:
        return text
    whole, places = text.split(".")
    places = places.rstrip("0").ljust(2, "0")
    return f"{whole}.{places}"


def _local_date(moment):
    return timezone.localtime(moment).date() if timezone.is_aware(moment) else moment.date()


def _text_figures(form):
    """Figure fields are text inputs with the decimal keypad, prefilled to the table's places."""
    for name, field in form.fields.items():
        if not isinstance(field, forms.DecimalField):
            continue
        field.widget = forms.TextInput(attrs={"class": "form-input", "inputmode": "decimal"})
        if not form.is_bound:
            value = form.initial.get(name, field.initial)
            if value not in (None, ""):
                form.initial[name] = shown(value)
    return form


def _drop(form, *names):
    for name in names:
        form.fields.pop(name, None)
    return form


def _same(old, new):
    if isinstance(old, Decimal) or isinstance(new, Decimal):
        if old is None or new is None:
            return old is None and new is None
        return Decimal(old) == Decimal(new)
    if old in (None, "") and new in (None, ""):
        return True
    return old == new


def _model_changes(row, form, names):
    """The model-form fields among ``names`` whose cleaned value differs from the record's."""
    found = {}
    for name in names:
        if name not in form.fields or name not in form.cleaned_data:
            continue
        new = form.cleaned_data[name]
        field = type(row)._meta.get_field(name)
        old = getattr(row, field.attname) if field.is_relation else getattr(row, name)
        if field.is_relation:
            new_id = getattr(new, "pk", new)
            if old != new_id:
                found[name] = new
        elif not _same(old, new):
            found[name] = new
    return found


# -- Per kind --------------------------------------------------------------------------------


def _meter_reading(row, data):
    from wells.forms import MeterReadingForm

    form = MeterReadingForm(
        data or None, meter=row.meter, exclude_pk=row.pk,
        initial={
            "reading_date": _local_date(row.reading_date),
            "current_value": row.current_value,
            "quality": "estimated" if row.quality == "estimated" else "provisional",
        },
    )
    return _text_figures(_drop(form, "notes"))


def _meter_reading_changes(row, form):
    data = form.cleaned_data
    found = {}
    if data["reading_date"] != _local_date(row.reading_date):
        found["reading_date"] = data["reading_date"]
    if not _same(row.current_value, data["current_value"]):
        found["current_value"] = data["current_value"]
    # An unchanged choice keeps the record's own quality: an approved read stays approved.
    if (data["quality"] == "estimated") != (row.quality == "estimated"):
        found["quality"] = data["quality"]
    return found


def _water_level(row, data):
    from wells.forms import WaterLevelForm

    class CorrectionLevelForm(WaterLevelForm):
        """The entry form; its "no measurement" reason is named apart, because Reason is the correction's."""

        def add_prefix(self, field_name):
            return "no_reason" if field_name == "reason" else super().add_prefix(field_name)

    form = CorrectionLevelForm(
        data or None,
        initial={
            "level_date": _local_date(row.measurement_date),
            "method": row.method,
            "depth_ft": row.value,
            "no_measurement": row.value is None,
            "reason": row.no_measurement_reason,
        },
    )
    form.fields["reason"].label = "Why the depth was not read"
    return _text_figures(_drop(form, "notes"))


def _water_level_changes(row, form):
    data = form.cleaned_data
    unmeasured = data["no_measurement"]
    found = {}
    if data["level_date"] != _local_date(row.measurement_date):
        found["measurement_date"] = data["level_date"]
    value = None if unmeasured else data["depth_ft"]
    if not _same(row.value, value):
        found["value"] = value
    if (data.get("method") or "") != (row.method or ""):
        found["method"] = data.get("method") or ""
    why = data["reason"] if unmeasured else ""
    if why != (row.no_measurement_reason or ""):
        found["no_measurement_reason"] = why
    return found


def _ledger_entry(row, data):
    from accounting.forms import ParcelLedgerForm

    class CorrectionLedgerForm(ParcelLedgerForm):
        class Meta(ParcelLedgerForm.Meta):
            fields = ["effective_date", "amount_acre_feet", "water_type", "description"]

        def __init__(self, *args, **kwargs):
            # The entry form orders its use area list; a correction keeps the use area.
            forms.ModelForm.__init__(self, *args, **kwargs)

    # Prefixed: the ledger's own filters (sent with the request, so the table keeps them)
    # include a water_type of their own.
    form = CorrectionLedgerForm(data or None, instance=copy.copy(row), prefix="correct")
    form.fields["description"].widget = forms.TextInput(attrs={"class": "form-input"})
    return _text_figures(form)


def _diversion_record(row, data):
    from surface.forms import DiversionRecordEditForm

    form = DiversionRecordEditForm(data or None, instance=copy.copy(row), pod=row.point_of_diversion)
    return _text_figures(_drop(form, "reason", "notes"))


def _recharge_event(row, data):
    from recharge.forms import RechargeEventEditForm

    form = RechargeEventEditForm(data or None, instance=copy.copy(row))
    return _text_figures(_drop(form, "reason", "notes"))


def _production_record(row, data):
    from drinking.forms import SystemProductionForm

    form = SystemProductionForm(data or None, instance=copy.copy(row), system=row.system)
    return _text_figures(_drop(form, "notes"))


def _lab_result(row, data):
    class LabResultCorrectionForm(forms.ModelForm):
        class Meta:
            from drinking.models import SampleResult

            model = SampleResult
            fields = ["result_value", "less_than_rl", "reporting_level", "unit"]
            labels = {
                "result_value": "Result",
                "less_than_rl": "Less than the reporting level",
                "reporting_level": "Reporting level",
            }
            widgets = {"unit": forms.TextInput(attrs={"class": "form-input"})}

    form = LabResultCorrectionForm(data or None, instance=copy.copy(row))
    return _text_figures(form)


def _station_reading(row, data):
    class StationReadingCorrectionForm(forms.ModelForm):
        class Meta:
            from datasync.models import TypedReading

            model = TypedReading
            fields = ["observation_date", "value"]
            labels = {"observation_date": "Reading date", "value": "Value"}
            widgets = {
                "observation_date": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            }

    form = StationReadingCorrectionForm(data or None, instance=copy.copy(row))
    return _text_figures(form)


class FallowCorrectionForm(forms.Form):
    """A fallow period's start and end month; any day in the month will do."""

    start_month = forms.DateField(
        label="Start month (pick any day in it)",
        error_messages={
            "required": "Pick a day in the start month.",
            "invalid": "Pick a day in the start month.",
        },
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
    )
    end_month = forms.DateField(
        label="End month (optional, pick any day in it)",
        required=False,
        error_messages={"invalid": "Pick a day in the end month, or leave it blank."},
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
    )

    def __init__(self, *args, row, **kwargs):
        super().__init__(*args, **kwargs)
        self.row = row

    def clean(self):
        from accounting.locks import finalized_message
        from parcels.forms import FallowPeriodForm
        from parcels.models import FallowPeriod, overlap_sentence

        cleaned = super().clean()
        if self.errors:
            return cleaned
        start = cleaned["start_month"].replace(day=1)
        end = cleaned.get("end_month")
        end = end.replace(day=1) if end else None
        cleaned["start_month"], cleaned["end_month"] = start, end
        if end and end < start:
            raise forms.ValidationError("The end month cannot be before the start month.")
        # `_finalized_period` stands aside inside the recorded override.
        locked = FallowPeriodForm._finalized_period(start, end)
        if locked is not None:
            raise forms.ValidationError(finalized_message(locked.name))
        clash = FallowPeriod(
            parcel=self.row.parcel, start_month=start, end_month=end, replaces=self.row
        ).overlapping()
        if clash:
            raise forms.ValidationError(overlap_sentence(clash[0]))
        return cleaned


def _fallow_period(row, data):
    return FallowCorrectionForm(
        data or None, row=row,
        initial={"start_month": row.start_month, "end_month": row.end_month},
    )


def _fallow_changes(row, form):
    data = form.cleaned_data
    found = {}
    if data["start_month"] != row.start_month:
        found["start_month"] = data["start_month"]
    if data["end_month"] != row.end_month:
        found["end_month"] = data["end_month"]
    return found


def _by_registry(names):
    def make(row, form):
        return _model_changes(row, form, names)

    return make


_BUILDERS = {
    "meter_reading": (_meter_reading, _meter_reading_changes),
    "water_level": (_water_level, _water_level_changes),
    "ledger_entry": (_ledger_entry, None),
    "fallow_period": (_fallow_period, _fallow_changes),
    "diversion_record": (_diversion_record, None),
    "recharge_event": (_recharge_event, None),
    "lab_result": (_lab_result, None),
    "production_record": (_production_record, None),
    "station_reading": (_station_reading, None),
}


def build(kind_key, row, data=None):
    """The correction form for ``row``: prefilled from it, or bound to ``data`` (a POST).

    Its field ids carry the record's own, because the entry form of the same kind can
    be on the same page and ids are unique.
    """
    form = _BUILDERS[kind_key][0](row, data)
    form.auto_id = f"correct_{kind_key}_{row.pk}_%s"
    return form


def changes(kind_key, row, form):
    """The ``changes`` for :func:`core.corrections.correct` from a valid ``form``: what differs."""
    from core import corrections

    custom = _BUILDERS[kind_key][1]
    if custom is not None:
        return custom(row, form)
    return _model_changes(row, form, corrections.get_kind(kind_key)["correct_fields"])


