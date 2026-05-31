# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sync all active data sources.

Usage:
    python manage.py sync_all
    python manage.py sync_all --mock
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from datasync.models import DataSource


class Command(BaseCommand):
    help = "Sync all active data sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mock", action="store_true",
            help="Force mock mode for all sources",
        )

    def handle(self, *args, **options):
        sources = DataSource.objects.filter(is_active=True).order_by("code")

        if not sources.exists():
            self.stdout.write(
                self.style.WARNING("No active data sources. Run seed_data_sources first.")
            )
            return

        self.stdout.write(f"Syncing {sources.count()} active data source(s)...")

        for source in sources:
            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(f"Source: {source.name} ({source.code})")
            self.stdout.write(f"{'=' * 60}")

            extra_args = []
            if options["mock"]:
                extra_args.append("--mock")

            try:
                call_command("sync_source", source.code, *extra_args, stdout=self.stdout)
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"Failed to sync {source.code}: {exc}")
                )

        self.stdout.write(self.style.SUCCESS("\nAll sources processed."))
