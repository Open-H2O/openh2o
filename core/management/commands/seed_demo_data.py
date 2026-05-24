"""
Seed realistic demo data for a fictional California GSA.

Creates a complete dataset spanning geography, parcels, wells, meters,
water accounts, surface water rights, recharge sites, and ledger entries.
Idempotent: skips creation if "Demo Valley GSA" boundary already exists.
"""
import random
from datetime import date, timedelta
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
from surface.models import PointOfDiversion, WaterRight, WaterRightType
from wells.models import Well, WellIrrigatedParcel, WellMeter, WellType

# Center point: San Joaquin Valley, roughly near Madera, CA
CENTER_LON = -119.78
CENTER_LAT = 36.75

OWNER_NAMES = [
    "Johnson Family Trust",
    "Garcia Farms LLC",
    "Central Valley Agriculture",
    "Smith Ranch",
    "Westside Orchards",
    "Valley Dairy Co",
    "Sunrise Vineyards",
    "Oak Creek Ranch",
    "Delta Irrigation",
    "Hillside Farms",
    "Riverside Ag Corp",
    "Golden State Growers",
    "Pioneer Land Co",
    "Heritage Farms",
    "Valley View Ranch",
    "Madera Ag Partners",
    "Blue Sky Dairy",
    "Summit Orchards",
    "Foothill Farms",
    "Basin Water Co",
    "Sierra Land Trust",
    "Central Pumping",
    "Valley Floor Ag",
    "Eastside Growers",
    "Mesa Verde Ranch",
    "Adobe Creek Farm",
    "Lakeview Dairy",
    "Pacific Ag Inc",
    "Cedar Point Ranch",
    "Willow Springs Farm",
    "Cottonwood Farming",
    "Dry Creek Ag",
    "Granite Hills Ranch",
    "Riverbend Dairy",
    "Kern View Orchards",
    "Lone Oak Farms",
    "Sunflower Ranch",
    "North Fork Land Co",
    "Flat Rock Ag",
    "Twin Oaks Vineyards",
]

