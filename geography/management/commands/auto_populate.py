"""
Auto-populate geographic data for a boundary from public APIs.

Steps:
  basins    — DWR Bulletin 118 groundwater basins (Zone records)
  parcels   — DWR LightBox statewide parcel boundaries (Parcel records)
  flowlines — USGS 3DHP flowlines (Flowline records)
  stations  — CDEC/USGS/CIMIS monitoring stations (MonitoredStation records)

Usage:
  python manage.py auto_populate --boundary "Kaweah Subbasin"
  python manage.py auto_populate --boundary 1 --steps basins --dry-run
"""

import json
import logging
from collections import OrderedDict
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError

from datasync.adapters import get_adapter
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, Flowline, Zone
from geography.services.arcgis import (
    esri_polygon_to_geos,
    esri_polyline_to_geos,
    geos_to_esri_geometry,
    query_by_boundary,
    query_feature_server,
)
from parcels.models import Parcel

logger = logging.getLogger(__name__)

B118_BASINS_URL = (
    "https://gis.water.ca.gov/arcgis/rest/services/Geoscientific/"
    "i08_B118_CA_GroundwaterBasins/FeatureServer/0/query"
)

LIGHTBOX_PARCELS_URL = (
    "https://gis.water.ca.gov/arcgis/rest/services/Planning/"
    "i15_Parcels_Assessor_Lightbox/MapServer/0/query"
)

THREEDHP_FLOWLINES_URL = (
    "https://hydro.nationalmap.gov/arcgis/rest/services/"
    "3DHP_all/MapServer/50/query"
)


