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
    },
    {
        "name": "CIMIS",
        "code": "cimis",
        "url": "https://et.water.ca.gov",
        "auth_type": "api_key",
        "sync_interval_hours": 24,
        "description": "California Irrigation Management Information System",
    },
    {
        "name": "CNRFC",
        "code": "cnrfc",
        "url": "https://www.cnrfc.noaa.gov",
        "auth_type": "none",
        "sync_interval_hours": 24,
        "description": "California Nevada River Forecast Center",
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
            _, created = DataSource.objects.get_or_create(
                code=ds["code"],
                defaults={
                    "name": ds["name"],
                    "url": ds["url"],
                    "auth_type": ds["auth_type"],
                    "sync_interval_hours": ds["sync_interval_hours"],
                    "description": ds["description"],
                },
            )
            status = "created" if created else "existing"
            self.stdout.write(f"  {ds['name']} ({ds['code']}): {status}")
            if created:
                created_count += 1
        existing = len(DATA_SOURCES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(DATA_SOURCES)} data sources ({created_count} created, {existing} existing)"
            )
        )
