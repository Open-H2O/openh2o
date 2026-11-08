# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports parcels from a map file.

Reads a .geojson, .json, .zip (one shapefile), .kml or a bare .shp through
core/geofiles.py, the reader the Import use areas page uses. Features that
carry the same parcel number are joined into one parcel whose outline holds
all of them. Stages each parcel into ParcelStaging (normalising geometry to
SRID 4326 and flagging duplicates), then promotes this run's pending rows into
the Parcel table. Run it to load a county/agency parcel layer; use --dry-run to
preview without writing Parcel rows. The dry run counts what a real run does.
"""
from __future__ import annotations

import os
from typing import Any

from django.apps import apps as django_apps
from django.contrib.gis.gdal import GDALException
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core import geofiles
from parcels import use_area_import
from parcels.models import Parcel, ParcelStaging


class _PromotionRefused(Exception):
    """Raised inside the promotion transaction to roll every row back."""


class Command(BaseCommand):
    help = "Import parcels from a GeoJSON, zipped shapefile, KML or shapefile into the staging table, then promote to Parcel."

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the input file (GeoJSON, zipped shapefile, KML or Shapefile).",
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
            "--headgate-field",
            default=None,
            help=(
                "The column that names each use area's headgate. The command reads the column "
                "HEADGATE unless you name another. Each value must be the local name of a point "
                "of diversion on the site. A point's name works too."
            ),
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
        headgate_given = options["headgate_field"] is not None
        headgate_field = options["headgate_field"] or "HEADGATE"

        if not os.path.exists(file_path):
            raise CommandError(f"File not found: {file_path}")

        self._detect_format(file_path, fmt)

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be promoted."))

        self._promotion_refused = False
        features = self._read_features(file_path)

        # Without the surface app the command ignores a headgate column, as it
        # ignores any other column; a column named on purpose is refused.
        headgates: dict[str, list[str]] = {}
        if django_apps.is_installed("surface"):
            # A column named on purpose that the file lacks is refused (row 33),
            # so a mistyped name never skips every link without a word.
            if headgate_given and not any(
                headgate_field in (feature.get("properties") or {}) for feature in features
            ):
                raise CommandError(
                    f"The file does not have a column named {headgate_field}. "
                    "Check the spelling against the file's first row."
                )
            headgates = self._headgates_in(features, parcel_number_field, headgate_field)
            if headgates:
                self._refuse_unknown_headgates(headgates)
        elif headgate_given:
            raise CommandError(
                "This site runs without OpenH2O's Surface Water pages. Add surface to "
                "OPENH2O_MODULES in .env to link use areas to headgates."
            )

        staged_ids, staged_pending, staged_duplicate, staged_error = self._stage_features(
            features, parcel_number_field
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

        # A refused outline or a refused promotion imported nothing, so no
        # link is made and no linking line is printed.
        linking = (
            bool(headgates)
            and not staged_error_outline
            and (dry_run or not self._promotion_refused)
        )
        linked = already = 0
        if linking:
            linked, already = self._link_headgates(headgates, dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {imported_count} parcels, {staged_duplicate} duplicates skipped, {staged_error} errors"
            )
        )
        if linking:
            self.stdout.write(self._linking_line(linked, already))

    def _detect_format(self, file_path: str, fmt: str | None) -> str:
        """Return the explicit format, or the one the file extension implies."""
        # Auto-detect format from extension
        if fmt is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".geojson", ".json"):
                fmt = "geojson"
            elif ext in (".shp", ".zip"):
                fmt = "shapefile"
            elif ext == ".kml":
                fmt = "kml"
            else:
                raise CommandError(
                    f"Cannot detect format from extension '{ext}'. Use --format."
                )
        return fmt

    def _read_features(self, file_path: str) -> list[dict[str, Any]]:
        """Read the file's features through core/geofiles.py.

        Refuses, in the page's own words, a zip that holds several shapefiles
        and coordinates that are not longitude and latitude.
        """
        try:
            features = geofiles.features_from_path(file_path)
        except GDALException as exc:
            raise CommandError(f"Failed to open file with GDAL: {exc}")
        except (ValueError, ImportError) as exc:
            raise CommandError(str(exc))
        try:
            geofiles.check_longitude_latitude(features)
        except ValueError as exc:
            raise CommandError(str(exc))
        return features

    def _stage_features(
        self, features: list[dict[str, Any]], parcel_number_field: str
    ) -> tuple[list[int], int, int, int]:
        """Stage every parcel; return (staged ids, pending, duplicate, error counts).

        Features that share a parcel number are one parcel whose outline holds
        all of them, so the counts are the same ones a real run produces.
        """
        staged_pending = 0
        staged_duplicate = 0
        staged_error = 0
        self._outline_refusals = 0
        # Track the staging rows THIS invocation creates, so promotion
        # is scoped to this run (never a leftover `pending` row from an aborted
        # earlier import) and so this run can clear its own scratch afterward.
        staged_ids: list[int] = []

        # parcel number -> the first feature's line and properties, and every outline
        parcels: dict[str, dict[str, Any]] = {}
        for line, feature in enumerate(features, start=1):
            properties = feature.get("properties") or {}
            # A null value is a missing number, not the text "None".
            value = properties.get(parcel_number_field)
            parcel_number = "" if value is None else str(value).strip()

            if not parcel_number:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping feature: missing or empty '{parcel_number_field}' field."
                    )
                )
                staged_error += 1
                continue

            outline = use_area_import.outline_of(feature.get("geometry"))
            if outline is None:
                self.stdout.write(
                    self.style.ERROR(
                        f"  Refused {parcel_number} (feature {line}): "
                        "its outline cannot be read."
                    )
                )
                staged_error += 1
                self._outline_refusals += 1
                continue

            parcel = parcels.get(parcel_number)
            if parcel is None:
                parcels[parcel_number] = {"properties": properties, "outlines": [outline]}
            else:
                parcel["outlines"].append(outline)

        for parcel_number, parcel in parcels.items():
            try:
                # Duplicate detection
                is_duplicate = Parcel.objects.filter(parcel_number=parcel_number).exists()
                status = "duplicate" if is_duplicate else "pending"

                staging_row = ParcelStaging.objects.create(
                    parcel_number=parcel_number,
                    raw_data=parcel["properties"],
                    geometry=use_area_import.joined(parcel["outlines"]),
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
            self._promotion_refused = True
            return 0, failed_count
        now = timezone.now()
        pending_qs.update(status="imported", imported_at=now)
        return imported_count, failed_count

    def _headgates_in(
        self, features: list[dict[str, Any]], parcel_number_field: str, headgate_field: str
    ) -> dict[str, list[str]]:
        """Return {parcel number: its headgate values}; empty when the file has no such column.

        A blank cell adds no value, so a use area with only blank cells is absent.
        """
        has_column = any(
            headgate_field in (feature.get("properties") or {}) for feature in features
        )
        if not has_column:
            return {}
        found: dict[str, list[str]] = {}
        for feature in features:
            properties = feature.get("properties") or {}
            number = properties.get(parcel_number_field)
            number = "" if number is None else str(number).strip()
            cell = properties.get(headgate_field)
            cell = "" if cell is None else str(cell).strip()
            if not number or not cell:
                continue
            values = found.setdefault(number, [])
            if cell not in values:
                values.append(cell)
        return found

    def _refuse_unknown_headgates(self, headgates: dict[str, list[str]]) -> None:
        """Name every value no point holds, then stop before anything is saved."""
        from surface.points import point_named

        missing = False
        for number, values in headgates.items():
            for value in values:
                if point_named(value) is None:
                    missing = True
                    self.stdout.write(
                        self.style.ERROR(
                            f"Use area {number}: OpenH2O did not find a point of diversion named '{value}'."
                        )
                    )
        if missing:
            raise CommandError(
                "The command did not import any use area. Add the missing points of diversion "
                "or correct the names in the file. Then run the command again."
            )

    def _link_headgates(self, headgates: dict[str, list[str]], dry_run: bool) -> tuple[int, int]:
        """Add the missing use area to headgate links; return (use areas linked, already linked).

        A link is made at the model's own default share, and an existing link
        is never touched.
        """
        from surface.models import PointOfDiversionParcel
        from surface.points import point_named

        on_site = {
            p.parcel_number: p
            for p in Parcel.objects.filter(parcel_number__in=list(headgates))
        }
        linked = already = 0
        with transaction.atomic():
            for number, values in headgates.items():
                parcel = on_site.get(number)
                added = False
                for value in values:
                    point = point_named(value)
                    if parcel is None:
                        # Dry run: the use area would be new, so its link would be too.
                        # A real run that did not save it has nothing to link.
                        added = added or dry_run
                        continue
                    if PointOfDiversionParcel.objects.filter(
                        point_of_diversion=point, parcel=parcel
                    ).exists():
                        continue
                    added = True
                    if not dry_run:
                        PointOfDiversionParcel.objects.create(
                            point_of_diversion=point, parcel=parcel
                        )
                if added:
                    linked += 1
                else:
                    already += 1
        return linked, already

    def _linking_line(self, linked: int, already: int) -> str:
        areas = "1 use area" if linked == 1 else f"{linked} use areas"
        line = f"OpenH2O linked {areas} to {'its headgate' if linked == 1 else 'their headgates'}."
        if already:
            if already == 1:
                line += " Another 1 use area in the file was already linked to its headgate."
            else:
                line += (
                    f" Another {already} use areas in the file were already linked to their headgates."
                )
        return line
