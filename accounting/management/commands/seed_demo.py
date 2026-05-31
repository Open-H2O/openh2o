# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed realistic demo data for a fictional GSA."""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.models import (
    AllocationPlan,
    ReportingPeriod,
    WaterAccount,
    WaterAccountParcel,
    WaterType,
)
from geography.models import Boundary, ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger


def make_box(cx, cy, size=0.005):
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
    help = "Seed demo data: 3 zones, 30 parcels, 3 accounts, 6 months ledger."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._run()

    def _run(self):
        # Water types
        gw, _ = WaterType.objects.get_or_create(code="GW", defaults={"name": "Groundwater"})
        sw, _ = WaterType.objects.get_or_create(code="SW", defaults={"name": "Surface Water"})
        recycled, _ = WaterType.objects.get_or_create(code="RW", defaults={"name": "Recycled Water"})

        # Boundary
        boundary, _ = Boundary.objects.get_or_create(
            name="Demo Valley GSA",
            defaults={
                "description": "Fictional groundwater sustainability agency for demonstration",
                "geometry": make_box(-119.78, 36.75, 0.15),
                "area_sq_miles": 85.0,
            },
        )

        # 3 Zones
        zone_configs = [
            ("North Management Area", -119.78, 36.78, 0.04, "management_area"),
            ("Central Management Area", -119.78, 36.75, 0.04, "management_area"),
            ("South Management Area", -119.78, 36.72, 0.04, "management_area"),
        ]
        zones = []
        for name, cx, cy, size, ztype in zone_configs:
            z, _ = Zone.objects.get_or_create(
                name=name,
                boundary=boundary,
                defaults={
                    "geometry": make_box(cx, cy, size),
                    "zone_type": ztype,
                    "description": f"Demo zone for testing",
                },
            )
            zones.append(z)

        # 30 Parcels (10 per zone)
        parcels_by_zone = {z: [] for z in zones}
        owners = [
            "Johnson Family Trust", "Garcia Farms LLC", "Central Valley Ag",
            "Smith Ranch", "Westside Orchards", "Valley Dairy Co",
            "Sunrise Vineyards", "Oak Creek Ranch", "Delta Irrigation",
            "Hillside Farms", "Riverside Ag Corp", "Golden State Growers",
            "Pioneer Land Co", "Heritage Farms", "Valley View Ranch",
            "Madera Ag Partners", "Blue Sky Dairy", "Summit Orchards",
            "Foothill Farms", "Basin Water Co", "Sierra Land Trust",
            "Central Pumping", "Valley Floor Ag", "Eastside Growers",
            "Mesa Verde Ranch", "Adobe Creek Farm", "Lakeview Dairy",
            "Pacific Ag Inc", "Cedar Point Ranch", "Willow Springs Farm",
        ]

        parcel_num = 100
        for i, zone in enumerate(zones):
            cx, cy = zone_configs[i][1], zone_configs[i][2]
            for j in range(10):
                parcel_num += 1
                apn = f"045-{parcel_num:03d}-{random.randint(10,99)}"
                offset_x = (j % 5) * 0.008 - 0.016
                offset_y = (j // 5) * 0.008 - 0.004
                area = Decimal(str(random.randint(40, 320)))

                p, created = Parcel.objects.get_or_create(
                    parcel_number=apn,
                    defaults={
                        "owner_name": owners[i * 10 + j],
                        "area_acres": area,
                        "geometry": make_box(cx + offset_x, cy + offset_y, 0.006),
                        "status": "active",
                    },
                )
                parcels_by_zone[zone].append(p)

                if created:
                    ParcelZone.objects.get_or_create(parcel=p, zone=zone)

        # Reporting period: WY 2024-2025
        period, _ = ReportingPeriod.objects.get_or_create(
            name="WY 2024-2025",
            defaults={
                "start_date": date(2024, 10, 1),
                "end_date": date(2025, 9, 30),
            },
        )

        # 3 Water Accounts
        account_configs = [
            ("ACC-001", "North Valley Irrigation District", zones[0]),
            ("ACC-002", "Central Basin Water Company", zones[1]),
            ("ACC-003", "South County Ag Cooperative", zones[2]),
        ]
        accounts = []
        for acct_num, name, zone in account_configs:
            acct, _ = WaterAccount.objects.get_or_create(
                account_number=acct_num,
                defaults={
                    "name": name,
                    "status": "active",
                    "contact_name": f"{name.split()[0]} Manager",
                    "contact_email": f"water@{name.split()[0].lower()}.example.com",
                },
            )
            accounts.append((acct, zone))

        # Assign parcels to accounts
        for acct, zone in accounts:
            for p in parcels_by_zone[zone]:
                WaterAccountParcel.objects.get_or_create(
                    water_account=acct,
                    parcel=p,
                    reporting_period=None,
                )

        # Allocation plans
        for zone in zones:
            AllocationPlan.objects.get_or_create(
                zone=zone,
                water_type=gw,
                reporting_period=period,
                defaults={
                    "name": f"{zone.name} - GW Allocation",
                    "allocation_acre_feet": Decimal("1500.0000"),
                },
            )

        # Ledger entries: 6 months of supply and usage
        all_parcels = []
        for plist in parcels_by_zone.values():
            all_parcels.extend(plist)

        existing_count = ParcelLedger.objects.filter(reporting_period=period).count()
        if existing_count > 0:
            self.stdout.write(f"Ledger entries already exist ({existing_count}), skipping.")
        else:
            entries = []
            for month_offset in range(6):
                month_date = date(2024, 10, 1) + timedelta(days=30 * month_offset)
                for p in all_parcels:
                    # Supply: groundwater pumping (positive)
                    supply = Decimal(str(random.uniform(5.0, 25.0))).quantize(Decimal("0.01"))
                    entries.append(ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=supply,
                        water_type=gw,
                        source_type="meter_reading",
                        description=f"Monthly groundwater extraction",
                        reporting_period=period,
                    ))
                    # Usage: crop ET (negative)
                    usage = Decimal(str(random.uniform(8.0, 30.0))).quantize(Decimal("0.01"))
                    entries.append(ParcelLedger(
                        parcel=p,
                        transaction_date=month_date,
                        effective_date=month_date,
                        amount_acre_feet=-usage,
                        water_type=gw,
                        source_type="et_estimate",
                        description=f"Monthly ET consumption estimate",
                        reporting_period=period,
                    ))

            ParcelLedger.objects.bulk_create(entries, batch_size=500)
            self.stdout.write(self.style.SUCCESS(f"Created {len(entries)} ledger entries"))

        self.stdout.write(self.style.SUCCESS(
            f"Demo seeded: {Boundary.objects.count()} boundary, "
            f"{Zone.objects.count()} zones, {Parcel.objects.count()} parcels, "
            f"{WaterAccount.objects.count()} accounts, "
            f"{ParcelLedger.objects.filter(reporting_period=period).count()} ledger entries"
        ))
