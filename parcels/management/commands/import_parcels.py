# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from parcels.models import Parcel, ParcelStaging


class Command(BaseCommand):
    help = "Import parcels from GeoJSON or Shapefile into the staging table, then promote to Parcel."

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the input file (GeoJSON or Shapefile).",
        )
        parser.add_argument(
            "--format",
            choices=["geojson", "shapefile"],
            default=None,
            help="File format. Auto-detected from extension if not provided.",
        )
        parser.add_argument(
            "--parcel-number-field",
            default="APN",
            help="Field name in the source data containing the parcel number (default: APN).",
        )
        parser.add_argument(
            "--owner-field",
            default="OWNER",
            help="Field name in the source data containing the owner name (default: OWNER).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Stage records but do not promote to Parcel table. Reports what would happen.",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        fmt = options["format"]
        parcel_number_field = options["parcel_number_field"]
        owner_field = options["owner_field"]
        dry_run = options["dry_run"]

        if not os.path.exists(file_path):
            raise CommandError(f"File not found: {file_path}")

        # Auto-detect format from extension
        if fmt is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".geojson", ".json"):
                fmt = "geojson"
            elif ext in (".shp",):
                fmt = "shapefile"
            else:
                raise CommandError(
                    f"Cannot detect format from extension '{ext}'. Use --format."
                )

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be promoted."))

        staged_pending = 0
        staged_duplicate = 0
        staged_error = 0
        # ISS-030: track the staging rows THIS invocation creates, so promotion
        # is scoped to this run (never a leftover `pending` row from an aborted
        # earlier import) and so this run can clear its own scratch afterward.
        staged_ids = []

        try:
            ds = DataSource(file_path)
        except Exception as exc:
            raise CommandError(f"Failed to open file with GDAL: {exc}")

        layer = ds[0]

        for feature in layer:
            parcel_number = None
            try:
                # Extract parcel number
                try:
                    parcel_number = str(feature[parcel_number_field].value).strip()
                except Exception:
                    parcel_number = None

                if not parcel_number:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipping feature: missing or empty '{parcel_number_field}' field."
                        )
                    )
                    staged_error += 1
                    continue

                # Extract properties as dict
                raw_data = {}
                for field_name in layer.fields:
                    try:
                        raw_data[field_name] = feature[field_name].value
                    except Exception:
                        raw_data[field_name] = None

                # Extract and normalise geometry
                geom = None
                try:
                    geom_wkt = feature.geom.wkt
                    geos_geom = GEOSGeometry(geom_wkt, srid=feature.geom.srid or 4326)
                    # Transform to SRID 4326 if needed
                    if geos_geom.srid != 4326:
                        geos_geom.transform(4326)
                    # Wrap Polygon in MultiPolygon
                    if isinstance(geos_geom, Polygon):
                        geos_geom = MultiPolygon(geos_geom)
                    geom = geos_geom
                except Exception as exc:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {parcel_number}: geometry error — {exc}. Staging without geometry."
                        )
                    )

                # Duplicate detection
                is_duplicate = Parcel.objects.filter(parcel_number=parcel_number).exists()
                status = "duplicate" if is_duplicate else "pending"

                staging_row = ParcelStaging.objects.create(
                    parcel_number=parcel_number,
                    raw_data=raw_data,
                    geometry=geom,
                    status=status,
                )
                staged_ids.append(staging_row.id)

                if is_duplicate:
                    staged_duplicate += 1
                else:
                    staged_pending += 1

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"  Error processing feature (parcel '{parcel_number}'): {exc}"
                    )
                )
                staged_error += 1

        # Promote pending staging records to Parcel table
        imported_count = 0
        if not dry_run:
            # ISS-030: promote ONLY the rows this invocation staged — not every
            # global `pending` row. A leftover `pending` row from an aborted
            # prior import must never be materialized by an unrelated later run.
            pending_qs = ParcelStaging.objects.filter(
                id__in=staged_ids, status="pending"
            )
            with transaction.atomic():
                for staging in pending_qs:
                    try:
                        owner_name = staging.raw_data.get(owner_field, "") or ""
                        Parcel.objects.create(
                            parcel_number=staging.parcel_number,
                            owner_name=str(owner_name).strip(),
                            geometry=staging.geometry,
                            status="active",
                        )
                        staging.status = "imported"
                        staging.imported_at = timezone.now()
                        staging.save(update_fields=["status", "imported_at"])
                        imported_count += 1
                    except Exception as exc:
                        staging.status = "rejected"
                        staging.error_message = str(exc)
                        staging.save(update_fields=["status", "error_message"])
                        staged_error += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"  Failed to promote {staging.parcel_number}: {exc}"
                            )
                        )
        else:
            imported_count = staged_pending  # Would-be count

        # ISS-030: clear this run's staging scratch so the table can't accumulate
        # across imports or bleed a leftover row into a later run. Duplicate/error
        # diagnostics were already written to stdout above. Done for dry-run too —
        # a dry-run that left `pending` rows behind would be promoted by the next
        # real import.
        if staged_ids:
            ParcelStaging.objects.filter(id__in=staged_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {imported_count} parcels, {staged_duplicate} duplicates skipped, {staged_error} errors"
            )
        )
