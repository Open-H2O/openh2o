# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that seeds the default Role reference rows.

An operator runs it during initial setup to populate the (currently dormant)
RBAC roles (admin, manager, viewer); it is idempotent via get_or_create, so
re-running leaves existing rows untouched.
"""
from django.core.management.base import BaseCommand

from core.models import Role

ROLES = [
    {"name": "admin", "description": "Full system access"},
    {"name": "manager", "description": "Manage parcels, wells, and accounts"},
    {"name": "viewer", "description": "Read-only access"},
]


class Command(BaseCommand):
    help = "Seed default roles"

    def handle(self, *args, **options):
        created_count = 0
        for role_data in ROLES:
            _, created = Role.objects.get_or_create(
                name=role_data["name"],
                defaults={"description": role_data["description"]},
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {role_data['name']}: {status}")
            if created:
                created_count += 1
        existing = len(ROLES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(ROLES)} roles ({created_count} created, {existing} existing)"
            )
        )
