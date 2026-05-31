# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from datasync.models import DataRecordStaging, DataSyncLog
from health.models import HealthCheckResult


class Command(BaseCommand):
    help = "Prune old staging, health check, and sync log data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete (default is dry-run)",
        )
        parser.add_argument(
            "--staging-days",
            type=int,
            default=90,
            help="Days to keep published staging records (default: 90)",
        )
        parser.add_argument(
            "--health-days",
            type=int,
            default=365,
            help="Days to keep health check results (default: 365)",
        )
        parser.add_argument(
            "--sync-days",
            type=int,
            default=365,
            help="Days to keep sync logs (default: 365)",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        confirm = options["confirm"]

        staging_cutoff = now - timedelta(days=options["staging_days"])
        health_cutoff = now - timedelta(days=options["health_days"])
        sync_cutoff = now - timedelta(days=options["sync_days"])

        staging_qs = DataRecordStaging.objects.filter(
            status="published", created_at__lt=staging_cutoff
        )
        health_qs = HealthCheckResult.objects.filter(checked_at__lt=health_cutoff)
        sync_qs = DataSyncLog.objects.filter(started_at__lt=sync_cutoff)

        staging_count = staging_qs.count()
        health_count = health_qs.count()
        sync_count = sync_qs.count()

        total = staging_count + health_count + sync_count

        if not confirm:
            self.stdout.write(self.style.WARNING("DRY RUN (use --confirm to delete)"))
            self.stdout.write("")

        self.stdout.write(f"{'Data Type':<30} {'Count':<10} {'Cutoff Date'}")
        self.stdout.write("-" * 60)
        self.stdout.write(
            f"{'Published staging records':<30} {staging_count:<10} {staging_cutoff.date()}"
        )
        self.stdout.write(
            f"{'Health check results':<30} {health_count:<10} {health_cutoff.date()}"
        )
        self.stdout.write(
            f"{'Sync logs':<30} {sync_count:<10} {sync_cutoff.date()}"
        )
        self.stdout.write("-" * 60)
        self.stdout.write(f"{'Total':<30} {total}")
        self.stdout.write("")

        if confirm:
            if total == 0:
                self.stdout.write(self.style.SUCCESS("Nothing to delete."))
                return

            staging_deleted, _ = staging_qs.delete()
            health_deleted, _ = health_qs.delete()
            sync_deleted, _ = sync_qs.delete()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted: {staging_deleted} staging, {health_deleted} health, {sync_deleted} sync log records"
                )
            )
        else:
            if total > 0:
                self.stdout.write("Run with --confirm to delete these records.")
            else:
                self.stdout.write(self.style.SUCCESS("Nothing to prune."))
