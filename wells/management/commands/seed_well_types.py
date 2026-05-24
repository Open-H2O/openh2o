from django.core.management.base import BaseCommand

from wells.models import WellType

WELL_TYPES = [
    {"name": "Production", "description": "Active extraction well"},
    {"name": "Monitoring", "description": "Groundwater level observation"},
    {"name": "Injection", "description": "Aquifer recharge injection well"},
    {"name": "Observation", "description": "Passive monitoring well"},
]


class Command(BaseCommand):
    help = "Seed default well types"

    def handle(self, *args, **options):
        created_count = 0
        for wt in WELL_TYPES:
            _, created = WellType.objects.get_or_create(
                name=wt["name"],
                defaults={"description": wt["description"]},
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {wt['name']}: {status}")
            if created:
                created_count += 1
        existing = len(WELL_TYPES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(WELL_TYPES)} well types ({created_count} created, {existing} existing)"
            )
        )
