# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Discover monitoring stations near a boundary and create inactive MonitoredStation records.

Usage:
    python manage.py discover_stations cdec --boundary-name "San Joaquin Valley"
    python manage.py discover_stations usgs --radius 100 --mock
"""

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError

from datasync.adapters import get_adapter
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary


class Command(BaseCommand):
    help = "Discover monitoring stations near a boundary"

    def add_arguments(self, parser):
        parser.add_argument("code", type=str, help="Data source code (e.g. cdec, usgs)")
        parser.add_argument(
            "--radius", type=float, default=50,
            help="Search radius in km (default: 50)",
        )
        parser.add_argument(
            "--boundary-name", type=str, default=None,
            help="Name of the Boundary to search near. Uses first boundary if omitted.",
        )
        parser.add_argument(
            "--mock", action="store_true",
            help="Use fixture data instead of live API",
        )

    def handle(self, *args, **options):
        code = options["code"]
        radius_km = options["radius"]

        try:
            data_source = DataSource.objects.get(code=code)
        except DataSource.DoesNotExist:
            raise CommandError(f"Data source '{code}' not found.")

        adapter = get_adapter(code)
        if adapter is None:
            raise CommandError(f"No adapter registered for '{code}'.")

        # Find boundary
        if options["boundary_name"]:
            try:
                boundary = Boundary.objects.get(name=options["boundary_name"])
            except Boundary.DoesNotExist:
                raise CommandError(
                    f"Boundary '{options['boundary_name']}' not found."
                )
        else:
            boundary = Boundary.objects.first()
            if boundary is None:
                raise CommandError(
                    "No boundaries exist. Create one in the admin or via migration."
                )

        self.stdout.write(
            f"Discovering {data_source.name} stations within {radius_km}km "
            f"of boundary '{boundary.name}'..."
        )

        # Discover
        if options["mock"]:
            # Load station list from fixture
            mock_data = adapter.fetch_mock(None, None, None)
            # Expect the fixture to have a "stations" key at the top level,
            # but fetch_mock returns "records". Load stations directly.
            import json
            from pathlib import Path
            fixture_path = (
                Path(__file__).resolve().parent.parent.parent
                / "fixtures" / f"{code}.json"
            )
            if not fixture_path.exists():
                raise CommandError(f"Fixture not found: {fixture_path}")
            with open(fixture_path) as f:
                fixture = json.load(f)
            discovered = fixture.get("stations", [])
        else:
            discovered = adapter.discover_stations(boundary.geometry, radius_km)

        if not discovered:
            self.stdout.write(
                self.style.WARNING("No stations found in the search area.")
            )
            return

        created_count = 0
        existing_count = 0

        for stn in discovered:
            station_id = stn.get("station_id", "")
            name = stn.get("name", "Unknown")
            lat = stn.get("latitude")
            lon = stn.get("longitude")
            params = stn.get("parameters", [])

            if not station_id or lat is None or lon is None:
                self.stdout.write(
                    self.style.WARNING(f"  Skipping station with missing data: {stn}")
                )
                continue

            point = Point(float(lon), float(lat), srid=4326)

            _, created = MonitoredStation.objects.get_or_create(
                data_source=data_source,
                external_station_id=station_id,
                defaults={
                    "station_name": name,
                    "location": point,
                    "parameters": params,
                    "is_active": False,
                },
            )

            if created:
                created_count += 1
                self.stdout.write(f"  + {station_id}: {name}")
            else:
                existing_count += 1
                self.stdout.write(f"  = {station_id}: {name} (already exists)")

        self.stdout.write(
            self.style.SUCCESS(
                f"Discovered {len(discovered)} stations: "
                f"{created_count} created, {existing_count} existing"
            )
        )
