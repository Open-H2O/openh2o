"""
Seed realistic data for the Kaweah Subbasin (DWR Basin 5-022.11).

Uses real geography, real monitoring-station IDs, and representative
water-right holders from Tulare County. Designed to coexist with the
fictional Demo Valley GSA dataset.

Idempotent: skips creation if "Kaweah Subbasin" boundary already exists.
All Kaweah-specific records use the "KAW-" prefix for targeted cleanup.
"""
import json
import math
import os
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.models import (
    AllocationPlan,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterType,
)
from core.models import SiteConfig
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, ParcelZone, Zone
from measurements.models import Meter, MeterReading
from parcels.models import Parcel, ParcelLedger
from recharge.models import RechargeEvent, RechargeSite
from surface.models import (
    DiversionRecord,
    PointOfDiversion,
    WaterRight,
    WaterRightParcel,
    WaterRightType,
)
from wells.models import (
    MonitoringWell,
    Well,
    WellIrrigatedParcel,
    WellMeter,
    WellType,
)


def make_box(cx, cy, size=0.005):
    """Create a MultiPolygon rectangle centered on (cx, cy)."""
    half = size / 2
    ring = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


def make_field_parcel(cx, cy, size=0.005, seed_val=0):
    """Create a realistic agricultural parcel polygon.

    Uses PLSS-style grid with random irregularity to mimic
    real assessor parcels in the San Joaquin Valley.
    """
    rng = random.Random(seed_val)
    half = size / 2

    # Aspect ratio: most ag fields are wider than tall (E-W oriented)
    aspect = rng.uniform(0.6, 1.4)
    hw = half * max(aspect, 1.0)
    hh = half / max(aspect, 1.0)

    # Slight rotation (fields aren't always perfectly N-S aligned)
    angle = rng.uniform(-0.08, 0.08)  # radians, ~5 degrees max

    # Base corners with irregularity
    jitter = size * 0.08  # 8% edge jitter
    corners = [
        (cx - hw + rng.uniform(-jitter, jitter),
         cy - hh + rng.uniform(-jitter, jitter)),
        (cx + hw + rng.uniform(-jitter, jitter),
         cy - hh + rng.uniform(-jitter, jitter)),
        (cx + hw + rng.uniform(-jitter, jitter),
         cy + hh + rng.uniform(-jitter, jitter)),
        (cx - hw + rng.uniform(-jitter, jitter),
         cy + hh + rng.uniform(-jitter, jitter)),
    ]

    # Sometimes add a 5th or 6th point (canal cut, road jog)
    if rng.random() < 0.3:
        edge = rng.randint(0, 3)
        next_edge = (edge + 1) % 4
        mid_x = (corners[edge][0] + corners[next_edge][0]) / 2
        mid_y = (corners[edge][1] + corners[next_edge][1]) / 2
        inward_x = (cx - mid_x) * 0.15
        inward_y = (cy - mid_y) * 0.15
        corners.insert(edge + 1, (mid_x + inward_x, mid_y + inward_y))

    # Apply rotation around center
    if abs(angle) > 0.01:
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        rotated = []
        for px, py in corners:
            dx, dy = px - cx, py - cy
            rotated.append(
                (cx + dx * cos_a - dy * sin_a,
                 cy + dx * sin_a + dy * cos_a)
            )
        corners = rotated

    # Close the ring
    corners.append(corners[0])

    return MultiPolygon(Polygon(corners))


