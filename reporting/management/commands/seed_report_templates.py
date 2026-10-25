# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that seeds the default ReportTemplate rows.

Idempotently get_or_creates the four state report templates (GEARS by Well,
GEARS by ET, CalWATRS Direct Use / A1, CalWATRS To Storage / A2). Run it once
when standing up an instance so the report types are available to generate.

**Each row is gated on the module whose water it describes**. GEARS is
a groundwater filing and belongs to ``wells``; CalWATRS is a surface-water filing
and belongs to ``surface``. A deployment that does not run a domain is not
offered its filings -- before v2.4 an agency with no surface water was seeded two
CalWATRS templates anyway and invited to prepare a filing it could not make. The
owner mapping is ``reporting.report_types.REPORT_TYPE_OWNER``, which the generate
form reads too; it is not restated here.

**The GEARS half of this gate withholds when ``wells`` is switched off.**
``wells`` is optional (``required=False`` in ``core/modules.py``), so
``is_enabled("wells")`` is False on a deployment that turned it off, and the two
GEARS rows are then not seeded. While ``wells`` is on, those two rows seed.

**Withholding is not deleting.** A row for a disabled module is skipped, never
removed. ``ReportSubmission`` carries an FK to ``ReportTemplate``, so deleting a
template would take an agency's report history with it -- switching a module off
must not be a data-loss event. Not creating a new row and destroying an existing
one are different promises, and this command makes only the first.
"""
from django.core.management.base import BaseCommand

from reporting.models import ReportTemplate
from reporting.report_types import REPORT_TYPE_OWNER, report_type_is_available

REPORT_TEMPLATES = [
    {
        "name": "GEARS by Well",
        "report_type": "gears_by_well",
        "description": "Per-well monthly extraction volumes",
        "owner": REPORT_TYPE_OWNER["gears_by_well"],
    },
    {
        "name": "GEARS by ET",
        "report_type": "gears_by_et",
        "description": "Per-parcel groundwater extraction estimated from satellite consumptive use (ET)",
        "owner": REPORT_TYPE_OWNER["gears_by_et"],
    },
    {
        "name": "CalWATRS — Direct Use",
        "report_type": "calwatrs_a1",
        "description": "Surface water diverted and put to direct use, monthly volumes",
        "owner": REPORT_TYPE_OWNER["calwatrs_a1"],
    },
    {
        "name": "CalWATRS — To Storage",
        "report_type": "calwatrs_a2",
        "description": "Surface water diverted into storage for later use, monthly volumes",
        "owner": REPORT_TYPE_OWNER["calwatrs_a2"],
    },
]


class Command(BaseCommand):
    help = "Seed default report templates"

    def handle(self, *args, **options):
        created_count = 0
        seeded_count = 0
        for rt in REPORT_TEMPLATES:
            if not report_type_is_available(rt["report_type"]):
                # Named out loud rather than silently omitted: an operator who
                # goes looking for a missing report type should find the reason
                # in this command's own output, not have to infer it.
                self.stdout.write(
                    f"  {rt['name']} ({rt['report_type']}): "
                    f"skipped (module '{rt['owner']}' not enabled)"
                )
                continue
            seeded_count += 1
            _, created = ReportTemplate.objects.get_or_create(
                report_type=rt["report_type"],
                defaults={"name": rt["name"], "description": rt["description"]},
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {rt['name']} ({rt['report_type']}): {status}")
            if created:
                created_count += 1
        existing = seeded_count - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {seeded_count} report templates ({created_count} created, {existing} existing)"
            )
        )
