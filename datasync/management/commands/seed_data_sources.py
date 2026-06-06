# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand

from datasync.models import DataSource

DATA_SOURCES = [
    {
        "name": "CDEC",
        "code": "cdec",
        "url": "https://cdec.water.ca.gov",
        "auth_type": "none",
        "sync_interval_hours": 24,
        "description": "California Data Exchange Center",
    },
    {
        "name": "USGS NWIS",
        "code": "usgs",
        "url": "https://waterservices.usgs.gov",
        "auth_type": "api_key",
        "sync_interval_hours": 24,
        "description": "USGS National Water Information System",
    },
    {
        "name": "OpenET",
        "code": "openet",
        "url": "https://openet.dri.edu",
        "auth_type": "api_key",
        "sync_interval_hours": 720,
        "description": "Satellite evapotranspiration data",
        # 59-01: hidden — not a station source; ET flows via OpenETCache, not the station pipeline
        "is_active": False,
    },
    {
        "name": "CIMIS",
        "code": "cimis",
        "url": "https://et.water.ca.gov",
        "auth_type": "api_key",
        "sync_interval_hours": 24,
        "description": "California Irrigation Management Information System",
        # 68-01: revived (ISS-007) — re-pointed to the new 2026 API; valid key in CIMIS_API_KEY.
        "is_active": True,
    },
    {
        "name": "CNRFC",
        "code": "cnrfc",
        "url": "https://www.cnrfc.noaa.gov",
        "auth_type": "none",
        "sync_interval_hours": 24,
        "description": "California Nevada River Forecast Center",
        # 59-01: retired — no telemetry stations in the Merced bbox (forecast provider)
        "is_active": False,
    },
    {
        "name": "Department of Water Resources Water Data Library",
        "code": "dwr_wdl",
        "url": "https://wdl.water.ca.gov",
        "auth_type": "none",
        "sync_interval_hours": 168,
        "description": "Department of Water Resources groundwater level data",
    },
    {
        "name": "Department of Water Resources SGMA Portal",
        "code": "dwr_sgma",
        "url": "https://sgma.water.ca.gov",
        "auth_type": "none",
        "sync_interval_hours": 720,
        "description": "Department of Water Resources SGMA monitoring data",
    },
    {
        "name": "NOAA NCEI",
        "code": "noaa",
        "url": "https://www.ncei.noaa.gov",
        "auth_type": "token",
        "sync_interval_hours": 24,
        "description": "NOAA National Centers for Environmental Information",
    },
]


class Command(BaseCommand):
    help = "Seed default data sources"

    def handle(self, *args, **options):
        created_count = 0
        for ds in DATA_SOURCES:
            # Sources without the key default to active; cnrfc/openet/cimis carry False (59-01).
            desired_active = ds.get("is_active", True)
            obj, created = DataSource.objects.get_or_create(
                code=ds["code"],
                defaults={
                    "name": ds["name"],
                    "url": ds["url"],
                    "auth_type": ds["auth_type"],
                    "sync_interval_hours": ds["sync_interval_hours"],
                    "description": ds["description"],
                    "is_active": desired_active,
                },
            )
            status = "created" if created else "existing"
            # Enforce is_active on existing rows so a re-seed (or a box where these were
            # previously active) flips cnrfc/openet/cimis off. Deactivate, never delete:
            # keeps history, makes the cimis defer reversible, leaves OpenETCache ET untouched.
            if not created and obj.is_active != desired_active:
                obj.is_active = desired_active
                obj.save(update_fields=["is_active"])
                status = "reactivated" if desired_active else "deactivated"
            self.stdout.write(f"  {ds['name']} ({ds['code']}): {status}")
            if created:
                created_count += 1
        existing = len(DATA_SOURCES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(DATA_SOURCES)} data sources ({created_count} created, {existing} existing)"
            )
        )
