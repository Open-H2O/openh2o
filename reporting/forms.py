# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forms for generating state compliance reports."""
from django import forms

from accounting.models import ReportingPeriod
from reporting.models import ReportTemplate


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
        if report_type_filter:
            self.fields["report_template"].queryset = (
                ReportTemplate.objects.filter(
                    is_active=True, report_type__startswith=report_type_filter
                )
            )
