from django import forms

from accounting.models import ReportingPeriod
from reporting.models import ReportTemplate

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


class ReportGenerateForm(forms.Form):
    report_template = forms.ModelChoiceField(
        queryset=ReportTemplate.objects.filter(is_active=True),
        empty_label="Select report type",
        widget=forms.Select(attrs={"style": FORM_SELECT_STYLE}),
    )
    reporting_period = forms.ModelChoiceField(
        queryset=ReportingPeriod.objects.order_by("-start_date"),
        empty_label="Select period",
        widget=forms.Select(attrs={"style": FORM_SELECT_STYLE}),
    )
