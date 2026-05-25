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

from geography.models import Boundary, Zone
from geography.services.arcgis import (
    esri_polygon_to_geos,
    query_by_boundary,
)

logger = logging.getLogger(__name__)

B118_BASINS_URL = (
    "https://gis.water.ca.gov/arcgis/rest/services/Geoscientific/"
    "i08_B118_CA_GroundwaterBasins/FeatureServer/0/query"
)


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
        """Fetch DWR Bulletin 118 groundwater basins that intersect the boundary.

        Creates Zone records with zone_type='subbasin' for each basin.
        Idempotent: skips basins that already exist for this boundary.
        """
        self.stdout.write("  Querying B118 FeatureServer...")
        try:
            features = query_by_boundary(B118_BASINS_URL, boundary.geometry)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  API query failed: {exc}"))
            logger.exception("B118 API query failed")
            return 0

        self.stdout.write(f"  Found {len(features)} basin(s) intersecting boundary.")

        created_count = 0
        for feature in features:
            attrs = feature.get("attributes", {})
            name = (
                attrs.get("Basin_Subbasin_Name")
                or attrs.get("Basin_Name")
                or "Unknown Basin"
            )
            number = attrs.get("Basin_Subbasin_Number", "")

            # Check for existing zone (idempotent)
            if Zone.objects.filter(name=name, boundary=boundary).exists():
                self.stdout.write(f"  Skipping (exists): {name}")
                continue

            # Convert geometry
            esri_geom = feature.get("geometry")
            if not esri_geom:
                self.stdout.write(
                    self.style.WARNING(f"  Skipping (no geometry): {name}")
                )
                continue

            try:
                geom = esri_polygon_to_geos(esri_geom)
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping (bad geometry): {name}: {exc}"
                    )
                )
                continue

            if geom is None:
                self.stdout.write(
                    self.style.WARNING(f"  Skipping (empty geometry): {name}")
                )
                continue

            if dry_run:
                self.stdout.write(f"  Would create: {name} ({number})")
            else:
                Zone.objects.create(
                    name=name,
                    boundary=boundary,
                    description=f"DWR Bulletin 118 Basin {number}",
                    geometry=geom,
                    zone_type="subbasin",
                )
                self.stdout.write(f"  Created: {name} ({number})")
                created_count += 1

        return created_count

    def _step_parcels(self, boundary, dry_run):
        """Fetch parcel boundaries. (stub)"""
        self.stdout.write(self.style.WARNING("  parcels: not yet implemented"))
        return 0

    def _step_flowlines(self, boundary, dry_run):
        """Fetch NLDI flowlines. (stub)"""
        self.stdout.write(self.style.WARNING("  flowlines: not yet implemented"))
        return 0
