import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounting.models import ReportingPeriod
from reporting.generators import generate_calwatrs_csv, generate_gears_csv
from reporting.models import ReportSubmission, ReportTemplate
from reporting.validators import validate_report


class Command(BaseCommand):
    help = "Generate a state report (GEARS CSV or CalWATRS CSV)"

    def add_arguments(self, parser):
        parser.add_argument(
            "report_type",
            choices=[c[0] for c in ReportTemplate.REPORT_TYPE_CHOICES],
        )
        parser.add_argument("--period", type=int, help="ReportingPeriod ID")
        parser.add_argument("--output", type=str, help="Output file path (default: stdout for CSV)")

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
                raise CommandError("No reporting periods exist. Create one first.")
            self.stdout.write(f"Using most recent period: {period.name}")

        warnings = validate_report(period, report_type)
        for w in warnings:
            style = self.style.ERROR if w["level"] == "error" else self.style.WARNING
            self.stdout.write(style(f"[{w['level'].upper()}] {w['message']}"))

        errors = [w for w in warnings if w["level"] == "error"]
        if errors:
            self.stdout.write(self.style.ERROR("Errors found. Report may be incomplete."))

        output_path = options.get("output")

        if report_type in ("gears_by_well", "gears_by_et"):
            method = "by_well" if report_type == "gears_by_well" else "by_et"
            csv_output = generate_gears_csv(period, method=method)
            content = csv_output.getvalue()
        elif report_type in ("calwatrs_a1", "calwatrs_a2"):
            template_type = "a1" if report_type == "calwatrs_a1" else "a2"
            csv_output = generate_calwatrs_csv(period, template_type=template_type)
            content = csv_output.getvalue()

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w") as f:
                f.write(content)
            self.stdout.write(self.style.SUCCESS(f"Written to {output_path}"))
        else:
            self.stdout.write(content)

        try:
            template = ReportTemplate.objects.get(report_type=report_type)
        except ReportTemplate.DoesNotExist:
            template = None

        if template:
            ReportSubmission.objects.create(
                report_template=template,
                reporting_period=period,
                status="draft",
                generated_file=output_path or "",
                generated_at=timezone.now(),
                validation_warnings=warnings,
            )
            self.stdout.write(self.style.SUCCESS("ReportSubmission record created (status: draft)"))
