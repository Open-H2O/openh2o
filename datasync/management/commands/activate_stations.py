# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Activate discovered monitoring stations inside a boundary — the headless
counterpart to the setup wizard's "Enable all" button.

Discovery creates stations inactive, and ``sync_source`` only pulls data for
active ones, so a fresh basin needs an activation step between the two. A
browser operator gets it at ``/setup/``; this is the same operation over SSH.

Usage:
    python manage.py activate_stations --boundary-name "Merced Subbasin"
    python manage.py activate_stations --source cdec --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary


class Command(BaseCommand):
    help = "Activate inactive monitoring stations inside a boundary"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", type=str, default=None,
            help="Data source code (e.g. cdec, usgs). All sources if omitted.",
        )
        parser.add_argument(
            "--boundary-name", type=str, default=None,
            help="Name of the Boundary to activate within. Uses first boundary if omitted.",
        )
        parser.add_argument(
            "--all-boundaries", action="store_true",
            help="Activate everywhere, ignoring boundaries. Must be typed deliberately.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without touching anything",
        )

    def handle(self, *args, **options):
        code = options["source"]
        boundary_name = options["boundary_name"]
        all_boundaries = options["all_boundaries"]
        dry_run = options["dry_run"]

        if all_boundaries and boundary_name:
            raise CommandError(
                "--all-boundaries and --boundary-name are mutually exclusive."
            )

        # Resolve the source filter first, so an unknown code fails before any
        # boundary lookup work.
        data_source = None
        if code:
            try:
                data_source = DataSource.objects.get(code=code)
            except DataSource.DoesNotExist:
                raise CommandError(f"Data source '{code}' not found.")

        # Resolve the scope. Platform-wide requires --all-boundaries; with
        # nothing given we fall back to the first boundary and NAME it, so the
        # operator sees the scope they got instead of inferring it.
        boundary = None
        if not all_boundaries:
            if boundary_name:
                try:
                    boundary = Boundary.objects.get(name=boundary_name)
                except Boundary.DoesNotExist:
                    raise CommandError(f"Boundary '{boundary_name}' not found.")
            else:
                boundary = Boundary.objects.first()
                if boundary is None:
                    raise CommandError(
                        "No boundaries exist. Create one in the admin, upload one "
                        "at /setup/, or pass --all-boundaries."
                    )

        scope_label = "all boundaries" if boundary is None else f"'{boundary.name}'"
        source_label = data_source.name if data_source else "all sources"
        self.stdout.write(
            f"Activating inactive {source_label} stations within {scope_label}..."
        )

        qs = MonitoredStation.objects.filter(is_active=False)
        if boundary is not None:
            # Same spatial predicate as setup/views.py's activate endpoint, so
            # the browser path and this one cannot drift apart.
            qs = qs.filter(location__within=boundary.geometry)
        if data_source is not None:
            qs = qs.filter(data_source=data_source)

        count = qs.count()

        if dry_run:
            for station in qs.order_by("station_name")[:20]:
                self.stdout.write(f"  would activate: {station}")
            self.stdout.write(
                self.style.SUCCESS(f"Would activate {count} station(s).")
            )
            return

        # A single update — no N+1 saves, matching the wizard's own approach.
        updated = qs.update(is_active=True)
        self.stdout.write(self.style.SUCCESS(f"Activated {updated} station(s)."))
