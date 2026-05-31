# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Load California county boundaries from Census TIGERweb.

Queries the TIGERweb State_County MapServer for all counties in a given
state (default: California, FIPS 06) and creates Boundary records.
Idempotent: skips counties that already exist by name.

Usage:
  python manage.py load_counties
  python manage.py load_counties --dry-run
  python manage.py load_counties --state 06
"""

import logging

from django.core.management.base import BaseCommand

from geography.models import Boundary
from geography.services.arcgis import (
    esri_polygon_to_geos,
    query_feature_server,
)

logger = logging.getLogger(__name__)

TIGERWEB_COUNTIES_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/State_County/MapServer/1/query"
)


class Command(BaseCommand):
    help = "Load county boundaries from Census TIGERweb into the Boundary table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--state",
            default="06",
            help="State FIPS code (default: 06 for California).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        state_fips = options["state"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no records will be created."))

        self.stdout.write(f"Querying TIGERweb for state FIPS {state_fips} counties...")

        try:
            pages = query_feature_server(
                TIGERWEB_COUNTIES_URL,
                where=f"STATE='{state_fips}'",
                out_fields="NAME,GEOID,BASENAME",
                return_geometry=True,
                out_sr=4326,
                max_record_count=100,
            )

            created_count = 0
            for features in pages:
                for feat in features:
                    attrs = feat.get("attributes") or {}
                    basename = str(attrs.get("BASENAME") or attrs.get("NAME") or "").strip()
                    geoid = str(attrs.get("GEOID") or "").strip()

                    if not basename:
                        continue

                    county_name = f"{basename} County"

                    if Boundary.objects.filter(name=county_name).exists():
                        self.stdout.write(f"  Skipping (exists): {county_name}")
                        continue

                    esri_geom = feat.get("geometry")
                    if not esri_geom:
                        self.stdout.write(
                            self.style.WARNING(f"  Skipping (no geometry): {county_name}")
                        )
                        continue

                    try:
                        geom = esri_polygon_to_geos(esri_geom)
                    except Exception as exc:
                        self.stdout.write(
                            self.style.WARNING(f"  Skipping (bad geometry): {county_name}: {exc}")
                        )
                        continue

                    if geom is None:
                        self.stdout.write(
                            self.style.WARNING(f"  Skipping (empty geometry): {county_name}")
                        )
                        continue

                    if dry_run:
                        self.stdout.write(f"  Would create: {county_name} (FIPS {geoid})")
                    else:
                        Boundary.objects.create(
                            name=county_name,
                            description=f"California County (FIPS {geoid})",
                            geometry=geom,
                        )
                        self.stdout.write(f"  Created: {county_name}")
                        created_count += 1

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"API query failed: {exc}"))
            logger.exception("TIGERweb counties query failed")
            return

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. {created_count} county boundary(ies) created.")
        )
