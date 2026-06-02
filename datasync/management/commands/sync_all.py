# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sync all active data sources.

Usage:
    python manage.py sync_all
    python manage.py sync_all --mock
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

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

        failed = []
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
                failed.append(source.code)
                self.stdout.write(
                    self.style.ERROR(f"Failed to sync {source.code}: {exc}")
                )

        # Exit nonzero if any source failed, so the cron job's exit status
        # reflects reality and ntfy/monitoring can alert. Previously this command
        # swallowed every failure and always exited 0 — "all synced" and "all
        # failed" looked identical to cron.
        if failed:
            raise CommandError(
                f"{len(failed)} of {sources.count()} source(s) failed to sync: "
                f"{', '.join(failed)}"
            )

        self.stdout.write(self.style.SUCCESS("\nAll sources processed."))
