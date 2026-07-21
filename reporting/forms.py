# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for generating state compliance reports."""
from django import forms

from accounting.models import ReportingPeriod
from reporting.models import ReportTemplate
from reporting.report_types import unavailable_report_types


class ReportGenerateForm(forms.Form):
    report_template = forms.ModelChoiceField(
        queryset=ReportTemplate.objects.filter(is_active=True),
        empty_label="Select report type",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    reporting_period = forms.ModelChoiceField(
        queryset=ReportingPeriod.objects.order_by("-start_date"),
        empty_label="Select period",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, report_type_filter="", **kwargs):
        super().__init__(*args, **kwargs)

        queryset = ReportTemplate.objects.filter(is_active=True)
        if report_type_filter:
            queryset = queryset.filter(report_type__startswith=report_type_filter)

        # Seeding is only half the promise (ISS-082). With the seed gate in
        # place a FRESH instance never gets a disabled module's rows, so this
        # queryset empties on its own — but an instance that was seeded BEFORE
        # the module was switched off still carries them, and those rows must
        # not be offerable. `seed_report_templates` deliberately withholds
        # rather than deletes, so filtering here is what closes the gap for an
        # existing deployment.
        #
        # Excluded rather than allow-listed: a report type nobody has mapped is
        # not making a claim about any module, so it passes through untouched.
        # On a full deployment `unavailable_report_types()` is empty and this
        # `.exclude()` changes nothing — the rendered dropdown is identical.
        excluded = unavailable_report_types()
        if excluded:
            queryset = queryset.exclude(report_type__in=excluded)

        self.fields["report_template"].queryset = queryset