class Command(BaseCommand):
    help = (
        "Seed data for the Kaweah Subbasin (DWR Basin 5-022.11) using "
        "real geography and monitoring stations. "
        "Idempotent: skips if 'Kaweah Subbasin' already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing Kaweah data before seeding.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()

        # Idempotency check
        if Boundary.objects.filter(name="Kaweah Subbasin").exists():
            self.stdout.write(
                self.style.WARNING(
                    "Kaweah data already exists (Kaweah Subbasin found). "
                    "Use --flush to recreate."
                )
            )
            return

        with transaction.atomic():
            self._seed()

    def _flush(self):
        """Remove all Kaweah data using KAW- prefix for targeted deletion."""
        self.stdout.write("Flushing existing Kaweah data...")
        boundary = Boundary.objects.filter(name="Kaweah Subbasin").first()
        if boundary:
            zone_ids = boundary.zones.values_list("id", flat=True)
            parcels = Parcel.objects.filter(parcel_number__startswith="KAW-APN-")
            parcel_ids = list(parcels.values_list("id", flat=True))

            # Ledger entries, account-parcel links, well-parcel links
            ParcelLedger.objects.filter(parcel_id__in=parcel_ids).delete()
            WaterAccountParcel.objects.filter(parcel_id__in=parcel_ids).delete()
            WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids).delete()

            # Wells and meters linked to Kaweah
            wells = Well.objects.filter(
                well_registration_id__startswith="KAW-W-"
            )
            well_ids = list(wells.values_list("id", flat=True))
            meter_ids = list(
                WellMeter.objects.filter(well_id__in=well_ids)
                .values_list("meter_id", flat=True)
            )
            MeterReading.objects.filter(meter_id__in=meter_ids).delete()
            WellMeter.objects.filter(well_id__in=well_ids).delete()
            MonitoringWell.objects.filter(well_id__in=well_ids).delete()
            Meter.objects.filter(id__in=meter_ids).delete()
            wells.delete()

            # Allocation plans referencing Kaweah zones
            AllocationPlan.objects.filter(zone_id__in=zone_ids).delete()

            # Accounts
            WaterAccount.objects.filter(
                account_number__startswith="KAW-ACCT-"
            ).delete()

            # Report submissions referencing Kaweah periods (PROTECT FK)
            from reporting.models import ReportSubmission

            kaweah_periods = ReportingPeriod.objects.filter(
                name__in=["WY 2024-2025", "WY 2025-2026"]
            )
            ReportSubmission.objects.filter(
                reporting_period__in=kaweah_periods
            ).delete()
            # Only delete WY 2025-2026 (WY 2024-2025 may be shared with demo)
            ReportingPeriod.objects.filter(name="WY 2025-2026").delete()

            # Water rights
            WaterRight.objects.filter(right_id__startswith="KAW-WR-").delete()

            # Recharge sites
            RechargeSite.objects.filter(name__startswith="Kaweah ").delete()
            RechargeSite.objects.filter(name__startswith="Rocky Ford").delete()
            RechargeSite.objects.filter(name__startswith="Exeter ").delete()
            RechargeSite.objects.filter(name__startswith="Terminus ").delete()

            # Monitored stations (Kaweah-specific)
            kaweah_station_ids = [
                "TRM", "KWR", "VIS",  # CDEC
                "11210100", "11208730",  # USGS
                "54",  # CIMIS
                "KAW-GWL-01", "KAW-GWL-02",  # DWR WDL
            ]
            MonitoredStation.objects.filter(
                external_station_id__in=kaweah_station_ids
            ).delete()

            # Parcels and zones (cascade handles ParcelZone)
            parcels.delete()
            boundary.delete()

            # SiteConfig (only if it's the Kaweah one)
            SiteConfig.objects.filter(
                agency_name="Kaweah Subbasin GSA"
            ).delete()

            self.stdout.write(self.style.SUCCESS("  Flushed."))
        else:
            self.stdout.write("  No Kaweah data found.")

    def _seed(self):
        random.seed(42)  # Reproducible data

        # ----------------------------------------------------------------
        # 1. SiteConfig (singleton: leave alone if one exists)
        # ----------------------------------------------------------------
        self.stdout.write("Checking site configuration...")
        if not SiteConfig.objects.exists():
            SiteConfig.objects.create(
                agency_name="Kaweah Subbasin GSA",
                timezone="America/Los_Angeles",
                native_srid=4326,
                contact_email="info@kaweahgsa.example.com",
                contact_phone="(559) 555-0200",
            )
            self.stdout.write("  Created SiteConfig for Kaweah Subbasin GSA.")
        else:
            self.stdout.write("  SiteConfig already exists, skipping.")

        # ----------------------------------------------------------------
        # 2. Water types
        # ----------------------------------------------------------------
        self.stdout.write("Ensuring water types...")
        gw, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )
        sw, _ = WaterType.objects.get_or_create(
            code="SW", defaults={"name": "Surface Water"}
        )
        rw, _ = WaterType.objects.get_or_create(
            code="RW", defaults={"name": "Recycled Water"}
        )
        storm, _ = WaterType.objects.get_or_create(
            code="ST", defaults={"name": "Stormwater"}
        )

        # ----------------------------------------------------------------
        # 3. Well types
        # ----------------------------------------------------------------
        self.stdout.write("Ensuring well types...")
        ag_well_type, _ = WellType.objects.get_or_create(
            name="Agricultural",
            defaults={"description": "Agricultural irrigation well"},
        )
        muni_well_type, _ = WellType.objects.get_or_create(
            name="Municipal",
            defaults={"description": "Municipal supply well"},
        )
        mon_well_type, _ = WellType.objects.get_or_create(
            name="Monitoring",
            defaults={"description": "Groundwater monitoring well"},
        )
        dom_well_type, _ = WellType.objects.get_or_create(
            name="Domestic",
            defaults={"description": "Domestic supply well"},
        )

        # ----------------------------------------------------------------
        # 4. Kaweah Subbasin Boundary (real DWR Basin 5-022.11)
        # ----------------------------------------------------------------
        self.stdout.write("Creating Kaweah Subbasin boundary...")
        data_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'data', 'kaweah',
        )
        geojson_path = os.path.join(data_dir, 'subbasin_boundary.geojson')
        with open(geojson_path) as f:
            subbasin_data = json.load(f)
        feature = subbasin_data['features'][0]
        boundary_geom = GEOSGeometry(json.dumps(feature['geometry']))
        if boundary_geom.geom_type == 'Polygon':
            boundary_geom = MultiPolygon(boundary_geom)

        boundary = Boundary.objects.create(
            name="Kaweah Subbasin",
            description=(
                "DWR Basin 5-022.11 in Tulare County, part of the "
                "San Joaquin Valley Groundwater Basin. Critically "
                "overdrafted under SGMA."
            ),
            geometry=boundary_geom,
            area_sq_miles=Decimal("706.0"),
        )

        # ----------------------------------------------------------------
        # 5. Management Zones (3 real GSA boundaries)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 3 GSA management zones...")
        gsa_path = os.path.join(data_dir, 'gsa_boundaries.geojson')
        with open(gsa_path) as f:
            gsa_data = json.load(f)

        zones = []
        for gsa_feature in gsa_data['features']:
            gsa_name = gsa_feature['properties'].get('GSA_Name', 'Unknown GSA')
            zone_geom = GEOSGeometry(json.dumps(gsa_feature['geometry']))
            if zone_geom.geom_type == 'Polygon':
                zone_geom = MultiPolygon(zone_geom)
            z = Zone.objects.create(
                name=gsa_name,
                boundary=boundary,
                geometry=zone_geom,
                zone_type="management_area",
                description=(
                    f"Groundwater Sustainability Agency boundary "
                    f"for {gsa_name}"
                ),
            )
            zones.append(z)

        # ----------------------------------------------------------------
        # 6. Wells (25 total)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 25 wells...")

        well_configs = [
            # (name, type, depth_ft, capacity_gpm, status, lon, lat)
            # 15 Agricultural
            ("Avenue 196 Well", ag_well_type, 450, 1800, "active", -119.42, 36.30),
            ("Road 148 Well", ag_well_type, 380, 1500, "active", -119.38, 36.35),
            ("Avenue 232 Well", ag_well_type, 520, 2200, "active", -119.35, 36.25),
            ("Road 168 Well", ag_well_type, 400, 1600, "active", -119.44, 36.38),
            ("Avenue 216 Well", ag_well_type, 350, 2000, "active", -119.32, 36.32),
            ("Road 132 Well", ag_well_type, 480, 1900, "active", -119.40, 36.20),
            ("Goshen Avenue Well", ag_well_type, 300, 1400, "active", -119.48, 36.28),
            ("Caldwell Avenue Well", ag_well_type, 550, 2500, "active", -119.30, 36.22),
            ("Lovers Lane Well", ag_well_type, 420, 1700, "active", -119.36, 36.40),
            ("Noble Avenue Well", ag_well_type, 360, 1300, "active", -119.46, 36.33),
            ("Houston Avenue Well", ag_well_type, 500, 2100, "active", -119.28, 36.26),
            ("Packwood Creek Well", ag_well_type, 280, 1200, "inactive", -119.34, 36.18),
            ("Ben Maddox Well", ag_well_type, 440, 1850, "active", -119.29, 36.36),
            ("Whitendale Avenue Well", ag_well_type, 390, 1550, "active", -119.43, 36.42),
            ("St Johns Well", ag_well_type, 470, 2300, "inactive", -119.37, 36.16),
            # 5 Monitoring
            ("Mineral King Mon-1", mon_well_type, 250, 50, "active", -119.15, 36.38),
            ("Woodlake Mon-2", mon_well_type, 300, 80, "active", -119.10, 36.42),
            ("Ivanhoe Mon-3", mon_well_type, 220, 60, "active", -119.22, 36.40),
            ("Tulare Mon-4", mon_well_type, 350, 100, "active", -119.35, 36.17),
            ("Farmersville Mon-5", mon_well_type, 280, 75, "active", -119.20, 36.30),
            # 3 Domestic
            ("Lemon Cove Domestic", dom_well_type, 200, 150, "active", -119.08, 36.38),
            ("Cutler Domestic", dom_well_type, 250, 200, "active", -119.28, 36.32),
            ("Orosi Domestic", dom_well_type, 230, 180, "inactive", -119.12, 36.44),
            # 2 Municipal
            ("Visalia Municipal #1", muni_well_type, 600, 500, "active", -119.30, 36.33),
            ("Exeter Municipal #1", muni_well_type, 550, 450, "active", -119.14, 36.30),
        ]

        wells = []
        for i, (wname, wtype, depth, cap, status, lon, lat) in enumerate(well_configs):
            well = Well.objects.create(
                well_registration_id=f"KAW-W-{i + 1:03d}",
                name=wname,
                well_type=wtype,
                location=Point(lon, lat),
                depth_ft=Decimal(str(depth)),
                capacity_gpm=Decimal(str(cap)),
                status=status,
                owner_name=f"Kaweah Well Owner {i + 1}",
            )
            wells.append(well)

        # Create MonitoringWell records for the 5 monitoring wells (index 15-19)
        for i in range(15, 20):
            MonitoringWell.objects.create(
                well=wells[i],
                monitoring_agency="Kaweah Delta WCD",
                measurement_frequency="monthly",
            )

        # ----------------------------------------------------------------
        # 7. Parcels (40 total, scattered within real boundary)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 40 parcels...")
        all_parcels = []
        parcels_by_zone = {z.pk: [] for z in zones}

        def assign_zone(pt_geom):
            """Return the zone whose geometry contains the point, or
            fall back to the first zone."""
            for zone in zones:
                if zone.geometry.contains(pt_geom):
                    return zone
            return zones[0]

        # Load real Tulare County parcel geometries
        parcel_path = os.path.join(data_dir, 'tulare_parcels_sample.geojson')
        with open(parcel_path) as f:
            parcel_data = json.load(f)

        for i, pfeat in enumerate(parcel_data['features']):
            props = pfeat['properties']
            parcel_geom = GEOSGeometry(json.dumps(pfeat['geometry']))
            if parcel_geom.geom_type == 'Polygon':
                parcel_geom = MultiPolygon(parcel_geom)

            apn_raw = props.get('APN_TXT', f'{i+1:09d}')
            acres_raw = props.get('GROW_AC') or props.get('TOT_ACRES')
            area = Decimal(str(round(float(acres_raw), 2))) if acres_raw else Decimal("40.0")
            use_desc = props.get('USEDSCRP', '')

            p = Parcel.objects.create(
                parcel_number=f"KAW-APN-{i + 1:03d}",
                owner_name=use_desc or "Agricultural",
                area_acres=area,
                geometry=parcel_geom,
                status="active",
            )
            zone = assign_zone(p.geometry.centroid)
            ParcelZone.objects.create(parcel=p, zone=zone)
            all_parcels.append(p)
            parcels_by_zone[zone.pk].append(p)

        # ----------------------------------------------------------------
        # 8. WellIrrigatedParcel links (ag wells to nearby parcels)
        # ----------------------------------------------------------------
        self.stdout.write("Linking agricultural wells to parcels...")
        ag_wells = wells[:15]
        wip_count = 0
        for i, well in enumerate(ag_wells):
            # Link to 1-3 parcels, picking from the same zone
            zone = assign_zone(well.location)
            zone_parcels = parcels_by_zone[zone.pk]
            if not zone_parcels:
                continue
            num_links = random.randint(1, min(3, len(zone_parcels)))
            linked = random.sample(zone_parcels, num_links)
            fraction = Decimal(str(round(1.0 / num_links, 4)))
            for parcel in linked:
                WellIrrigatedParcel.objects.create(
                    well=well, parcel=parcel, fraction=fraction,
                )
                wip_count += 1

        # ----------------------------------------------------------------
        # 9. Meters and readings (15 production wells)
        # ----------------------------------------------------------------
        self.stdout.write("Creating meters and readings for 15 production wells...")
        production_wells = wells[:15]
        reading_count = 0
        for i, well in enumerate(production_wells):
            meter = Meter.objects.create(
                serial_number=f"KAW-MTR-{i + 1:03d}",
                meter_type="totalizer",
                unit="acre_feet",
                manufacturer="McCrometer" if i % 2 == 0 else "Badger",
                status="active",
            )
            WellMeter.objects.create(
                well=well,
                meter=meter,
                installed_date=date(2023, 1, 1),
                is_current=True,
            )

            # Monthly readings for 12 months (Oct 2024 - Sep 2025)
            cumulative = Decimal("0.0")
            for month_offset in range(12):
                month_num = ((10 + month_offset - 1) % 12) + 1  # Oct=10..Sep=9
                year = 2024 if month_num >= 10 else 2025
                reading_dt = datetime(year, month_num, 15, 12, 0, 0,
                                     tzinfo=timezone.utc)

                # Seasonal pattern: higher May-Sep, lower Nov-Mar
                if month_num in (5, 6, 7, 8, 9):
                    volume = Decimal(str(round(random.uniform(100, 500), 2)))
                else:
                    volume = Decimal(str(round(random.uniform(10, 50), 2)))

                prev_val = cumulative
                cumulative += volume

                MeterReading.objects.create(
                    meter=meter,
                    reading_date=reading_dt,
                    previous_value=prev_val,
                    current_value=cumulative,
                    calculated_volume=volume,
                )
                reading_count += 1

        # ----------------------------------------------------------------
        # 10. Monitored Stations (10 total)
        # ----------------------------------------------------------------
        self.stdout.write("Creating monitored stations...")
        station_count = 0

        # CDEC stations
        cdec = DataSource.objects.filter(code="cdec").first()
        if cdec:
            cdec_stations = [
                ("TRM", "Terminus Dam", 36.4167, -118.9833, ["15", "20"]),
                ("KWR", "Kaweah River below Terminus", 36.4050, -119.0167, ["20", "1"]),
                ("VIS", "Visalia", 36.3333, -119.2917, ["2"]),
            ]
            for ext_id, sname, lat, lon, params in cdec_stations:
                _, created = MonitoredStation.objects.get_or_create(
                    data_source=cdec,
                    external_station_id=ext_id,
                    defaults={
                        "station_name": sname,
                        "location": Point(lon, lat),
                        "parameters": params,
                        "is_active": True,
                    },
                )
                if created:
                    station_count += 1

        # USGS stations
        usgs = DataSource.objects.filter(code="usgs").first()
        if usgs:
            usgs_stations = [
                ("11210100", "Kaweah River at Three Rivers", 36.4367, -118.9044, ["00060"]),
                ("11208730", "Kaweah Terminus Dam outflow", 36.4150, -118.9900, ["00060"]),
            ]
            for ext_id, sname, lat, lon, params in usgs_stations:
                _, created = MonitoredStation.objects.get_or_create(
                    data_source=usgs,
                    external_station_id=ext_id,
                    defaults={
                        "station_name": sname,
                        "location": Point(lon, lat),
                        "parameters": params,
                        "is_active": True,
                    },
                )
                if created:
                    station_count += 1

        # CIMIS station
        cimis = DataSource.objects.filter(code="cimis").first()
        if cimis:
            _, created = MonitoredStation.objects.get_or_create(
                data_source=cimis,
                external_station_id="54",
                defaults={
                    "station_name": "Visalia",
                    "location": Point(-119.2903, 36.3322),
                    "parameters": ["ETo", "precip"],
                    "is_active": True,
                },
            )
            if created:
                station_count += 1

        # DWR/WDL groundwater stations
        dwr_wdl = DataSource.objects.filter(code="dwr_wdl").first()
        if dwr_wdl:
            wdl_stations = [
                ("KAW-GWL-01", "Kaweah Delta monitoring well 1", 36.3000, -119.3000),
                ("KAW-GWL-02", "Kaweah Delta monitoring well 2", 36.2500, -119.2000),
            ]
            for ext_id, sname, lat, lon in wdl_stations:
                _, created = MonitoredStation.objects.get_or_create(
                    data_source=dwr_wdl,
                    external_station_id=ext_id,
                    defaults={
                        "station_name": sname,
                        "location": Point(lon, lat),
                        "parameters": ["gwl"],
                        "is_active": True,
                    },
                )
                if created:
                    station_count += 1

        # ----------------------------------------------------------------
        # 11. Water Right Types and Water Rights (10 total)
        # ----------------------------------------------------------------
        self.stdout.write("Creating water right types and 10 water rights...")
        pre14_type, _ = WaterRightType.objects.get_or_create(
            code="PRE14",
            defaults={
                "name": "Pre-1914 Appropriative",
                "description": "Pre-1914 appropriative water right",
            },
        )
        approp_type, _ = WaterRightType.objects.get_or_create(
            code="POST14",
            defaults={
                "name": "Post-1914 Appropriative",
                "description": "Post-1914 appropriative water right",
            },
        )
        riparian_type, _ = WaterRightType.objects.get_or_create(
            code="RIP",
            defaults={
                "name": "Riparian",
                "description": "Riparian water right",
            },
        )

        right_configs = [
            # (right_id, type, holder, priority_date, face_value, source, status)
            # 4 pre-1914
            ("KAW-WR-001", pre14_type, "Kaweah Delta WCD",
             date(1872, 5, 1), 15000, "Kaweah River", "active"),
            ("KAW-WR-002", pre14_type, "Lindsay-Strathmore ID",
             date(1880, 3, 15), 8000, "Kaweah River", "active"),
            ("KAW-WR-003", pre14_type, "Lindmore ID",
             date(1895, 7, 10), 5000, "St. Johns River", "active"),
            ("KAW-WR-004", pre14_type, "Exeter ID",
             date(1910, 1, 20), 3000, "Kaweah River", "curtailed"),
            # 3 post-1914
            ("KAW-WR-005", approp_type, "Ivanhoe ID",
             date(1925, 6, 1), 2000, "Kaweah River", "active"),
            ("KAW-WR-006", approp_type, "Tulare ID",
             date(1938, 9, 15), 4000, "Mill Creek", "active"),
            ("KAW-WR-007", approp_type, "Kaweah Delta WCD",
             date(1952, 4, 1), 6000, "Kaweah River", "curtailed"),
            # 3 riparian (no priority date)
            ("KAW-WR-008", riparian_type, "Three Rivers Ranch",
             None, 500, "Kaweah River", "active"),
            ("KAW-WR-009", riparian_type, "Mineral King Ranch",
             None, 800, "Mill Creek", "active"),
            ("KAW-WR-010", riparian_type, "Yokohl Valley Ranch",
             None, 1200, "Yokohl Creek", "active"),
        ]

        water_rights = []
        for right_id, rtype, holder, pdate, face_val, source, status in right_configs:
            wr = WaterRight.objects.create(
                right_id=right_id,
                right_type=rtype,
                holder_name=holder,
                priority_date=pdate,
                face_value_acre_feet=Decimal(str(face_val)),
                status=status,
                source_name=source,
            )
            water_rights.append(wr)

        # ----------------------------------------------------------------
        # 12. Points of Diversion (1-2 per right)
        # ----------------------------------------------------------------
        self.stdout.write("Creating points of diversion...")
        pod_configs = [
            # (right_index, name, lon, lat, stream, max_cfs)
            (0, "Kaweah Main Diversion", -119.20, 36.40, "Kaweah River", 50.0),
            (0, "McKay Point Diversion", -119.18, 36.38, "Kaweah River", 30.0),
            (1, "Lindsay Canal Headgate", -119.12, 36.35, "Kaweah River", 25.0),
            (2, "St Johns Diversion", -119.25, 36.32, "St. Johns River", 15.0),
            (3, "Exeter Canal Intake", -119.14, 36.30, "Kaweah River", 12.0),
            (3, "Exeter South Fork Intake", -119.12, 36.28, "Kaweah River", 8.0),
            (4, "Ivanhoe Ditch Head", -119.22, 36.42, "Kaweah River", 10.0),
            (5, "Mill Creek Weir", -119.30, 36.20, "Mill Creek", 18.0),
            (6, "Kaweah Delta Main Canal", -119.22, 36.38, "Kaweah River", 35.0),
            (7, "Three Rivers Riparian", -119.06, 36.43, "Kaweah River", 5.0),
            (8, "Mill Creek Riparian", -119.08, 36.40, "Mill Creek", 4.0),
            (9, "Yokohl Creek Take", -119.10, 36.35, "Yokohl Creek", 6.0),
        ]

        pods = []
        for ri, pname, lon, lat, stream, max_cfs in pod_configs:
            pod = PointOfDiversion.objects.create(
                water_right=water_rights[ri],
                name=pname,
                location=Point(lon, lat),
                stream_name=stream,
                max_rate_cfs=Decimal(str(max_cfs)),
                status="active",
            )
            pods.append(pod)

        # ----------------------------------------------------------------
        # 13. WaterRightParcel links (nearby parcels)
        # ----------------------------------------------------------------
        self.stdout.write("Linking water rights to parcels...")
        wrp_count = 0
        for i, wr in enumerate(water_rights):
            # Pick 2-4 parcels for each right
            num_links = random.randint(2, min(4, len(all_parcels)))
            linked = random.sample(all_parcels, num_links)
            for parcel in linked:
                WaterRightParcel.objects.create(
                    water_right=wr, parcel=parcel,
                )
                wrp_count += 1

        # ----------------------------------------------------------------
        # 14. Reporting Periods
        # ----------------------------------------------------------------
        self.stdout.write("Creating reporting periods...")
        wy2025, _ = ReportingPeriod.objects.get_or_create(
            name="WY 2024-2025",
            defaults={
                "start_date": date(2024, 10, 1),
                "end_date": date(2025, 9, 30),
                "is_finalized": True,
            },
        )
        wy2026 = ReportingPeriod.objects.create(
            name="WY 2025-2026",
            start_date=date(2025, 10, 1),
            end_date=date(2026, 9, 30),
        )

        # ----------------------------------------------------------------
        # 15. Diversion Records (monthly, 12 months)
        # ----------------------------------------------------------------
        self.stdout.write("Creating diversion records...")
        div_count = 0
        for pod in pods:
            for month_offset in range(12):
                month_num = ((10 + month_offset - 1) % 12) + 1
                year = 2024 if month_num >= 10 else 2025
                month_date = date(year, month_num, 1)

                # Seasonal: higher Apr-Sep, near-zero Nov-Feb
                if month_num in (4, 5, 6, 7, 8, 9):
                    face_val = float(pod.water_right.face_value_acre_feet or 1000)
                    # Monthly diversion is ~50-80% of monthly share of face value
                    monthly_share = face_val / 6  # 6 irrigation months
                    volume = Decimal(str(round(
                        random.uniform(0.5, 0.8) * monthly_share, 2
                    )))
                elif month_num in (3, 10):
                    volume = Decimal(str(round(random.uniform(5, 50), 2)))
                else:
                    volume = Decimal(str(round(random.uniform(0, 5), 2)))

                rp = wy2025 if month_num >= 10 or month_num <= 9 else wy2026
                # Determine correct reporting period based on water year
                if year == 2024 and month_num >= 10:
                    rp = wy2025
                elif year == 2025 and month_num <= 9:
                    rp = wy2025

                DiversionRecord.objects.create(
                    point_of_diversion=pod,
                    reporting_period=rp,
                    month=month_date,
                    volume_acre_feet=volume,
                    diversion_type="direct_use",
                )
                div_count += 1

        # ----------------------------------------------------------------
        # 16. Recharge Sites (4)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 4 recharge sites...")
        recharge_configs = [
            # (name, type, lon, lat, capacity, operator)
            ("Kaweah Delta Spreading Grounds", "spreading_basin",
             -119.2800, 36.3100, Decimal("2000.0"), "Kaweah Delta WCD"),
            ("Rocky Ford Ditch Recharge", "streambed",
             -119.1500, 36.3600, Decimal("500.0"), "Kaweah Delta WCD"),
            ("Exeter Recharge Basin", "spreading_basin",
             -119.1410, 36.2960, Decimal("800.0"), "Exeter ID"),
            ("Terminus Dam ASR Well", "asr_well",
             -118.9900, 36.4100, Decimal("300.0"), "USACE / Kaweah Delta WCD"),
        ]

        recharge_sites = []
        for sname, stype, lon, lat, capacity, operator in recharge_configs:
            site_zone = assign_zone(Point(lon, lat))
            geom_size = 0.008 if stype == "spreading_basin" else 0.003
            site = RechargeSite.objects.create(
                name=sname,
                site_type=stype,
                location=Point(lon, lat),
                geometry=make_box(lon, lat, size=geom_size),
                capacity_acre_feet=capacity,
                status="active",
                operator=operator,
                zone=site_zone,
            )
            recharge_sites.append(site)

        # ----------------------------------------------------------------
        # 17. Recharge Events (2-4 per site, wet season Dec-Apr)
        # ----------------------------------------------------------------
        self.stdout.write("Creating recharge events...")
        recharge_event_count = 0
        for site in recharge_sites:
            num_events = random.randint(2, 4)
            for j in range(num_events):
                # Wet season months: Dec, Jan, Feb, Mar, Apr
                month = random.choice([12, 1, 2, 3, 4])
                year = 2024 if month == 12 else 2025
                start = date(year, month, random.randint(1, 15))
                duration = random.randint(7, 21)
                volume = Decimal(str(round(random.uniform(100, 2000), 2)))
                wt = random.choice([sw, storm])

                RechargeEvent.objects.create(
                    recharge_site=site,
                    start_date=start,
                    end_date=start + timedelta(days=duration),
                    volume_acre_feet=volume,
                    water_type=wt,
                    source_description=f"Wet-season flow to {site.name}",
                )
                recharge_event_count += 1

        # ----------------------------------------------------------------
        # 18. Water Accounts (10)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 10 water accounts...")
        account_configs = [
            ("KAW-ACCT-001", "Kaweah Delta WCD"),
            ("KAW-ACCT-002", "Lindsay-Strathmore ID"),
            ("KAW-ACCT-003", "Lindmore ID"),
            ("KAW-ACCT-004", "Exeter ID"),
            ("KAW-ACCT-005", "Ivanhoe ID"),
            ("KAW-ACCT-006", "Tulare Irrigation District"),
            ("KAW-ACCT-007", "Cutler-Orosi Joint Powers"),
            ("KAW-ACCT-008", "Woodlake Public Utility"),
            ("KAW-ACCT-009", "Farmersville Farms Co-op"),
            ("KAW-ACCT-010", "Three Rivers Land Trust"),
        ]
        accounts = []
        for acct_num, name in account_configs:
            acct = WaterAccount.objects.create(
                account_number=acct_num,
                name=name,
                status="active",
                contact_name=f"{name.split()[0]} Water Manager",
                contact_email=f"water@{name.split()[0].lower()}.example.com",
            )
            accounts.append(acct)

        # ----------------------------------------------------------------
        # 19. WaterAccountParcel links (3-5 parcels per account)
        # ----------------------------------------------------------------
        self.stdout.write("Linking accounts to parcels...")
        remaining_parcels = list(all_parcels)
        random.shuffle(remaining_parcels)
        wap_count = 0
        for acct in accounts:
            if not remaining_parcels:
                remaining_parcels = list(all_parcels)
                random.shuffle(remaining_parcels)
            num_links = random.randint(3, max(3, min(5, len(remaining_parcels))))
            for _ in range(num_links):
                if not remaining_parcels:
                    remaining_parcels = list(all_parcels)
                    random.shuffle(remaining_parcels)
                parcel = remaining_parcels.pop()
                WaterAccountParcel.objects.create(
                    water_account=acct,
                    parcel=parcel,
                    reporting_period=wy2025,
                )
                wap_count += 1

        # ----------------------------------------------------------------
        # 20. Allocation Plans (per zone per water type per period)
        # ----------------------------------------------------------------
        self.stdout.write("Creating allocation plans...")
        alloc_count = 0
        for zone in zones:
            for wtype, rate in [(gw, "2.5"), (sw, "1.5")]:
                for rp in [wy2025, wy2026]:
                    AllocationPlan.objects.create(
                        name=f"{zone.name} - {wtype.name} {rp.name}",
                        zone=zone,
                        water_type=wtype,
                        reporting_period=rp,
                        allocation_acre_feet=Decimal(rate) * Decimal("1000"),
                    )
                    alloc_count += 1

        # ----------------------------------------------------------------
        # 21. ParcelLedger entries (target 400+)
        # ----------------------------------------------------------------
        self.stdout.write("Creating parcel ledger entries...")
        entries = []

        for p in all_parcels:
            parcel_area = float(p.area_acres or 100)

            # --- Allocation entries (beginning of each period) ---
            for rp in [wy2025, wy2026]:
                alloc_amount = Decimal(str(round(parcel_area * 2.5, 2)))
                entries.append(
                    ParcelLedger(
                        parcel=p,
                        transaction_date=rp.start_date,
                        effective_date=rp.start_date,
                        amount_acre_feet=alloc_amount,
                        water_type=gw,
                        source_type="allocation",
                        description=f"Annual GW allocation for {rp.name}",
                        reporting_period=rp,
                    )
                )

            # --- Monthly meter_reading entries (negative, extraction) ---
            for month_offset in range(12):
                month_num = ((10 + month_offset - 1) % 12) + 1
                year = 2024 if month_num >= 10 else 2025
                month_date = date(year, month_num, 15)

                if month_num in (5, 6, 7, 8, 9):
                    extraction = Decimal(str(round(
                        random.uniform(0.3, 0.6) * parcel_area / 12, 2
                    )))
                else:
                    extraction = Decimal(str(round(
                        random.uniform(0.05, 0.15) * parcel_area / 12, 2
                    )))

                entries.append(
                    ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=-extraction,
                        water_type=gw,
                        source_type="meter_reading",
                        description="Monthly groundwater extraction",
                        reporting_period=wy2025,
                    )
                )

            # --- Monthly ET estimate entries (negative) ---
            for month_offset in range(12):
                month_num = ((10 + month_offset - 1) % 12) + 1
                year = 2024 if month_num >= 10 else 2025
                month_date = date(year, month_num, 20)

                if month_num in (5, 6, 7, 8, 9):
                    et = Decimal(str(round(
                        random.uniform(0.4, 0.7) * parcel_area / 12, 2
                    )))
                else:
                    et = Decimal(str(round(
                        random.uniform(0.02, 0.1) * parcel_area / 12, 2
                    )))

                entries.append(
                    ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=-et,
                        water_type=gw,
                        source_type="et_estimate",
                        description="Monthly ET consumption estimate",
                        reporting_period=wy2025,
                    )
                )

            # --- Surface diversion entries (positive, Apr-Sep only) ---
            for month_num in (4, 5, 6, 7, 8, 9):
                month_date = date(2025, month_num, 10)
                div_amount = Decimal(str(round(
                    random.uniform(0.1, 0.3) * parcel_area / 12, 2
                )))
                entries.append(
                    ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=div_amount,
                        water_type=sw,
                        source_type="surface_diversion",
                        description="Surface water delivery",
                        reporting_period=wy2025,
                    )
                )

        # --- Recharge entries (positive, one per recharge event) ---
        # Distribute recharge credit across parcels in same zone
        for site in recharge_sites:
            zone_parcels = parcels_by_zone.get(site.zone_id, [])
            if not zone_parcels:
                continue
            events = RechargeEvent.objects.filter(recharge_site=site)
            for event in events:
                credit_per_parcel = event.volume_acre_feet / len(zone_parcels)
                for p in zone_parcels[:5]:  # Credit top 5 parcels in zone
                    entries.append(
                        ParcelLedger(
                            parcel=p,
                            transaction_date=event.start_date,
                            effective_date=event.start_date,
                            amount_acre_feet=credit_per_parcel,
                            water_type=event.water_type or sw,
                            source_type="recharge",
                            description=f"Recharge credit from {site.name}",
                            reporting_period=wy2025,
                        )
                    )

        ParcelLedger.objects.bulk_create(entries, batch_size=500)

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        self.stdout.write(
            self.style.SUCCESS(
                f"\nKaweah Subbasin data seeded successfully:\n"
                f"  1 subbasin boundary\n"
                f"  {len(zones)} management zones\n"
                f"  {len(all_parcels)} parcels\n"
                f"  {len(wells)} wells ({wip_count} well-parcel links)\n"
                f"  {reading_count} meter readings\n"
                f"  {station_count} monitored stations\n"
                f"  {len(water_rights)} water rights ({len(pods)} points of diversion)\n"
                f"  {div_count} diversion records\n"
                f"  {len(recharge_sites)} recharge sites ({recharge_event_count} events)\n"
                f"  {len(accounts)} water accounts ({wap_count} account-parcel links)\n"
                f"  {alloc_count} allocation plans\n"
                f"  {len(entries)} ledger entries\n"
                f"  2 reporting periods"
            )
        )
