from django.core.management.base import BaseCommand

from surface.models import WaterRightType

WATER_RIGHT_TYPES = [
    {
        "name": "Pre-1914 Appropriative",
        "code": "PRE14",
        "description": "Rights established before the 1914 Water Commission Act",
    },
    {
        "name": "Post-1914 Appropriative",
        "code": "POST14",
        "description": "Permitted rights under SWRCB jurisdiction",
    },
    {
        "name": "Riparian",
        "code": "RIP",
        "description": "Rights tied to land adjacent to a natural watercourse",
    },
    {
        "name": "Pueblo",
        "code": "PUE",
        "description": "Municipal rights from Spanish/Mexican law",
    },
    {
        "name": "Federal Reserved",
        "code": "FED",
        "description": "Rights reserved by federal land designation",
    },
    {
        "name": "Statutory Small Domestic",
        "code": "SSD",
        "description": "Registrations for small domestic use under Water Code 1228",
    },
]


class Command(BaseCommand):
    help = "Seed default water right types"

    def handle(self, *args, **options):
        created_count = 0
        for wrt in WATER_RIGHT_TYPES:
            _, created = WaterRightType.objects.get_or_create(
                code=wrt["code"],
                defaults={"name": wrt["name"], "description": wrt["description"]},
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {wrt['name']} ({wrt['code']}): {status}")
            if created:
                created_count += 1
        existing = len(WATER_RIGHT_TYPES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(WATER_RIGHT_TYPES)} water right types ({created_count} created, {existing} existing)"
            )
        )
