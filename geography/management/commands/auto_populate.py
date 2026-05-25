"""
Auto-populate geographic data for a boundary from public APIs.

Steps:
  basins    — DWR Bulletin 118 groundwater basins (Zone records)
  parcels   — LightBox parcel boundaries (not yet implemented)
  flowlines — NLDI flowlines (not yet implemented)

Usage:
  python manage.py auto_populate --boundary "Kaweah Subbasin"
  python manage.py auto_populate --boundary 1 --steps basins --dry-run
"""

import logging
from collections import OrderedDict

from django.core.management.base import BaseCommand, CommandError

from geography.models import Boundary

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Auto-populate geographic data (basins, parcels, flowlines) "
        "for a boundary from public APIs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--boundary",
            required=True,
            help="Name (case-insensitive) or numeric ID of the Boundary.",
        )
        parser.add_argument(
            "--steps",
            default=None,
            help=(
                "Comma-separated list of steps to run. "
                "Valid: basins, parcels, flowlines. Default: all."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        boundary = self._resolve_boundary(options["boundary"])
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no records will be created."))

        step_registry = OrderedDict([
            ("basins", self._step_basins),
            ("parcels", self._step_parcels),
            ("flowlines", self._step_flowlines),
        ])

        # Filter to requested steps
        requested = options["steps"]
        if requested:
            step_names = [s.strip() for s in requested.split(",")]
            invalid = [s for s in step_names if s not in step_registry]
            if invalid:
                raise CommandError(
                    f"Unknown steps: {', '.join(invalid)}. "
                    f"Valid: {', '.join(step_registry.keys())}"
                )
            step_registry = OrderedDict(
                (k, v) for k, v in step_registry.items() if k in step_names
            )

        self.stdout.write(
            f"Running {len(step_registry)} step(s) for boundary "
            f"'{boundary.name}' (ID {boundary.pk})..."
        )

        total_created = 0
        for step_name, step_fn in step_registry.items():
            self.stdout.write(f"\n--- Step: {step_name} ---")
            try:
                count = step_fn(boundary, dry_run)
                total_created += count
                self.stdout.write(
                    self.style.SUCCESS(f"  {step_name}: {count} record(s) created.")
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"  {step_name} failed: {exc}")
                )
                logger.exception("Step %s failed", step_name)

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. {total_created} total record(s) created.")
        )

    def _resolve_boundary(self, value):
        """Look up Boundary by numeric ID or name (case-insensitive)."""
        if value.isdigit():
            try:
                return Boundary.objects.get(pk=int(value))
            except Boundary.DoesNotExist:
                raise CommandError(f"No boundary found with ID {value}.")

        matches = Boundary.objects.filter(name__icontains=value)
        if matches.count() == 0:
            raise CommandError(f"No boundary found matching '{value}'.")
        if matches.count() > 1:
            names = ", ".join(m.name for m in matches[:5])
            raise CommandError(
                f"Multiple boundaries match '{value}': {names}. "
                "Use the numeric ID or a more specific name."
            )
        return matches.first()

    def _step_basins(self, boundary, dry_run):
        """Fetch DWR Bulletin 118 basins. (stub)"""
        self.stdout.write(self.style.WARNING("  basins: not yet implemented"))
        return 0

    def _step_parcels(self, boundary, dry_run):
        """Fetch parcel boundaries. (stub)"""
        self.stdout.write(self.style.WARNING("  parcels: not yet implemented"))
        return 0

    def _step_flowlines(self, boundary, dry_run):
        """Fetch NLDI flowlines. (stub)"""
        self.stdout.write(self.style.WARNING("  flowlines: not yet implemented"))
        return 0
