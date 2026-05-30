from django.core.management.base import BaseCommand

from reporting.models import ReportTemplate

REPORT_TEMPLATES = [
    {
        "name": "GEARS by Well",
        "report_type": "gears_by_well",
        "description": "Per-well monthly extraction volumes",
    },
    {
        "name": "GEARS by ET",
        "report_type": "gears_by_et",
        "description": "Per-parcel ET-based extraction estimates",
    },
    {
        "name": "CalWATRS — Direct Use",
        "report_type": "calwatrs_a1",
        "description": "Surface water diverted and put to direct use, monthly volumes",
    },
    {
        "name": "CalWATRS — To Storage",
        "report_type": "calwatrs_a2",
        "description": "Surface water diverted into storage for later use, monthly volumes",
    },
]


class Command(BaseCommand):
    help = "Seed default report templates"

    def handle(self, *args, **options):
        created_count = 0
        for rt in REPORT_TEMPLATES:
            _, created = ReportTemplate.objects.get_or_create(
                report_type=rt["report_type"],
                defaults={"name": rt["name"], "description": rt["description"]},
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {rt['name']} ({rt['report_type']}): {status}")
            if created:
                created_count += 1
        existing = len(REPORT_TEMPLATES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(REPORT_TEMPLATES)} report templates ({created_count} created, {existing} existing)"
            )
        )