class Command(BaseCommand):
    help = (
        "Auto-populate geographic data (basins, parcels, flowlines, stations) "
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
                "Valid: basins, parcels, flowlines, stations. Default: all."
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
            ("stations", self._step_stations),
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
        """Fetch LightBox parcel boundaries that intersect the boundary.

        Queries DWR's statewide LightBox parcel MapServer page-by-page,
        creates Parcel records with APN and geometry. Idempotent: skips
        parcels whose APN already exists.
        """
        self.stdout.write("  Querying LightBox Parcels MapServer...")
        esri_geom = geos_to_esri_geometry(boundary.geometry)

        out_fields = "PARCEL_APN,SITE_ADDR,SITE_CITY,SITE_STATE,SITE_ZIP"
        created_total = 0
        page_num = 0

        try:
            pages = query_feature_server(
                LIGHTBOX_PARCELS_URL,
                geometry=esri_geom,
                geometry_type="esriGeometryPolygon",
                spatial_rel="esriSpatialRelIntersects",
                out_fields=out_fields,
                return_geometry=True,
                out_sr=4326,
                max_record_count=1500,
            )

            for features in pages:
                page_num += 1
                apn_map = {}
                for feat in features:
                    apn = (feat.get("attributes") or {}).get("PARCEL_APN")
                    if not apn or not str(apn).strip():
                        continue
                    apn = str(apn).strip()
                    if apn not in apn_map:
                        apn_map[apn] = feat

                if not apn_map:
                    self.stdout.write(f"  Page {page_num}: 0 valid parcels, skipping.")
                    continue

                existing_apns = set(
                    Parcel.objects.filter(
                        parcel_number__in=list(apn_map.keys())
                    ).values_list("parcel_number", flat=True)
                )

                new_parcels = []
                for apn, feat in apn_map.items():
                    if apn in existing_apns:
                        continue

                    attrs = feat.get("attributes") or {}
                    addr_parts = [
                        str(attrs.get("SITE_ADDR") or "").strip(),
                        str(attrs.get("SITE_CITY") or "").strip(),
                        str(attrs.get("SITE_STATE") or "").strip(),
                        str(attrs.get("SITE_ZIP") or "").strip(),
                    ]
                    address = ", ".join(p for p in addr_parts if p)

                    geom = None
                    esri_feat_geom = feat.get("geometry")
                    if esri_feat_geom:
                        try:
                            geom = esri_polygon_to_geos(esri_feat_geom)
                        except Exception as exc:
                            logger.warning("Bad geometry for %s: %s", apn, exc)

                    if geom is None:
                        self.stdout.write(
                            self.style.WARNING(f"  Skipping (no geometry): {apn}")
                        )
                        continue

                    new_parcels.append(
                        Parcel(
                            parcel_number=apn,
                            geometry=geom,
                            address=address,
                            status="active",
                        )
                    )

                if dry_run:
                    self.stdout.write(
                        f"  Page {page_num}: would create {len(new_parcels)} parcel(s)"
                    )
                    created_total += len(new_parcels)
                else:
                    created = Parcel.objects.bulk_create(
                        new_parcels, ignore_conflicts=True
                    )
                    created_total += len(created)
                    self.stdout.write(
                        f"  Page {page_num}: {len(created)} parcel(s) created "
                        f"({len(existing_apns)} existing skipped)"
                    )

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  API query failed: {exc}"))
            logger.exception("LightBox parcels API query failed")

        return created_total

    def _step_flowlines(self, boundary, dry_run):
        """Fetch USGS 3DHP flowlines that intersect the boundary.

        Queries the 3D Hydrography Program MapServer (layer 50)
        page-by-page, creates Flowline records. Idempotent via
        source_id+boundary uniqueness check.
        """
        self.stdout.write("  Querying USGS 3DHP Flowlines MapServer...")
        esri_geom = geos_to_esri_geometry(boundary.geometry)

        out_fields = "id3dhp,gnisidlabel,featuretypelabel,lengthkm,streamorder"
        created_total = 0
        page_num = 0

        try:
            pages = query_feature_server(
                THREEDHP_FLOWLINES_URL,
                geometry=esri_geom,
                geometry_type="esriGeometryPolygon",
                spatial_rel="esriSpatialRelIntersects",
                out_fields=out_fields,
                return_geometry=True,
                out_sr=4326,
                max_record_count=2500,
            )

            for features in pages:
                page_num += 1
                sid_map = {}
                for feat in features:
                    attrs = feat.get("attributes") or {}
                    sid = str(attrs.get("id3dhp") or "").strip()
                    if not sid:
                        continue
                    if sid not in sid_map:
                        sid_map[sid] = feat

                if not sid_map:
                    self.stdout.write(f"  Page {page_num}: 0 valid flowlines, skipping.")
                    continue

                existing_sids = set(
                    Flowline.objects.filter(
                        source_id__in=list(sid_map.keys()),
                        boundary=boundary,
                    ).values_list("source_id", flat=True)
                )

                new_flowlines = []
                for sid, feat in sid_map.items():
                    if sid in existing_sids:
                        continue

                    attrs = feat.get("attributes") or {}
                    geom = None
                    esri_feat_geom = feat.get("geometry")
                    if esri_feat_geom:
                        try:
                            geom = esri_polyline_to_geos(esri_feat_geom)
                        except Exception as exc:
                            logger.warning("Bad geometry for %s: %s", sid, exc)

                    if geom is None:
                        self.stdout.write(
                            self.style.WARNING(f"  Skipping (no geometry): {sid}")
                        )
                        continue

                    new_flowlines.append(
                        Flowline(
                            name=str(attrs.get("gnisidlabel") or "").strip(),
                            boundary=boundary,
                            feature_type=str(attrs.get("featuretypelabel") or "").strip(),
                            length_km=attrs.get("lengthkm"),
                            stream_order=attrs.get("streamorder"),
                            source_id=sid,
                            geometry=geom,
                        )
                    )

                if dry_run:
                    self.stdout.write(
                        f"  Page {page_num}: would create {len(new_flowlines)} flowline(s)"
                    )
                    created_total += len(new_flowlines)
                else:
                    created = Flowline.objects.bulk_create(
                        new_flowlines, ignore_conflicts=True
                    )
                    created_total += len(created)
                    self.stdout.write(
                        f"  Page {page_num}: {len(created)} flowline(s) created "
                        f"({len(existing_sids)} existing skipped)"
                    )

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  API query failed: {exc}"))
            logger.exception("3DHP flowlines API query failed")

        return created_total

    def _step_stations(self, boundary, dry_run):
        """Discover monitoring stations from CDEC, USGS, and CIMIS.

        Creates inactive MonitoredStation records for user curation.
        Idempotent: skips stations that already exist (data_source + external_station_id).
        """
        source_codes = ["cdec", "usgs", "cimis"]
        use_mock = getattr(settings, "DATASYNC_MOCK_MODE", False)
        total_created = 0

        for code in source_codes:
            try:
                ds = DataSource.objects.filter(code=code).first()
                if ds is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  DataSource '{code}' not found, skipping."
                        )
                    )
                    continue

                adapter = get_adapter(code)
                if adapter is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No adapter registered for '{code}', skipping."
                        )
                    )
                    continue

                if use_mock:
                    station_list = self._load_mock_stations(code)
                else:
                    station_list = adapter.discover_stations(boundary.geometry)

                self.stdout.write(
                    f"  {code.upper()}: found {len(station_list)} station(s)."
                )

                created_count = 0
                for stn in station_list:
                    ext_id = str(stn.get("station_id", "")).strip()
                    if not ext_id:
                        continue

                    lat = stn.get("latitude")
                    lon = stn.get("longitude")
                    if lat is None or lon is None:
                        continue

                    if dry_run:
                        exists = MonitoredStation.objects.filter(
                            data_source=ds, external_station_id=ext_id
                        ).exists()
                        if not exists:
                            created_count += 1
                        continue

                    _, created = MonitoredStation.objects.get_or_create(
                        data_source=ds,
                        external_station_id=ext_id,
                        defaults={
                            "station_name": stn.get("name", ""),
                            "location": Point(
                                float(lon), float(lat), srid=4326
                            ),
                            "parameters": stn.get("parameters", []),
                            "is_active": False,
                        },
                    )
                    if created:
                        created_count += 1

                if dry_run:
                    self.stdout.write(
                        f"  {code.upper()}: would create {created_count} station(s)."
                    )
                else:
                    self.stdout.write(
                        f"  {code.upper()}: {created_count} station(s) created."
                    )
                total_created += created_count

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"  {code.upper()} station discovery failed: {exc}"
                    )
                )
                logger.exception("Station discovery failed for %s", code)

        return total_created

    def _load_mock_stations(self, source_code):
        """Load station list from fixture file for mock mode."""
        fixture_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "datasync"
            / "fixtures"
            / f"{source_code}.json"
        )
        if not fixture_path.exists():
            logger.warning("Mock fixture not found: %s", fixture_path)
            return []
        with open(fixture_path) as f:
            data = json.load(f)
        return data.get("stations", [])
