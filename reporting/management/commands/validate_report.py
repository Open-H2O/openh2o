# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that validates data quality for a state report.

Runs the reporting validators for the chosen report type over a --period and
prints the resulting warnings and errors, exiting non-zero if any errors exist.
Run it before generating or filing a report to confirm the data will pass at
the GEARS or CalWATRS portal.
"""
import sys

from django.core.management.base import BaseCommand, CommandError

from accounting.models import ReportingPeriod
from reporting.models import ReportTemplate
from reporting.validators import validate_report


class Command(BaseCommand):
    help = "Validate data quality for a state report"

    def add_arguments(self, parser):
        parser.add_argument(
            "report_type",
            choices=[c[0] for c in ReportTemplate.REPORT_TYPE_CHOICES],
        )
        parser.add_argument("--period", type=int, help="ReportingPeriod ID")

    def handle(self, *args, **options):
        report_type = options["report_type"]
        period_id = options.get("period")

        if period_id:
            try:
                period = ReportingPeriod.objects.get(pk=period_id)
            except ReportingPeriod.DoesNotExist:
                raise CommandError(f"ReportingPeriod {period_id} not found.")
        else:
            period = ReportingPeriod.objects.order_by("-start_date").first()
            if not period:
                raise CommandError("No reporting periods exist.")
            self.stdout.write(f"Using most recent period: {period.name}")

        self.stdout.write(f"Validating {report_type} for period: {period.name}")
        self.stdout.write("-" * 60)

        warnings = validate_report(period, report_type)

        if not warnings:
            self.stdout.write(self.style.SUCCESS("All checks passed. No issues found."))
            return

        has_errors = False
        for w in warnings:
            if w["level"] == "error":
                self.stdout.write(self.style.ERROR(f"  ERROR: {w['message']}"))
                has_errors = True
            else:
                self.stdout.write(self.style.WARNING(f"  WARNING: {w['message']}"))

        self.stdout.write("-" * 60)
        error_count = sum(1 for w in warnings if w["level"] == "error")
        warn_count = sum(1 for w in warnings if w["level"] == "warning")
        self.stdout.write(f"Total: {error_count} error(s), {warn_count} warning(s)")

        if has_errors:
            sys.exit(1)
