# SPDX-License-Identifier: AGPL-3.0-or-later
"""The form behind a use area's fallow periods.

A person picks any day in the start month (and, optionally, the end month);
the form stores each as the first day of its month. It refuses, in one plain
sentence each, a month missing or unreadable, an end before the start, a period
that touches a finalized water year, and a period that overlaps another of the
same use area.
"""
import datetime as dt

from django import forms

from accounting.locks import finalized_message
from accounting.models import CalculationRun, ReportingPeriod
from parcels.models import FallowPeriod, overlap_sentence


def first_of_month(day):
    return day.replace(day=1)


def next_month(day):
    return dt.date(day.year + (day.month == 12), day.month % 12 + 1, 1)


class FallowPeriodForm(forms.Form):
    """Add a fallow period, or (``ending`` given) give an open one its end month."""

    start_month = forms.DateField(
        label="Start month (pick any day in it)",
        required=True,
        error_messages={
            "required": "Pick a day in the start month.",
            "invalid": "Pick a day in the start month.",
        },
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input", "style": "border-color: var(--color-accent);"}),
    )
    end_month = forms.DateField(
        label="End month (optional, pick any day in it)",
        required=False,
        error_messages={"invalid": "Pick a day in the end month, or leave it blank."},
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input", "style": "border-color: var(--color-accent);"}),
    )

    def __init__(self, *args, parcel, ending=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.parcel = parcel
        self.ending = ending
        if ending is not None:
            del self.fields["start_month"]
            self.fields["end_month"].required = True
            self.fields["end_month"].error_messages["required"] = "Pick a day in the end month."

    def first_error(self):
        """The one sentence to show, or ""."""
        for errors in self.errors.values():
            return errors[0]
        return ""

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if self.ending is not None:
            start = self.ending.start_month
        else:
            start = first_of_month(cleaned["start_month"])
            cleaned["start_month"] = start
        end = cleaned.get("end_month")
        end = first_of_month(end) if end else None
        cleaned["end_month"] = end
        if start and end and end < start:
            raise forms.ValidationError("The end month cannot be before the start month.")

        # The months this save changes: the whole span when adding, the months
        # after the new end month when ending an open period.
        changed_from = next_month(end) if self.ending is not None else start
        changed_to = None if self.ending is not None else end
        locked = self._finalized_period(changed_from, changed_to)
        if locked is not None:
            raise forms.ValidationError(finalized_message(locked.name))

        if self.ending is None:
            clash = FallowPeriod(parcel=self.parcel, start_month=start, end_month=end).overlapping()
            if clash:
                raise forms.ValidationError(overlap_sentence(clash[0]))
        return cleaned

    @staticmethod
    def _finalized_period(first, last):
        """The earliest finalized water year that has a month from ``first`` through ``last`` (None: no end)."""
        periods = ReportingPeriod.objects.filter(is_finalized=True, end_date__gte=first)
        if last is not None:
            periods = periods.filter(start_date__lt=next_month(last))
        return periods.order_by("start_date").first()

    def months_to_recalculate(self):
        """The calculated months this save covers or uncovers, as first-of-month dates.

        A period with an end month covers its own months up to this month. One
        without an end covers every month from its start through the last month
        the use area has been calculated for.
        """
        cleaned = self.cleaned_data
        if self.ending is not None:
            first, last = next_month(cleaned["end_month"]), None
        else:
            first, last = cleaned["start_month"], cleaned["end_month"]
        today = first_of_month(dt.date.today())
        if last is None:
            latest = (
                CalculationRun.objects.filter(parcel=self.parcel)
                .order_by("-period")
                .values_list("period", flat=True)
                .first()
            )
            if latest is None:
                return []
            year, month = latest.split("-")
            last = dt.date(int(year), int(month), 1)
        else:
            last = min(last, today)
        months = []
        month = first
        while month <= last:
            months.append(month)
            month = next_month(month)
        return months

    def save(self, user=None):
        """Write the period: the new one, or the open one with its end month set."""
        who = user if getattr(user, "is_authenticated", False) else None
        if self.ending is not None:
            self.ending.end_month = self.cleaned_data["end_month"]
            self.ending.save()
            return self.ending
        return FallowPeriod.objects.create(
            parcel=self.parcel,
            start_month=self.cleaned_data["start_month"],
            end_month=self.cleaned_data["end_month"],
            created_by=who,
        )
