# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Seed realistic data for the Kaweah Subbasin (DWR Basin 5-022.11).

Uses real geography, real monitoring-station IDs, and representative
water-right holders from Tulare County. Designed to coexist with the
fictional Demo Valley GSA dataset.

Idempotent: skips creation if "Kaweah Subbasin" boundary already exists.
All Kaweah-specific records use the "KAW-" prefix for targeted cleanup.
"""
import json
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
from core.management.commands.backfill_parcel_owners import KAWEAH_PARCEL_OWNERS
from core.models import SiteConfig
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, ParcelZone, Zone
from measurements.models import Meter, MeterReading, Sensor, SensorMeasurement
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation
from recharge.models import RechargeEvent, RechargeSite
from surface.models import (
    DiversionRecord,
    PointOfDiversion,
    PointOfDiversionParcel,
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

SEASONAL_WEIGHTS = {
    10: 0.05, 11: 0.03, 12: 0.02, 1: 0.02, 2: 0.02, 3: 0.04,
    4: 0.08, 5: 0.14, 6: 0.16, 7: 0.16, 8: 0.15, 9: 0.13,
}

CROP_CONFIGS = [
    ("Citrus", "CIT", "Orange, lemon, and grapefruit orchards"),
    ("Almonds", "ALM", "Almond orchards"),
    ("Alfalfa", "ALF", "Alfalfa hay production"),
    ("Corn", "CRN", "Field and silage corn"),
    ("Grapes", "GRP", "Table and wine grapes"),
    ("Pistachios", "PIS", "Pistachio orchards"),
]

ACCOUNT_PROFILES = [
    ("KAW-ACCT-001", "Kaweah Delta WCD", "large_over", 2.5, 1.35, 6),
    ("KAW-ACCT-002", "Lindsay-Strathmore ID", "large_over", 2.5, 1.25, 6),
    ("KAW-ACCT-003", "Lindmore ID", "mid", 2.0, 0.95, 5),
    ("KAW-ACCT-004", "Exeter ID", "mid", 2.0, 1.00, 5),
    ("KAW-ACCT-005", "Ivanhoe ID", "mid", 2.0, 1.05, 5),
    ("KAW-ACCT-006", "Tulare Irrigation District", "small_under", 1.8, 0.55, 3),
    ("KAW-ACCT-007", "Cutler-Orosi Joint Powers", "small_under", 1.8, 0.50, 3),
    ("KAW-ACCT-008", "Woodlake Public Utility", "small_under", 1.8, 0.60, 3),
    ("KAW-ACCT-009", "Farmersville Farms Co-op", "municipal", 3.0, 0.80, 2),
    ("KAW-ACCT-010", "Three Rivers Land Trust", "curtailed", 1.0, 0.25, 2),
]

AG_WELL_CONFIGS = [
    ("Avenue 196 Well", 450, 1800, "active"),
    ("Road 148 Well", 380, 1500, "active"),
    ("Avenue 232 Well", 520, 2200, "active"),
    ("Road 168 Well", 400, 1600, "active"),
    ("Avenue 216 Well", 350, 2000, "active"),
    ("Road 132 Well", 480, 1900, "active"),
    ("Goshen Avenue Well", 300, 1400, "active"),
    ("Caldwell Avenue Well", 550, 2500, "active"),
    ("Lovers Lane Well", 420, 1700, "active"),
    ("Noble Avenue Well", 360, 1300, "active"),
    ("Houston Avenue Well", 500, 2100, "active"),
    ("Packwood Creek Well", 280, 1200, "inactive"),
    ("Ben Maddox Well", 440, 1850, "active"),
    ("Whitendale Avenue Well", 390, 1550, "active"),
    ("St Johns Well", 470, 2300, "inactive"),
]


def make_box(cx, cy, size=0.005):
    half = size / 2
    ring = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


def dist_sq(a, b):
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy


MAX_LINK_DEG = 0.04  # ~2.7 miles at this latitude

def nearest_parcels(point, parcels, n, max_dist=None):
    ranked = sorted(parcels, key=lambda p: dist_sq(point, p.geometry.centroid))
    result = ranked[:min(n, len(ranked))]
    if max_dist is not None:
        limit_sq = max_dist * max_dist
        result = [p for p in result if dist_sq(point, p.geometry.centroid) <= limit_sq]
    return result


class Command(BaseCommand):
    help = "Seed data for Kaweah Subbasin (DWR Basin 5-022.11)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush", action="store_true",
            help="Delete existing Kaweah data before seeding.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()
        if Boundary.objects.filter(name="Kaweah Subbasin").exists():
            self.stdout.write(self.style.WARNING(
                "Kaweah data already exists. Use --flush to recreate."
            ))
            return
        with transaction.atomic():
            self._seed()

    def _flush(self):
        self.stdout.write("Flushing existing Kaweah data...")
        boundary = Boundary.objects.filter(name="Kaweah Subbasin").first()
        if not boundary:
            self.stdout.write("  No Kaweah data found.")
            return

        zone_ids = list(boundary.zones.values_list("id", flat=True))
        parcels = Parcel.objects.filter(parcel_number__startswith="KAW-APN-")
        parcel_ids = list(parcels.values_list("id", flat=True))

        ParcelLedger.objects.filter(parcel_id__in=parcel_ids).delete()
        WaterAccountParcel.objects.filter(parcel_id__in=parcel_ids).delete()
        WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids).delete()
        UsageLocation.objects.filter(parcel_id__in=parcel_ids).delete()

        wells = Well.objects.filter(well_registration_id__startswith="KAW-W-")
        well_ids = list(wells.values_list("id", flat=True))
        meter_ids = list(
            WellMeter.objects.filter(well_id__in=well_ids)
            .values_list("meter_id", flat=True)
        )
        MeterReading.objects.filter(meter_id__in=meter_ids).delete()
        WellMeter.objects.filter(well_id__in=well_ids).delete()
        MonitoringWell.objects.filter(well_id__in=well_ids).delete()
        Meter.objects.filter(id__in=meter_ids).delete()

        sensors = Sensor.objects.filter(serial_number__startswith="KAW-SNS-")
        SensorMeasurement.objects.filter(sensor__in=sensors).delete()
        sensors.delete()

        wells.delete()

        kaweah_wr_ids = list(
            WaterRight.objects.filter(right_id__startswith="KAW-WR-")
            .values_list("id", flat=True)
        )
        PointOfDiversion.objects.filter(
            water_right_id__in=kaweah_wr_ids
        ).delete()
        WaterRight.objects.filter(id__in=kaweah_wr_ids).delete()

        AllocationPlan.objects.filter(zone_id__in=zone_ids).delete()
        WaterAccount.objects.filter(
            account_number__startswith="KAW-ACCT-"
        ).delete()

        from reporting.models import ReportSubmission
        kaweah_periods = ReportingPeriod.objects.filter(
            name__in=["WY 2024-2025", "WY 2025-2026"]
        )
        ReportSubmission.objects.filter(
            reporting_period__in=kaweah_periods
        ).delete()
        ReportingPeriod.objects.filter(name="WY 2025-2026").delete()

        RechargeSite.objects.filter(name__startswith="Kaweah ").delete()
        RechargeSite.objects.filter(name__startswith="Rocky Ford").delete()
        RechargeSite.objects.filter(name__startswith="Exeter ").delete()
        RechargeSite.objects.filter(name__startswith="Terminus ").delete()

        MonitoredStation.objects.filter(external_station_id__in=[
            "TRM", "KWR", "VIS", "11210100", "11208730", "54",
            "KAW-GWL-01", "KAW-GWL-02",
        ]).delete()

        parcels.delete()
        boundary.delete()
        SiteConfig.objects.filter(agency_name="Kaweah Subbasin GSA").delete()
        self.stdout.write(self.style.SUCCESS("  Flushed."))

    def _seed(self):
        random.seed(42)
        data_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'data', 'kaweah',
        )

        def assign_zone(pt_geom):
            for zone in zones:
                if zone.geometry.contains(pt_geom):
                    return zone
            return zones[0]

        # ----------------------------------------------------------------
        # 1. SiteConfig
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
        WaterType.objects.get_or_create(
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
        # 4. Boundary (real DWR Basin 5-022.11)
        # ----------------------------------------------------------------
        self.stdout.write("Creating Kaweah Subbasin boundary...")
        with open(os.path.join(data_dir, 'subbasin_boundary.geojson')) as f:
            subbasin_data = json.load(f)
        boundary_geom = GEOSGeometry(
            json.dumps(subbasin_data['features'][0]['geometry'])
        )
        if boundary_geom.geom_type == 'Polygon':
            boundary_geom = MultiPolygon(boundary_geom)

        boundary = Boundary.objects.create(
            name="Kaweah Subbasin",
            description=(
                "Department of Water Resources Basin 5-022.11 in Tulare "
                "County, part of the San Joaquin Valley Groundwater Basin. "
                "Critically overdrafted under SGMA."
            ),
            geometry=boundary_geom,
            area_sq_miles=Decimal("706.0"),
        )

        # ----------------------------------------------------------------
        # 5. Management zones (3 real GSA boundaries)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 3 GSA management zones...")
        with open(os.path.join(data_dir, 'gsa_boundaries.geojson')) as f:
            gsa_data = json.load(f)

        zones = []
        for gsa_feature in gsa_data['features']:
            gsa_name = gsa_feature['properties'].get('GSA_Name', 'Unknown')
            zone_geom = GEOSGeometry(json.dumps(gsa_feature['geometry']))
            if zone_geom.geom_type == 'Polygon':
                zone_geom = MultiPolygon(zone_geom)
            z = Zone.objects.create(
                name=gsa_name, boundary=boundary, geometry=zone_geom,
                zone_type="management_area",
                description=f"GSA boundary for {gsa_name}",
            )
            zones.append(z)

        # ----------------------------------------------------------------
        # 6. Crop types
        # ----------------------------------------------------------------
        self.stdout.write("Ensuring crop types...")
        crops = []
        for crop_name, code, desc in CROP_CONFIGS:
            ct, _ = CropType.objects.get_or_create(
                code=code, defaults={"name": crop_name, "description": desc}
            )
            crops.append(ct)

        # ----------------------------------------------------------------
        # 7. Parcels (real Tulare County geometries)
        # ----------------------------------------------------------------
        self.stdout.write("Creating parcels from Tulare County GeoJSON...")
        with open(os.path.join(data_dir, 'tulare_parcels_sample.geojson')) as f:
            parcel_data = json.load(f)

        all_parcels = []
        parcels_by_zone = {z.pk: [] for z in zones}

        for i, pfeat in enumerate(parcel_data['features']):
            props = pfeat['properties']
            parcel_geom = GEOSGeometry(json.dumps(pfeat['geometry']))
            if parcel_geom.geom_type == 'Polygon':
                parcel_geom = MultiPolygon(parcel_geom)

            # The source parcels carry only a land-use class (USEDSCRP); the
            # crop is recorded on the UsageLocation below. owner_name gets a
            # realistic demo owner so the map/detail "Owner" reads truthfully.
            owner = KAWEAH_PARCEL_OWNERS[i % len(KAWEAH_PARCEL_OWNERS)]

            p = Parcel.objects.create(
                parcel_number=f"KAW-APN-{i + 1:03d}",
                owner_name=owner,
                geometry=parcel_geom, status="active",
            )
            zone = assign_zone(p.geometry.centroid)
            ParcelZone.objects.create(parcel=p, zone=zone)
            all_parcels.append(p)
            parcels_by_zone[zone.pk].append(p)

            crop = crops[i % len(crops)]
            UsageLocation.objects.create(
                parcel=p, name=f"{p.parcel_number} {crop.name}",
                crop_type=crop, area_acres=p.area_acres,
                geometry=p.geometry.centroid,
            )

        # ----------------------------------------------------------------
        # 8. Agricultural wells (placed at parcel centroids)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 15 agricultural wells at parcel centroids...")
        num_ag = len(AG_WELL_CONFIGS)
        step = max(1, len(all_parcels) // num_ag)
        host_indices = [
            min(i * step, len(all_parcels) - 1) for i in range(num_ag)
        ]

        wells = []
        for i, (wname, depth, cap, status) in enumerate(AG_WELL_CONFIGS):
            host = all_parcels[host_indices[i]]
            centroid = host.geometry.centroid
            well = Well.objects.create(
                well_registration_id=f"KAW-W-{i + 1:03d}",
                name=wname, well_type=ag_well_type,
                location=Point(
                    centroid.x + random.uniform(-0.002, 0.002),
                    centroid.y + random.uniform(-0.002, 0.002),
                ),
                depth_ft=Decimal(str(depth)),
                capacity_gpm=Decimal(str(cap)),
                status=status,
                owner_name=f"Kaweah Well Owner {i + 1}",
            )
            wells.append(well)

        # ----------------------------------------------------------------
        # 9. Non-agricultural wells (fixed coordinates)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 10 non-agricultural wells...")
        non_ag_configs = [
            ("Mineral King Mon-1", mon_well_type, 250, 50, "active",
             -119.15, 36.38),
            ("Woodlake Mon-2", mon_well_type, 300, 80, "active",
             -119.10, 36.42),
            ("Ivanhoe Mon-3", mon_well_type, 220, 60, "active",
             -119.22, 36.40),
            ("Tulare Mon-4", mon_well_type, 350, 100, "active",
             -119.35, 36.17),
            ("Farmersville Mon-5", mon_well_type, 280, 75, "active",
             -119.20, 36.30),
            ("Lemon Cove Domestic", dom_well_type, 200, 150, "active",
             -119.08, 36.38),
            ("Cutler Domestic", dom_well_type, 250, 200, "active",
             -119.28, 36.32),
            ("Orosi Domestic", dom_well_type, 230, 180, "inactive",
             -119.12, 36.44),
            ("Visalia Municipal #1", muni_well_type, 600, 500, "active",
             -119.30, 36.33),
            ("Exeter Municipal #1", muni_well_type, 550, 450, "active",
             -119.14, 36.30),
        ]
        for i, (wn, wt, dep, cap, st, lon, lat) in enumerate(non_ag_configs):
            well = Well.objects.create(
                well_registration_id=f"KAW-W-{num_ag + i + 1:03d}",
                name=wn, well_type=wt, location=Point(lon, lat),
                depth_ft=Decimal(str(dep)), capacity_gpm=Decimal(str(cap)),
                status=st,
                owner_name=f"Kaweah Well Owner {num_ag + i + 1}",
            )
            wells.append(well)

        for i in range(num_ag, num_ag + 5):
            MonitoringWell.objects.create(
                well=wells[i], monitoring_agency="Kaweah Delta WCD",
                measurement_frequency="monthly",
            )

        # ----------------------------------------------------------------
        # 10. WellIrrigatedParcel (proximity-based, not random)
        # ----------------------------------------------------------------
        self.stdout.write("Linking agricultural wells to nearest parcels...")
        ag_wells = wells[:num_ag]
        well_to_parcels = {}
        wip_count = 0
        for well in ag_wells:
            num_links = random.randint(1, 3)
            linked = nearest_parcels(well.location, all_parcels, num_links)
            fraction = Decimal(str(round(1.0 / len(linked), 4)))
            well_to_parcels[well.pk] = linked
            for parcel in linked:
                WellIrrigatedParcel.objects.create(
                    well=well, parcel=parcel, fraction=fraction,
                )
                wip_count += 1

        parcel_has_well = set()
        for linked in well_to_parcels.values():
            for p in linked:
                parcel_has_well.add(p.pk)

        # ----------------------------------------------------------------
        # 11. Meters (one per ag well; readings created later with ledger)
        # ----------------------------------------------------------------
        self.stdout.write("Creating meters for 15 production wells...")
        well_meters = {}
        for i, well in enumerate(ag_wells):
            meter = Meter.objects.create(
                serial_number=f"KAW-MTR-{i + 1:03d}",
                meter_type="totalizer", unit="acre_feet",
                manufacturer="McCrometer" if i % 2 == 0 else "Badger",
                status="active",
            )
            WellMeter.objects.create(
                well=well, meter=meter,
                installed_date=date(2023, 1, 1), is_current=True,
            )
            well_meters[well.pk] = meter

        # ----------------------------------------------------------------
        # 12. Sensors + measurements for 5 monitoring wells
        # ----------------------------------------------------------------
        self.stdout.write("Creating sensors for 5 monitoring wells...")
        sensor_count = 0
        seasonal_depth = {
            10: 4, 11: 2, 12: 0, 1: -2, 2: -4, 3: -5,
            4: -3, 5: 0, 6: 3, 7: 7, 8: 9, 9: 7,
        }
        for i, well in enumerate(wells[num_ag:num_ag + 5]):
            sensor = Sensor.objects.create(
                name=f"{well.name} Pressure Transducer",
                sensor_type="pressure_transducer",
                serial_number=f"KAW-SNS-{i + 1:03d}",
                well=well, location=well.location, status="active",
            )
            base_depth = 120 + i * 15
            for mo in range(12):
                mn = ((10 + mo - 1) % 12) + 1
                yr = 2024 if mn >= 10 else 2025
                depth = (base_depth + seasonal_depth[mn]
                         + random.uniform(-1.5, 1.5))
                SensorMeasurement.objects.create(
                    sensor=sensor,
                    measurement_date=datetime(
                        yr, mn, 15, 12, 0, 0, tzinfo=timezone.utc
                    ),
                    value=Decimal(str(round(depth, 2))),
                    unit="ft_bgs",
                )
                sensor_count += 1

        # ----------------------------------------------------------------
        # 13. Monitored stations (CDEC, USGS, CIMIS, DWR WDL)
        # ----------------------------------------------------------------
        self.stdout.write("Creating monitored stations...")
        station_count = 0

        cdec = DataSource.objects.filter(code="cdec").first()
        if cdec:
            for ext_id, sname, lat, lon, params in [
                ("TRM", "Terminus Dam", 36.4167, -118.9833, ["15", "20"]),
                ("KWR", "Kaweah River below Terminus",
                 36.4050, -119.0167, ["20", "1"]),
                ("VIS", "Visalia", 36.3333, -119.2917, ["2"]),
            ]:
                _, created = MonitoredStation.objects.get_or_create(
                    data_source=cdec, external_station_id=ext_id,
                    defaults={
                        "station_name": sname, "location": Point(lon, lat),
                        "parameters": params, "is_active": True,
                    },
                )
                if created:
                    station_count += 1

        usgs = DataSource.objects.filter(code="usgs").first()
        if usgs:
            for ext_id, sname, lat, lon, params in [
                ("11210100", "Kaweah River at Three Rivers",
                 36.4367, -118.9044, ["00060"]),
                ("11208730", "Kaweah Terminus Dam outflow",
                 36.4150, -118.9900, ["00060"]),
            ]:
                _, created = MonitoredStation.objects.get_or_create(
                    data_source=usgs, external_station_id=ext_id,
                    defaults={
                        "station_name": sname, "location": Point(lon, lat),
                        "parameters": params, "is_active": True,
                    },
                )
                if created:
                    station_count += 1

        cimis = DataSource.objects.filter(code="cimis").first()
        if cimis:
            _, created = MonitoredStation.objects.get_or_create(
                data_source=cimis, external_station_id="54",
                defaults={
                    "station_name": "Visalia",
                    "location": Point(-119.2903, 36.3322),
                    "parameters": ["ETo", "precip"], "is_active": True,
                },
            )
            if created:
                station_count += 1

        dwr_wdl = DataSource.objects.filter(code="dwr_wdl").first()
        if dwr_wdl:
            for ext_id, sname, lat, lon in [
                ("KAW-GWL-01", "Kaweah Delta monitoring well 1",
                 36.3000, -119.3000),
                ("KAW-GWL-02", "Kaweah Delta monitoring well 2",
                 36.2500, -119.2000),
            ]:
                _, created = MonitoredStation.objects.get_or_create(
                    data_source=dwr_wdl, external_station_id=ext_id,
                    defaults={
                        "station_name": sname, "location": Point(lon, lat),
                        "parameters": ["gwl"], "is_active": True,
                    },
                )
                if created:
                    station_count += 1

        # ----------------------------------------------------------------
        # 14. Water rights, PODs, PointOfDiversionParcel
        # ----------------------------------------------------------------
        self.stdout.write("Creating water rights and points of diversion...")
        pre14_type, _ = WaterRightType.objects.get_or_create(
            code="PRE14", defaults={
                "name": "Pre-1914 Appropriative",
                "description": "Pre-1914 appropriative water right",
            },
        )
        approp_type, _ = WaterRightType.objects.get_or_create(
            code="POST14", defaults={
                "name": "Post-1914 Appropriative",
                "description": "Post-1914 appropriative water right",
            },
        )
        riparian_type, _ = WaterRightType.objects.get_or_create(
            code="RIP", defaults={
                "name": "Riparian",
                "description": "Riparian water right",
            },
        )

        right_configs = [
            ("KAW-WR-001", pre14_type, "Kaweah Delta WCD",
             date(1872, 5, 1), 15000, "Kaweah River", "active"),
            ("KAW-WR-002", pre14_type, "Lindsay-Strathmore ID",
             date(1880, 3, 15), 8000, "Kaweah River", "active"),
            ("KAW-WR-003", pre14_type, "Lindmore ID",
             date(1895, 7, 10), 5000, "St. Johns River", "active"),
            ("KAW-WR-004", pre14_type, "Exeter ID",
             date(1910, 1, 20), 3000, "Kaweah River", "curtailed"),
            ("KAW-WR-005", approp_type, "Ivanhoe ID",
             date(1925, 6, 1), 2000, "Kaweah River", "active"),
            ("KAW-WR-006", approp_type, "Tulare ID",
             date(1938, 9, 15), 4000, "Mill Creek", "active"),
            ("KAW-WR-007", approp_type, "Kaweah Delta WCD",
             date(1952, 4, 1), 6000, "Kaweah River", "curtailed"),
            ("KAW-WR-008", riparian_type, "Three Rivers Ranch",
             None, 500, "Kaweah River", "active"),
            ("KAW-WR-009", riparian_type, "Mineral King Ranch",
             None, 800, "Mill Creek", "active"),
            ("KAW-WR-010", riparian_type, "Yokohl Valley Ranch",
             None, 1200, "Yokohl Creek", "active"),
        ]
        water_rights = []
        for rid, rtype, holder, pdate, fv, source, status in right_configs:
            wr = WaterRight.objects.create(
                right_id=rid, right_type=rtype, holder_name=holder,
                priority_date=pdate,
                face_value_acre_feet=Decimal(str(fv)),
                status=status, source_name=source,
            )
            water_rights.append(wr)

        pod_configs = [
            (0, "Kaweah Main Diversion", -119.20, 36.40,
             "Kaweah River", 50.0),
            (0, "McKay Point Diversion", -119.18, 36.38,
             "Kaweah River", 30.0),
            (1, "Lindsay Canal Headgate", -119.12, 36.35,
             "Kaweah River", 25.0),
            (2, "St Johns Diversion", -119.25, 36.32,
             "St. Johns River", 15.0),
            (3, "Exeter Canal Intake", -119.14, 36.30,
             "Kaweah River", 12.0),
            (3, "Exeter South Fork Intake", -119.12, 36.28,
             "Kaweah River", 8.0),
            (4, "Ivanhoe Ditch Head", -119.22, 36.42,
             "Kaweah River", 10.0),
            (5, "Mill Creek Weir", -119.30, 36.20,
             "Mill Creek", 18.0),
            (6, "Kaweah Delta Main Canal", -119.22, 36.38,
             "Kaweah River", 35.0),
            (7, "Three Rivers Riparian", -119.06, 36.43,
             "Kaweah River", 5.0),
            (8, "Mill Creek Riparian", -119.08, 36.40,
             "Mill Creek", 4.0),
            (9, "Yokohl Creek Take", -119.10, 36.35,
             "Yokohl Creek", 6.0),
        ]
        pods = []
        for ri, pname, lon, lat, stream, max_cfs in pod_configs:
            pod = PointOfDiversion.objects.create(
                water_right=water_rights[ri], name=pname,
                location=Point(lon, lat), stream_name=stream,
                max_rate_cfs=Decimal(str(max_cfs)), status="active",
            )
            pods.append(pod)

        self.stdout.write("Linking PODs to nearest parcels...")
        podp_count = 0
        for pod in pods:
            num_links = random.randint(2, 4)
            linked = nearest_parcels(
                pod.location, all_parcels, num_links,
                max_dist=MAX_LINK_DEG,
            )
            if not linked:
                continue
            fraction = Decimal(str(round(1.0 / len(linked), 4)))
            for parcel in linked:
                PointOfDiversionParcel.objects.create(
                    point_of_diversion=pod, parcel=parcel,
                    fraction=fraction,
                )
                podp_count += 1

        self.stdout.write("Linking water rights to parcels...")
        wrp_count = 0
        for wr in water_rights:
            wr_pods = [p for p in pods if p.water_right_id == wr.pk]
            ref_point = (wr_pods[0].location if wr_pods
                         else all_parcels[0].geometry.centroid)
            num_links = random.randint(2, min(4, len(all_parcels)))
            linked = nearest_parcels(ref_point, all_parcels, num_links)
            for parcel in linked:
                WaterRightParcel.objects.create(
                    water_right=wr, parcel=parcel,
                )
                wrp_count += 1

        # ----------------------------------------------------------------
        # 15. Reporting periods
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
        # 16. Diversion records (direct_use + to_storage for ~30% of PODs)
        # ----------------------------------------------------------------
        self.stdout.write("Creating diversion records...")
        storage_pod_set = set(random.sample(
            range(len(pods)), max(1, len(pods) * 30 // 100)
        ))
        div_count = 0
        for pod_idx, pod in enumerate(pods):
            for month_offset in range(12):
                month_num = ((10 + month_offset - 1) % 12) + 1
                year = 2024 if month_num >= 10 else 2025
                month_date = date(year, month_num, 1)

                face_val = float(
                    pod.water_right.face_value_acre_feet or 1000
                )
                if month_num in (4, 5, 6, 7, 8, 9):
                    monthly_share = face_val / 6
                    volume = Decimal(str(round(
                        random.uniform(0.5, 0.8) * monthly_share, 2
                    )))
                elif month_num in (3, 10):
                    volume = Decimal(str(round(
                        random.uniform(5, 50), 2
                    )))
                else:
                    volume = Decimal(str(round(
                        random.uniform(0, 5), 2
                    )))

                DiversionRecord.objects.create(
                    point_of_diversion=pod, reporting_period=wy2025,
                    month=month_date, volume_acre_feet=volume,
                    diversion_type="direct_use",
                )
                div_count += 1

                if (pod_idx in storage_pod_set
                        and month_num in (12, 1, 2, 3, 4)):
                    storage_vol = Decimal(str(round(
                        random.uniform(50, 500), 2
                    )))
                    DiversionRecord.objects.create(
                        point_of_diversion=pod, reporting_period=wy2025,
                        month=month_date, volume_acre_feet=storage_vol,
                        diversion_type="to_storage",
                    )
                    div_count += 1

        # ----------------------------------------------------------------
        # 17. Recharge sites + events
        # ----------------------------------------------------------------
        self.stdout.write("Creating 4 recharge sites...")
        recharge_configs = [
            ("Kaweah Delta Spreading Grounds", "spreading_basin",
             -119.2800, 36.3100, Decimal("2000.0"), "Kaweah Delta WCD"),
            ("Rocky Ford Ditch Recharge", "streambed",
             -119.1500, 36.3600, Decimal("500.0"), "Kaweah Delta WCD"),
            ("Exeter Recharge Basin", "spreading_basin",
             -119.1410, 36.2960, Decimal("800.0"), "Exeter ID"),
            ("Terminus Dam ASR Well", "asr_well",
             -118.9950, 36.4020, Decimal("300.0"),
             "USACE / Kaweah Delta WCD"),
        ]
        recharge_sites = []
        for sname, stype, lon, lat, capacity, operator in recharge_configs:
            site_zone = assign_zone(Point(lon, lat))
            geom_size = 0.008 if stype == "spreading_basin" else 0.003
            site = RechargeSite.objects.create(
                name=sname, site_type=stype,
                location=Point(lon, lat),
                geometry=make_box(lon, lat, size=geom_size),
                capacity_acre_feet=capacity,
                status="active", operator=operator, zone=site_zone,
            )
            recharge_sites.append(site)

        recharge_event_count = 0
        for site in recharge_sites:
            for _ in range(random.randint(2, 4)):
                month = random.choice([12, 1, 2, 3, 4])
                year = 2024 if month == 12 else 2025
                start = date(year, month, random.randint(1, 15))
                duration = random.randint(7, 21)
                volume = Decimal(str(round(random.uniform(100, 2000), 2)))
                wt = random.choice([sw, storm])
                RechargeEvent.objects.create(
                    recharge_site=site, start_date=start,
                    end_date=start + timedelta(days=duration),
                    volume_acre_feet=volume, water_type=wt,
                    source_description=f"Wet-season flow to {site.name}",
                )
                recharge_event_count += 1

        # ----------------------------------------------------------------
        # 18. Water accounts with narrative profiles
        # ----------------------------------------------------------------
        self.stdout.write("Creating 10 water accounts...")
        accounts = []
        account_parcel_map = {}
        remaining = list(all_parcels)
        random.shuffle(remaining)

        for acct_num, name, _, _, _, n_parcels in ACCOUNT_PROFILES:
            acct = WaterAccount.objects.create(
                account_number=acct_num, name=name, status="active",
                contact_name=f"{name.split()[0]} Water Manager",
                contact_email=(
                    f"water@{name.split()[0].lower()}.example.com"
                ),
            )
            accounts.append(acct)
            take = min(n_parcels, len(remaining))
            acct_parcels = remaining[:take]
            remaining = remaining[take:]
            account_parcel_map[acct_num] = acct_parcels
            for p in acct_parcels:
                WaterAccountParcel.objects.create(
                    water_account=acct, parcel=p,
                    reporting_period=wy2025,
                )

        for i, p in enumerate(remaining):
            idx = i % len(ACCOUNT_PROFILES)
            account_parcel_map[ACCOUNT_PROFILES[idx][0]].append(p)
            WaterAccountParcel.objects.create(
                water_account=accounts[idx], parcel=p,
                reporting_period=wy2025,
            )

        wap_count = sum(len(v) for v in account_parcel_map.values())

        # ----------------------------------------------------------------
        # 19. Allocation plans
        # ----------------------------------------------------------------
        self.stdout.write("Creating allocation plans...")
        alloc_count = 0
        for zone in zones:
            for wtype, rate in [(gw, "2.5"), (sw, "1.5")]:
                for rp in [wy2025, wy2026]:
                    AllocationPlan.objects.create(
                        name=f"{zone.name} - {wtype.name} {rp.name}",
                        zone=zone, water_type=wtype,
                        reporting_period=rp,
                        allocation_acre_feet=(
                            Decimal(rate) * Decimal("1000")
                        ),
                    )
                    alloc_count += 1

        # ----------------------------------------------------------------
        # 20. Ledger entries + meter readings (tied together)
        # ----------------------------------------------------------------
        self.stdout.write("Creating ledger entries and meter readings...")

        parcel_profile = {}
        for an, _, narrative, ar, em, _ in ACCOUNT_PROFILES:
            for p in account_parcel_map[an]:
                parcel_profile[p.pk] = (narrative, ar, em)

        month_schedule = []
        for mo in range(12):
            mn = ((10 + mo - 1) % 12) + 1
            yr = 2024 if mn >= 10 else 2025
            month_schedule.append((date(yr, mn, 15), mn))

        parcel_monthly = {}
        for p in all_parcels:
            narrative, alloc_rate, extract_mult = parcel_profile.get(
                p.pk, ("mid", 2.0, 1.0)
            )
            area = float(p.area_acres or 40)
            annual = area * alloc_rate * extract_mult
            vols = []
            for month_date, month_num in month_schedule:
                if narrative == "municipal":
                    weight = 1.0 / 12
                else:
                    weight = SEASONAL_WEIGHTS[month_num]
                vol = max(0.01, round(
                    annual * weight + random.uniform(-0.5, 0.5), 2
                ))
                vols.append((month_date, Decimal(str(vol))))
            parcel_monthly[p.pk] = vols

        reading_count = 0
        for well in ag_wells:
            meter = well_meters[well.pk]
            linked = well_to_parcels.get(well.pk, [])
            if not linked:
                continue
            cumulative = Decimal("0.0")
            for month_idx in range(12):
                month_date, month_num = month_schedule[month_idx]
                month_total = sum(
                    parcel_monthly[p.pk][month_idx][1] for p in linked
                )
                prev_val = cumulative
                cumulative += month_total
                MeterReading.objects.create(
                    meter=meter,
                    reading_date=datetime(
                        month_date.year, month_date.month, 15,
                        12, 0, 0, tzinfo=timezone.utc,
                    ),
                    previous_value=prev_val,
                    current_value=cumulative,
                    calculated_volume=month_total,
                )
                reading_count += 1

        entries = []
        for p in all_parcels:
            narrative, alloc_rate, _ = parcel_profile.get(
                p.pk, ("mid", 2.0, 1.0)
            )
            area = float(p.area_acres or 40)
            has_meter = p.pk in parcel_has_well

            for rp in [wy2025, wy2026]:
                alloc_amount = Decimal(str(round(area * alloc_rate, 2)))
                entries.append(ParcelLedger(
                    parcel=p,
                    transaction_date=rp.start_date,
                    effective_date=rp.start_date,
                    amount_acre_feet=alloc_amount,
                    water_type=gw, source_type="allocation",
                    description=f"Annual GW allocation for {rp.name}",
                    reporting_period=rp,
                ))

            for month_date, volume in parcel_monthly[p.pk]:
                entries.append(ParcelLedger(
                    parcel=p,
                    transaction_date=month_date,
                    effective_date=month_date,
                    amount_acre_feet=-volume,
                    water_type=gw,
                    source_type=(
                        "meter_reading" if has_meter else "et_estimate"
                    ),
                    description=(
                        "Monthly groundwater extraction"
                        if has_meter
                        else "Monthly ET consumption estimate"
                    ),
                    reporting_period=wy2025,
                ))

            for mo in range(12):
                mn = ((10 + mo - 1) % 12) + 1
                yr = 2024 if mn >= 10 else 2025
                et_date = date(yr, mn, 20)
                if mn in (5, 6, 7, 8, 9):
                    et = Decimal(str(round(
                        random.uniform(0.4, 0.7) * area / 12, 2
                    )))
                else:
                    et = Decimal(str(round(
                        random.uniform(0.02, 0.1) * area / 12, 2
                    )))
                entries.append(ParcelLedger(
                    parcel=p,
                    transaction_date=et_date,
                    effective_date=et_date,
                    amount_acre_feet=-et,
                    water_type=gw, source_type="et_estimate",
                    description="Monthly ET consumption estimate",
                    reporting_period=wy2025,
                ))

            for mn in (4, 5, 6, 7, 8, 9):
                month_date = date(2025, mn, 10)
                div_amount = Decimal(str(round(
                    random.uniform(0.1, 0.3) * area / 12, 2
                )))
                entries.append(ParcelLedger(
                    parcel=p,
                    transaction_date=month_date,
                    effective_date=month_date,
                    # Stored NEGATIVE — production convention shared by the calc
                    # engine and CSV importer. A delivery is still supply (the
                    # dashboard counts its magnitude as supply); the sign is the
                    # storage convention so the data round-trips through CSV.
                    amount_acre_feet=-div_amount,
                    water_type=sw, source_type="surface_diversion",
                    description="Surface water delivery",
                    reporting_period=wy2025,
                ))

        for site in recharge_sites:
            zone_parcels = parcels_by_zone.get(site.zone_id, [])
            if not zone_parcels:
                continue
            events = RechargeEvent.objects.filter(recharge_site=site)
            for event in events:
                credit = event.volume_acre_feet / len(zone_parcels)
                for p in zone_parcels[:5]:
                    entries.append(ParcelLedger(
                        parcel=p,
                        transaction_date=event.start_date,
                        effective_date=event.start_date,
                        amount_acre_feet=credit,
                        water_type=event.water_type or sw,
                        source_type="recharge",
                        description=(
                            f"Recharge credit from {site.name}"
                        ),
                        reporting_period=wy2025,
                    ))

        ParcelLedger.objects.bulk_create(entries, batch_size=500)

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        self.stdout.write(self.style.SUCCESS(
            f"\nKaweah Subbasin data seeded successfully:\n"
            f"  1 subbasin boundary\n"
            f"  {len(zones)} management zones\n"
            f"  {len(crops)} crop types\n"
            f"  {len(all_parcels)} parcels "
            f"({len(all_parcels)} usage locations)\n"
            f"  {len(wells)} wells "
            f"({wip_count} well-parcel links)\n"
            f"  {reading_count} meter readings\n"
            f"  {sensor_count} sensor measurements\n"
            f"  {station_count} monitored stations\n"
            f"  {len(water_rights)} water rights "
            f"({len(pods)} PODs, {podp_count} POD-parcel links)\n"
            f"  {wrp_count} water right-parcel links\n"
            f"  {div_count} diversion records\n"
            f"  {len(recharge_sites)} recharge sites "
            f"({recharge_event_count} events)\n"
            f"  {len(accounts)} water accounts "
            f"({wap_count} account-parcel links)\n"
            f"  {alloc_count} allocation plans\n"
            f"  {len(entries)} ledger entries\n"
            f"  2 reporting periods"
        ))