WELL_NAMES = [
    "Chowchilla Well",
    "Berenda Well",
    "Eastside Pump",
    "Cottonwood Well",
    "Ash Slough Well",
    "Daulton Well",
    "Road 400 Well",
    "Avenue 12 Well",
    "Firebaugh Well",
    "Highway 99 Well",
    "North Canal Well",
    "River Bottom Well",
    "Orchard Park Well",
    "Dairy Row Well",
    "Section Line Well",
]


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
        "Seed comprehensive demo data for a fictional California GSA. "
        "Idempotent: skips if 'Demo Valley GSA' already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing demo data before seeding.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()

        # Idempotency check
        if Boundary.objects.filter(name="Demo Valley GSA").exists():
            self.stdout.write(
                self.style.WARNING(
                    "Demo data already exists (Demo Valley GSA found). "
                    "Use --flush to recreate."
                )
            )
            return

        with transaction.atomic():
            self._seed()

    def _flush(self):
        """Remove all demo data by deleting the boundary (cascades)."""
        self.stdout.write("Flushing existing demo data...")
        boundary = Boundary.objects.filter(name="Demo Valley GSA").first()
        if boundary:
            # Delete objects that reference demo parcels/zones but don't cascade
            zone_ids = boundary.zones.values_list("id", flat=True)
            parcels = Parcel.objects.filter(
                parcel_zones__zone_id__in=zone_ids
            )
            parcel_ids = list(parcels.values_list("id", flat=True))

            # Ledger entries, account-parcel links, well-parcel links
            ParcelLedger.objects.filter(parcel_id__in=parcel_ids).delete()
            WaterAccountParcel.objects.filter(parcel_id__in=parcel_ids).delete()
            WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids).delete()

            # Wells and meters linked to demo parcels
            well_ids = WellIrrigatedParcel.objects.filter(
                parcel_id__in=parcel_ids
            ).values_list("well_id", flat=True)
            meter_ids = WellMeter.objects.filter(
                well_id__in=well_ids
            ).values_list("meter_id", flat=True)
            MeterReading.objects.filter(meter_id__in=meter_ids).delete()
            WellMeter.objects.filter(well_id__in=well_ids).delete()
            Meter.objects.filter(id__in=meter_ids).delete()
            Well.objects.filter(id__in=well_ids).delete()

            # Allocation plans referencing demo zones
            AllocationPlan.objects.filter(zone_id__in=zone_ids).delete()

            # Accounts that only have demo parcels
            demo_accounts = WaterAccount.objects.filter(
                account_number__startswith="DEMO-"
            )
            demo_accounts.delete()

            # Report submissions referencing demo periods (PROTECT FK)
            from reporting.models import ReportSubmission
            demo_periods = ReportingPeriod.objects.filter(name__startswith="WY ")
            ReportSubmission.objects.filter(reporting_period__in=demo_periods).delete()

            # Reporting periods
            demo_periods.delete()

            # Water rights
            WaterRight.objects.filter(right_id__startswith="DEMO-").delete()

            # Recharge sites
            RechargeSite.objects.filter(name__startswith="Demo ").delete()

            # Parcels and zones (cascade handles ParcelZone)
            parcels.delete()
            boundary.delete()

            # SiteConfig
            SiteConfig.objects.filter(agency_name="Demo Valley GSA").delete()

            self.stdout.write(self.style.SUCCESS("  Flushed."))
        else:
            self.stdout.write("  No demo data found.")

    def _seed(self):
        random.seed(42)  # Reproducible demo data

        # ----------------------------------------------------------------
        # 1. SiteConfig
        # ----------------------------------------------------------------
        self.stdout.write("Creating site configuration...")
        SiteConfig.objects.get_or_create(
            agency_name="Demo Valley GSA",
            defaults={
                "timezone": "America/Los_Angeles",
                "native_srid": 4326,
                "contact_email": "info@demovalleygsa.example.com",
                "contact_phone": "(559) 555-0100",
            },
        )

        # ----------------------------------------------------------------
        # 2. Water types (ensure they exist)
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

        # ----------------------------------------------------------------
        # 3. Well types (ensure they exist)
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

        # ----------------------------------------------------------------
        # 4. Water right types (ensure they exist)
        # ----------------------------------------------------------------
        self.stdout.write("Ensuring water right types...")
        approp_type, _ = WaterRightType.objects.get_or_create(
            code="APPROP",
            defaults={
                "name": "Appropriative",
                "description": "Post-1914 appropriative water right",
            },
        )
        pre14_type, _ = WaterRightType.objects.get_or_create(
            code="PRE14",
            defaults={
                "name": "Pre-1914",
                "description": "Pre-1914 appropriative water right",
            },
        )

        # ----------------------------------------------------------------
        # 5. GSA Boundary
        # ----------------------------------------------------------------
        self.stdout.write("Creating GSA boundary...")
        boundary = Boundary.objects.create(
            name="Demo Valley GSA",
            description=(
                "Fictional groundwater sustainability agency in the "
                "San Joaquin Valley for demonstration purposes"
            ),
            geometry=make_box(CENTER_LON, CENTER_LAT, 0.15),
            area_sq_miles=85.0,
        )

        # ----------------------------------------------------------------
        # 6. Management Zones (3)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 3 management zones...")
        zone_configs = [
            ("North Management Area", CENTER_LON, CENTER_LAT + 0.03, "management_area"),
            ("Central Management Area", CENTER_LON, CENTER_LAT, "management_area"),
            ("South Management Area", CENTER_LON, CENTER_LAT - 0.03, "management_area"),
        ]
        zones = []
        for name, cx, cy, ztype in zone_configs:
            z = Zone.objects.create(
                name=name,
                boundary=boundary,
                geometry=make_box(cx, cy, 0.04),
                zone_type=ztype,
                description=f"Demo zone for {name.lower()}",
            )
            zones.append(z)

        # ----------------------------------------------------------------
        # 7. Parcels (40 total, ~13 per zone)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 40 parcels...")
        all_parcels = []
        parcels_by_zone = {z.pk: [] for z in zones}
        parcel_idx = 0

        for zi, zone in enumerate(zones):
            cx = zone_configs[zi][1]
            cy = zone_configs[zi][2]
            count = 14 if zi < 2 else 12  # 14 + 14 + 12 = 40

            for j in range(count):
                apn = f"045-{100 + parcel_idx:03d}-{10 + (parcel_idx % 90):03d}"
                offset_x = (j % 5) * 0.007 - 0.014
                offset_y = (j // 5) * 0.007 - 0.007
                area = Decimal(str(random.randint(40, 320)))

                p = Parcel.objects.create(
                    parcel_number=apn,
                    owner_name=OWNER_NAMES[parcel_idx % len(OWNER_NAMES)],
                    area_acres=area,
                    geometry=make_box(cx + offset_x, cy + offset_y, 0.005),
                    status="active",
                )
                ParcelZone.objects.create(parcel=p, zone=zone)
                all_parcels.append(p)
                parcels_by_zone[zone.pk].append(p)
                parcel_idx += 1

        # ----------------------------------------------------------------
        # 8. Wells (15) with meters
        # ----------------------------------------------------------------
        self.stdout.write("Creating 15 wells with meters...")
        well_types = [ag_well_type, ag_well_type, muni_well_type, mon_well_type]
        wells = []
        for i, wname in enumerate(WELL_NAMES):
            zi = i % len(zones)
            cx = zone_configs[zi][1]
            cy = zone_configs[zi][2]
            offset_x = random.uniform(-0.015, 0.015)
            offset_y = random.uniform(-0.015, 0.015)

            well = Well.objects.create(
                well_registration_id=f"WCR-{2024000 + i}",
                name=wname,
                well_type=well_types[i % len(well_types)],
                location=Point(cx + offset_x, cy + offset_y),
                depth_ft=Decimal(str(random.randint(150, 600))),
                capacity_gpm=Decimal(str(random.randint(200, 2500))),
                status="active",
                owner_name=OWNER_NAMES[i],
            )
            wells.append(well)

            # Create a meter for each well
            meter = Meter.objects.create(
                serial_number=f"MTR-{5000 + i:05d}",
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

            # Link well to nearest parcel in same zone
            zone_parcels = parcels_by_zone[zones[zi].pk]
            if zone_parcels:
                target_parcel = zone_parcels[i % len(zone_parcels)]
                WellIrrigatedParcel.objects.create(
                    well=well,
                    parcel=target_parcel,
                    fraction=Decimal("1.0000"),
                )

        # ----------------------------------------------------------------
        # 9. Reporting Periods (2 water years)
        # ----------------------------------------------------------------
        self.stdout.write("Creating reporting periods...")
        wy2024 = ReportingPeriod.objects.create(
            name="WY 2023-2024",
            start_date=date(2023, 10, 1),
            end_date=date(2024, 9, 30),
            is_finalized=True,
        )
        wy2025 = ReportingPeriod.objects.create(
            name="WY 2024-2025",
            start_date=date(2024, 10, 1),
            end_date=date(2025, 9, 30),
        )

        # ----------------------------------------------------------------
        # 10. Water Accounts (5)
        # ----------------------------------------------------------------
        self.stdout.write("Creating 5 water accounts...")
        account_configs = [
            ("DEMO-001", "North Valley Irrigation District"),
            ("DEMO-002", "Central Basin Water Company"),
            ("DEMO-003", "South County Ag Cooperative"),
            ("DEMO-004", "Eastside Mutual Water Co"),
            ("DEMO-005", "Foothill Community Services"),
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

        # Assign parcels to accounts (distribute across accounts)
        for i, parcel in enumerate(all_parcels):
            acct = accounts[i % len(accounts)]
            WaterAccountParcel.objects.create(
                water_account=acct,
                parcel=parcel,
                reporting_period=wy2025,
            )

        # ----------------------------------------------------------------
        # 11. Allocation Plans (one per zone for GW)
        # ----------------------------------------------------------------
        self.stdout.write("Creating allocation plans...")
        for zone in zones:
            AllocationPlan.objects.create(
                name=f"{zone.name} - GW Allocation WY2025",
                zone=zone,
                water_type=gw,
                reporting_period=wy2025,
                allocation_acre_feet=Decimal("1500.0000"),
            )

        # ----------------------------------------------------------------
        # 12. Ledger entries (6 months of supply and usage)
        # ----------------------------------------------------------------
        self.stdout.write("Creating ledger entries (6 months x 40 parcels)...")
        entries = []
        for month_offset in range(6):
            month_date = date(2024, 10, 1) + timedelta(days=30 * month_offset)
            for p in all_parcels:
                # Supply: groundwater pumping (positive)
                supply = Decimal(str(round(random.uniform(5.0, 25.0), 2)))
                entries.append(
                    ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=supply,
                        water_type=gw,
                        source_type="meter_reading",
                        description="Monthly groundwater extraction",
                        reporting_period=wy2025,
                    )
                )
                # Usage: crop ET (negative)
                usage = Decimal(str(round(random.uniform(8.0, 30.0), 2)))
                entries.append(
                    ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=-usage,
                        water_type=gw,
                        source_type="et_estimate",
                        description="Monthly ET consumption estimate",
                        reporting_period=wy2025,
                    )
                )

        ParcelLedger.objects.bulk_create(entries, batch_size=500)

        # ----------------------------------------------------------------
        # 13. Surface Water Rights (3) with points of diversion
        # ----------------------------------------------------------------
        self.stdout.write("Creating 3 water rights with points of diversion...")
        right_configs = [
            ("DEMO-A012345", approp_type, "North Valley Irrigation District",
             date(1965, 3, 15), Decimal("500.0000"), "Kings River"),
            ("DEMO-S067890", pre14_type, "Central Basin Water Company",
             date(1910, 6, 1), Decimal("800.0000"), "San Joaquin River"),
            ("DEMO-A099999", approp_type, "South County Ag Cooperative",
             date(1978, 11, 20), Decimal("300.0000"), "Fresno River"),
        ]
        for right_id, rtype, holder, pdate, face_val, source in right_configs:
            wr = WaterRight.objects.create(
                right_id=right_id,
                right_type=rtype,
                holder_name=holder,
                priority_date=pdate,
                face_value_acre_feet=face_val,
                status="active",
                source_name=source,
            )
            # One point of diversion per right
            pod_lon = CENTER_LON + random.uniform(-0.05, 0.05)
            pod_lat = CENTER_LAT + random.uniform(-0.05, 0.05)
            PointOfDiversion.objects.create(
                water_right=wr,
                name=f"{source} Diversion",
                location=Point(pod_lon, pod_lat),
                stream_name=source,
                max_rate_cfs=Decimal(str(round(random.uniform(2.0, 15.0), 2))),
                status="active",
            )

        # ----------------------------------------------------------------
        # 14. Recharge Sites (2) with events
        # ----------------------------------------------------------------
        self.stdout.write("Creating 2 recharge sites with events...")
        site_configs = [
            ("Demo North Spreading Basin", "spreading_basin",
             CENTER_LON - 0.02, CENTER_LAT + 0.02, Decimal("250.0000")),
            ("Demo South ASR Well", "asr_well",
             CENTER_LON + 0.01, CENTER_LAT - 0.03, Decimal("100.0000")),
        ]
        for sname, stype, lon, lat, capacity in site_configs:
            site = RechargeSite.objects.create(
                name=sname,
                site_type=stype,
                location=Point(lon, lat),
                capacity_acre_feet=capacity,
                status="active",
                operator="Demo Valley GSA",
            )
            # 3 recharge events each
            for month in range(3):
                start = date(2025, 1, 1) + timedelta(days=30 * month)
                vol = Decimal(str(round(random.uniform(20.0, 80.0), 2)))
                RechargeEvent.objects.create(
                    recharge_site=site,
                    start_date=start,
                    end_date=start + timedelta(days=14),
                    volume_acre_feet=vol,
                    water_type=sw,
                    source_description=f"Flood flow from {sname.split()[1]} canal",
                )

        # ----------------------------------------------------------------
        # 15. Monitored Stations (3, linked to existing data sources)
        # ----------------------------------------------------------------
        self.stdout.write("Creating monitored stations...")
        cdec = DataSource.objects.filter(code="CDEC").first()
        usgs = DataSource.objects.filter(code="USGS").first()
        for ds, ext_id, sname, lon, lat in [
            (cdec, "CHW", "Chowchilla River near Daulton",
             CENTER_LON - 0.04, CENTER_LAT + 0.04),
            (usgs, "11253500", "San Joaquin River below Friant Dam",
             CENTER_LON + 0.06, CENTER_LAT - 0.01),
            (cdec, "MDR", "Madera Canal at Head",
             CENTER_LON - 0.01, CENTER_LAT + 0.01),
        ]:
            if ds:
                MonitoredStation.objects.get_or_create(
                    data_source=ds,
                    external_station_id=ext_id,
                    defaults={
                        "station_name": sname,
                        "location": Point(lon, lat),
                        "parameters": ["flow", "stage"],
                        "is_active": True,
                    },
                )

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDemo data seeded successfully:\n"
                f"  1 GSA boundary\n"
                f"  {len(zones)} management zones\n"
                f"  {len(all_parcels)} parcels\n"
                f"  {len(wells)} wells with meters\n"
                f"  {len(accounts)} water accounts\n"
                f"  {len(entries)} ledger entries\n"
                f"  {len(right_configs)} water rights\n"
                f"  {len(site_configs)} recharge sites\n"
                f"  2 reporting periods"
            )
        )
