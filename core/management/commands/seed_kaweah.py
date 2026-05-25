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
        # Summary
        # ----------------------------------------------------------------
        self.stdout.write(
            self.style.SUCCESS(
                f"\nKaweah Subbasin data seeded successfully:\n"
                f"  1 subbasin boundary\n"
                f"  {len(zones)} management zones\n"
            )
        )
