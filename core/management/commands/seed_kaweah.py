"""
Seed realistic data for the Kaweah Subbasin (DWR Basin 5-022.11).

Uses real geography, real monitoring-station IDs, and representative
water-right holders from Tulare County. Designed to coexist with the
fictional Demo Valley GSA dataset.

Idempotent: skips creation if "Kaweah Subbasin" boundary already exists.
All Kaweah-specific records use the "KAW-" prefix for targeted cleanup.
"""
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
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
            MonitoredStation.objects.filter(
                external_station_id__startswith="KAW-GWL-"
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
            code="STORMWATER", defaults={"name": "Stormwater"}
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
        # 4. Kaweah Subbasin Boundary (~10 vertex polygon)
        # ----------------------------------------------------------------
        self.stdout.write("Creating Kaweah Subbasin boundary...")
        # Approximate DWR Basin 5-022.11 boundary
        # North: ~36.45 (Woodlake/Ivanhoe), South: ~36.15 (south of Tulare)
        # West: ~-119.50 (Goshen), East: ~-119.05 (foothills/Three Rivers)
        boundary_ring = [
            (-119.50, 36.25),   # SW corner (Goshen area)
            (-119.48, 36.15),   # South (south of Tulare)
            (-119.30, 36.15),   # South-central
            (-119.10, 36.18),   # SE corner (foothills)
            (-119.05, 36.28),   # East (near foothills)
            (-119.05, 36.40),   # NE (approaching Three Rivers)
            (-119.10, 36.45),   # North-east
            (-119.25, 36.45),   # North-central
            (-119.45, 36.43),   # NW (Ivanhoe area)
            (-119.50, 36.35),   # West
            (-119.50, 36.25),   # Close ring
        ]
        boundary = Boundary.objects.create(
            name="Kaweah Subbasin",
            description=(
                "DWR Basin 5-022.11 in Tulare County, part of the "
                "San Joaquin Valley Groundwater Basin. Critically "
                "overdrafted under SGMA."
            ),
            geometry=MultiPolygon(Polygon(boundary_ring)),
            area_sq_miles=Decimal("700.0"),
        )

        # ----------------------------------------------------------------
        # 5. Management Zones (2, split at -119.25 longitude)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 2 management zones...")
        west_zone_ring = [
            (-119.50, 36.15),
            (-119.25, 36.15),
            (-119.25, 36.45),
            (-119.50, 36.45),
            (-119.50, 36.15),
        ]
        east_zone_ring = [
            (-119.25, 36.15),
            (-119.05, 36.15),
            (-119.05, 36.45),
            (-119.25, 36.45),
            (-119.25, 36.15),
        ]

        west_zone = Zone.objects.create(
            name="Mid-Kaweah Management Area",
            boundary=boundary,
            geometry=MultiPolygon(Polygon(west_zone_ring)),
            zone_type="management_area",
            description="Western portion of Kaweah Subbasin (~60% of area)",
        )
        east_zone = Zone.objects.create(
            name="Eastern Kaweah Management Area",
            boundary=boundary,
            geometry=MultiPolygon(Polygon(east_zone_ring)),
            zone_type="management_area",
            description="Eastern portion of Kaweah Subbasin (~40% of area)",
        )
        zones = [west_zone, east_zone]

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
        # 7. Parcels (40 total)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 40 parcels...")
        all_parcels = []
        parcels_by_zone = {z.pk: [] for z in zones}

        # Parcel owner names for the Kaweah area
        kaweah_owners = [
            "Bravo Lake Ranch", "Valley Citrus Growers", "Kaweah Delta Farms",
            "Sequoia Ag Partners", "Tulare Basin Dairy", "Three Rivers Ranch",
            "Ivanhoe Farming Co", "Exeter Orchards LLC", "Woodlake Vineyards",
            "Sierra View Ranch", "Cutler-Orosi Ag", "Goshen Land Trust",
            "Visalia Farm Bureau", "Lindsay Olive Growers", "Lemon Cove Citrus",
            "Farmersville Dairy", "Mineral King Ranch", "St Johns River Farms",
            "Packwood Ag Corp", "Yokohl Valley Ranch",
        ]

        # 20 large parcels
        for i in range(20):
            size = random.uniform(0.015, 0.04)
            lon = random.uniform(-119.48, -119.07)
            lat = random.uniform(36.16, 36.44)
            zone = west_zone if lon < -119.25 else east_zone
            area = Decimal(str(random.randint(160, 640)))

            p = Parcel.objects.create(
                parcel_number=f"KAW-APN-{i + 1:03d}",
                owner_name=kaweah_owners[i % len(kaweah_owners)],
                area_acres=area,
                geometry=make_box(lon, lat, size),
                status="active",
            )
            ParcelZone.objects.create(parcel=p, zone=zone)
            all_parcels.append(p)
            parcels_by_zone[zone.pk].append(p)

        # 15 medium parcels
        for i in range(15):
            size = random.uniform(0.005, 0.015)
            lon = random.uniform(-119.48, -119.07)
            lat = random.uniform(36.16, 36.44)
            zone = west_zone if lon < -119.25 else east_zone
            area = Decimal(str(random.randint(40, 160)))

            p = Parcel.objects.create(
                parcel_number=f"KAW-APN-{i + 21:03d}",
                owner_name=kaweah_owners[(i + 5) % len(kaweah_owners)],
                area_acres=area,
                geometry=make_box(lon, lat, size),
                status="active",
            )
            ParcelZone.objects.create(parcel=p, zone=zone)
            all_parcels.append(p)
            parcels_by_zone[zone.pk].append(p)

        # 5 small parcels
        for i in range(5):
            size = random.uniform(0.002, 0.005)
            lon = random.uniform(-119.48, -119.07)
            lat = random.uniform(36.16, 36.44)
            zone = west_zone if lon < -119.25 else east_zone
            area = Decimal(str(random.randint(5, 40)))

            p = Parcel.objects.create(
                parcel_number=f"KAW-APN-{i + 36:03d}",
                owner_name=kaweah_owners[(i + 10) % len(kaweah_owners)],
                area_acres=area,
                geometry=make_box(lon, lat, size),
                status="active",
            )
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
            well_lon = well.location.x
            zone = west_zone if well_lon < -119.25 else east_zone
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
                reading_dt = datetime(year, month_num, 15, 12, 0, 0)

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
        cdec = DataSource.objects.filter(code="CDEC").first()
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
        usgs = DataSource.objects.filter(code="USGS").first()
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
        cimis = DataSource.objects.filter(code="CIMIS").first()
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
        dwr_wdl = DataSource.objects.filter(code="DWR_WDL").first()
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
            )
        )
