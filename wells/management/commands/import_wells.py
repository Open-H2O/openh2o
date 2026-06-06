# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports wells from a CSV or Shapefile.

Reads each record (deriving a Point location from lat/lon columns or geometry,
in SRID 4326), skips duplicates by well registration ID, and creates Well rows.
Run it to load an agency's well inventory; use --dry-run to preview without
writing to the database.
"""
import csv
import os

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wells.models import Well


class Command(BaseCommand):
    help = "Import wells from CSV or Shapefile."

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the input file (CSV or Shapefile).",
        )
        parser.add_argument(
            "--format",
            choices=["csv", "shapefile"],
            default=None,
            help="File format. Auto-detected from extension if not provided.",
        )
        parser.add_argument(
            "--name-field",
            default="WELL_NAME",
            help="Field name containing the well name (default: WELL_NAME).",
        )
        parser.add_argument(
            "--lat-field",
            default="LATITUDE",
            help="Field name containing latitude (CSV only, default: LATITUDE).",
        )
        parser.add_argument(
            "--lon-field",
            default="LONGITUDE",
            help="Field name containing longitude (CSV only, default: LONGITUDE).",
        )
        parser.add_argument(
            "--reg-id-field",
            default="WELL_REG_ID",
            help="Field name containing the well registration ID (default: WELL_REG_ID).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing to the database.",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        fmt = options["format"]
        name_field = options["name_field"]
        lat_field = options["lat_field"]
        lon_field = options["lon_field"]
        reg_id_field = options["reg_id_field"]
        dry_run = options["dry_run"]

        if not os.path.exists(file_path):
            raise CommandError(f"File not found: {file_path}")

        # Auto-detect format from extension
        if fmt is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".csv":
                fmt = "csv"
            elif ext == ".shp":
                fmt = "shapefile"
            else:
                raise CommandError(
                    f"Cannot detect format from extension '{ext}'. Use --format."
                )

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be written."))

        imported_count = 0
        duplicate_count = 0
        error_count = 0

        records = list(self._load_records(file_path, fmt, name_field, lat_field, lon_field, reg_id_field))

        with transaction.atomic():
            for idx, rec in enumerate(records, start=1):
                try:
                    name = rec.get("name") or ""
                    reg_id = rec.get("reg_id") or None
                    location = rec.get("location")

                    # Skip records with no coordinates
                    if location is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Record {idx}: missing coordinates — skipped."
                            )
                        )
                        error_count += 1
                        continue

                    # Fall back to reg_id or sequential name
                    if not name:
                        name = reg_id or f"Well {idx}"

                    # Duplicate detection by registration ID
                    if reg_id:
                        if Well.objects.filter(well_registration_id=reg_id).exists():
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  {name} (reg_id={reg_id}): duplicate — skipped."
                                )
                            )
                            duplicate_count += 1
                            continue

                    if not dry_run:
                        Well.objects.create(
                            name=name,
                            well_registration_id=reg_id,
                            location=location,
                        )
                    imported_count += 1

                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(f"  Record {idx}: error — {exc}")
                    )
                    error_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {imported_count} wells, {duplicate_count} duplicates skipped, {error_count} errors"
            )
        )

    def _load_records(self, file_path, fmt, name_field, lat_field, lon_field, reg_id_field):
        if fmt == "csv":
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get(name_field, "").strip()
                    reg_id = row.get(reg_id_field, "").strip() or None
                    location = None
                    try:
                        lat_raw = row.get(lat_field, "")
                        lon_raw = row.get(lon_field, "")
                        if lat_raw and lon_raw:
                            location = Point(float(lon_raw), float(lat_raw), srid=4326)
                    except (ValueError, TypeError):
                        pass
                    yield {"name": name, "reg_id": reg_id, "location": location}

        elif fmt == "shapefile":
            try:
                ds = DataSource(file_path)
            except Exception as exc:
                raise CommandError(f"Failed to open shapefile with GDAL: {exc}")

            layer = ds[0]
            for feature in layer:
                name_val = ""
                reg_id_val = None
                try:
                    name_val = str(feature[name_field].value).strip()
                except Exception:
                    pass
                try:
                    reg_id_val = str(feature[reg_id_field].value).strip() or None
                except Exception:
                    pass

                location = None
                try:
                    geom = feature.geom
                    if geom is not None:
                        # Use centroid if not already a point
                        if geom.geom_type.upper() == "POINT":
                            lon, lat = geom.coords[0], geom.coords[1]
                        else:
                            centroid = geom.centroid
                            lon, lat = centroid.coords[0], centroid.coords[1]
                        srid = geom.srid or 4326
                        pt = Point(lon, lat, srid=srid)
                        if srid != 4326:
                            pt.transform(4326)
                        location = pt
                except Exception:
                    pass

                yield {"name": name_val, "reg_id": reg_id_val, "location": location}
