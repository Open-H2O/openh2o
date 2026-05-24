from django.core.management.base import BaseCommand

from accounting.models import WaterType

WATER_TYPES = [
    {"name": "Groundwater", "code": "GW"},
    {"name": "Surface Water", "code": "SW"},
    {"name": "Recycled Water", "code": "RW"},
    {"name": "Stormwater", "code": "ST"},
    {"name": "Imported Water", "code": "IW"},
    {"name": "Mixed", "code": "MX"},
]


class Command(BaseCommand):
    help = "Seed default water types"

    def handle(self, *args, **options):
        created_count = 0
        for wt in WATER_TYPES:
            _, created = WaterType.objects.get_or_create(
                code=wt["code"],
                defaults={"name": wt["name"]},
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {wt['name']} ({wt['code']}): {status}")
            if created:
                created_count += 1
        existing = len(WATER_TYPES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(WATER_TYPES)} water types ({created_count} created, {existing} existing)"
            )
        )
