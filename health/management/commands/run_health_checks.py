# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that runs the platform health-check suite.

Executes every check in health.checks, persists each outcome as a
HealthCheckResult row, and prints a colour-coded status table (or JSON with
--json; a single --category narrows the run). Run it to confirm the deployment
is healthy or to record a point-in-time status snapshot.
"""
import json

from django.core.management.base import BaseCommand

from health.checks import run_all_checks
from health.models import HealthCheckResult


class Command(BaseCommand):
    help = "Run all health checks and save results"

    def add_arguments(self, parser):
        parser.add_argument(
            "--json", action="store_true", help="Output results as JSON"
        )
        parser.add_argument(
            "--category", type=str, help="Run a single category only"
        )

    def handle(self, *args, **options):
        results = run_all_checks()

        if options["category"]:
            results = [r for r in results if r["category"] == options["category"]]
            if not results:
                self.stderr.write(f"Unknown category: {options['category']}")
                return

        objects = [
            HealthCheckResult(
                category=r["category"],
                status=r["status"],
                message=r["message"],
                details=r.get("details", {}),
            )
            for r in results
        ]
        HealthCheckResult.objects.bulk_create(objects)

        if options["json"]:
            self.stdout.write(json.dumps(results, indent=2, default=str))
        else:
            self.stdout.write("")
            self.stdout.write(f"{'Category':<20} {'Status':<10} {'Message'}")
            self.stdout.write("-" * 70)
            for r in results:
                status = r["status"]
                if status == "skipped":
                    # A check whose module is switched off is neither healthy nor
                    # broken; printing GREEN here would claim it ran. The status
                    # field is authoritative — details.module_disabled is only
                    # provenance now.
                    status_display = f"{'N/A':<10}"
                elif status == "green":
                    status_display = self.style.SUCCESS(f"{'GREEN':<10}")
                elif status == "yellow":
                    status_display = self.style.WARNING(f"{'YELLOW':<10}")
                else:
                    status_display = self.style.ERROR(f"{'RED':<10}")
                self.stdout.write(f"{r['category']:<20} {status_display} {r['message']}")
            self.stdout.write("")

            green_count = sum(1 for r in results if r["status"] == "green")
            # The denominator is APPLICABLE checks, not every check. Dividing by
            # every check while skipped rows scored as green is what printed
            # "12/13 healthy" on a deployment running half the platform — the
            # score went UP as modules went away (ISS-087). Both numbers are
            # shown so a dropped check stays distinguishable from one that never
            # existed.
            applicable = sum(1 for r in results if r["status"] != "skipped")
            skipped = len(results) - applicable
            skipped_note = f", {skipped} skipped" if skipped else ""
            self.stdout.write(
                f"Summary: {green_count}/{applicable} healthy "
                f"({applicable} applicable of {len(results)}{skipped_note})"
            )
