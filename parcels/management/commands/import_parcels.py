# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports parcels from GeoJSON or a Shapefile.

Stages each feature into ParcelStaging (normalising geometry to SRID 4326 and
flagging duplicates), then promotes this run's pending rows into the Parcel
table. Run it to load a county/agency parcel layer; use --dry-run to preview
without writing Parcel rows.
"""
from __future__ import annotations

import os
from typing import Any

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from parcels.models import Parcel, ParcelStaging


class _PromotionRefused(Exception):
    """Raised inside the promotion transaction to roll every row back."""


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

        self._detect_format(file_path, fmt)

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be promoted."))

        layer = self._open_layer(file_path)
        staged_ids, staged_pending, staged_duplicate, staged_error = self._stage_features(
            layer, parcel_number_field
        )
        staged_error_outline = self._outline_refusals

        # Promote pending staging records to Parcel table
        imported_count = 0
        if not dry_run:
            if staged_error_outline:
                # One unreadable outline stops the whole import: nothing is
                # promoted, and every refused feature has been named above.
                imported_count = 0
            else:
                promoted, failed = self._promote_staged(staged_ids, owner_field)
                imported_count += promoted
                staged_error += failed
        else:
            # Would-be count: a real run with a refused outline imports none.
            imported_count = 0 if staged_error_outline else staged_pending

        # Clear this run's staging scratch so the table can't accumulate
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

    def _detect_format(self, file_path: str, fmt: str | None) -> str:
        """Return the explicit format, or the one the file extension implies."""
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
        return fmt

    def _open_layer(self, file_path: str) -> Any:
        """Open the file with GDAL and return its first layer."""
        try:
            ds = DataSource(file_path)
        except Exception as exc:
            raise CommandError(f"Failed to open file with GDAL: {exc}")

        return ds[0]

    def _stage_features(
        self, layer: Any, parcel_number_field: str
    ) -> tuple[list[int], int, int, int]:
        """Stage every feature; return (staged ids, pending, duplicate, error counts)."""
        staged_pending = 0
        staged_duplicate = 0
        staged_error = 0
        self._outline_refusals = 0
        # Track the staging rows THIS invocation creates, so promotion
        # is scoped to this run (never a leftover `pending` row from an aborted
        # earlier import) and so this run can clear its own scratch afterward.
        staged_ids: list[int] = []

        for line, feature in enumerate(layer, start=1):
            parcel_number = None
            try:
                # Extract parcel number
                try:
                    # A null value is a missing number, not the text "None".
                    value = feature[parcel_number_field].value
                    parcel_number = "" if value is None else str(value).strip()
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

                raw_data = self._feature_properties(layer, feature)
                geom = self._feature_geometry(feature, parcel_number)
                if geom is None:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Refused {parcel_number} (feature {line}): "
                            "its outline cannot be read."
                        )
                    )
                    staged_error += 1
                    self._outline_refusals += 1
                    continue

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

        return staged_ids, staged_pending, staged_duplicate, staged_error

    def _feature_properties(self, layer: Any, feature: Any) -> dict[str, Any]:
        """Return the feature's attribute values keyed by field name."""
        # Extract properties as dict
        raw_data: dict[str, Any] = {}
        for field_name in layer.fields:
            try:
                raw_data[field_name] = feature[field_name].value
            except Exception:
                raw_data[field_name] = None
        return raw_data

    def _feature_geometry(self, feature: Any, parcel_number: str) -> MultiPolygon | None:
        """Return the feature geometry as a 4326 MultiPolygon, or None if it cannot be read."""
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
                self.style.WARNING(f"  {parcel_number}: geometry error: {exc}.")
            )
        return geom

    def _promote_staged(self, staged_ids: list[int], owner_field: str) -> tuple[int, int]:
        """Create a Parcel for each pending row this run staged; return (imported, failed) counts."""
        imported_count = 0
        failed_count = 0
        # Promote ONLY the rows this invocation staged — not every
        # global `pending` row. A leftover `pending` row from an aborted
        # prior import must never be materialized by an unrelated later run.
        pending_qs = ParcelStaging.objects.filter(
            id__in=staged_ids, status="pending"
        )
        refused: list[str] = []
        try:
            with transaction.atomic():
                for staging in pending_qs:
                    try:
                        with transaction.atomic():
                            owner_name = staging.raw_data.get(owner_field, "") or ""
                            Parcel.objects.create(
                                parcel_number=staging.parcel_number,
                                owner_name=str(owner_name).strip(),
                                geometry=staging.geometry,
                                status="active",
                            )
                        imported_count += 1
                    except Exception as exc:
                        failed_count += 1
                        refused.append(staging.parcel_number)
                        self.stdout.write(
                            self.style.ERROR(
                                f"  Refused {staging.parcel_number}: {exc}"
                            )
                        )
                if failed_count:
                    raise _PromotionRefused
        except _PromotionRefused:
            self.stdout.write(
                self.style.ERROR(
                    "  Nothing was imported. Refused: " + ", ".join(refused) + "."
                )
            )
            return 0, failed_count
        now = timezone.now()
        pending_qs.update(status="imported", imported_at=now)
        return imported_count, failed_count
