# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Export the SourceParameter crosswalk as CSV.

Produces the same shape as docs/crosswalk.csv: one row per (source, native code)
mapping, denormalized with the canonical ObservedProperty fields so another
system can consume it without joining. Writes to stdout by default, or to a path
with --output.

    python manage.py export_crosswalk
    python manage.py export_crosswalk --output docs/crosswalk.csv
"""

import csv
import sys

from django.core.management.base import BaseCommand

from standards.models import SourceParameter

HEADER = [
    "source_code",
    "source_parameter_code",
    "observed_property_key",
    "observed_property_name",
    "usgs_pcode",
    "wqx_characteristic_name",
    "ucum_unit",
]


class Command(BaseCommand):
    help = "Export the SourceParameter crosswalk as CSV (stdout or --output path)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            metavar="PATH",
            help="Write CSV to this file instead of stdout.",
        )

    def handle(self, *args, **options):
        rows = (
            SourceParameter.objects.select_related("observed_property")
            .order_by("source_code", "parameter_code")
        )

        out_path = options.get("output")
        handle = open(out_path, "w", newline="") if out_path else sys.stdout
        try:
            writer = csv.writer(handle)
            writer.writerow(HEADER)
            count = 0
            for sp in rows:
                op = sp.observed_property
                writer.writerow([
                    sp.source_code,
                    sp.parameter_code,
                    op.key if op else "",
                    op.name if op else "",
                    op.usgs_pcode if op else "",
                    op.wqx_characteristic_name if op else "",
                    op.ucum_unit if op else "",
                ])
                count += 1
        finally:
            if out_path:
                handle.close()

        if out_path:
            self.stdout.write(
                self.style.SUCCESS(f"Wrote {count} crosswalk rows to {out_path}")
            )
