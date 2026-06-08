"""Assert that a fresh install carries reference data only — no demo/sample content.

This is the invariant the public repo must always satisfy: an agency clones the
code, runs migrations + `seed_data` (reference/lookup data every install needs),
and gets an EMPTY instance ready for their own watershed. The fictional
"Demo Valley GSA" (`seed_demo_data`) is an opt-in demo the public never runs;
"Kaweah Subbasin" is a retired demo basin kept in the guard list below so a
stray leftover from an older install is still caught.

The CI `clean-install-guard` workflow runs this after `seed_data` and fails the
build if a single row of agency/demo content is present — making it impossible
to accidentally publish the software pre-loaded with sample data. Operators can
also run it locally (`make verify-clean`) to confirm a deployment is pristine
before they start entering real data.

Exit code 1 (CommandError) if any content is found; 0 if clean.
"""

from django.core.management.base import BaseCommand, CommandError

from accounting.models import WaterAccount
from core.models import SiteConfig
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, Zone
from parcels.models import Parcel
from wells.models import Well

# A clean install has zero of these. Each is operator-entered or demo-seeded
# content, never reference data. (Reference data — roles, water types, data
# sources, report templates — is loaded by `seed_data` and is expected.)
CONTENT_MODELS = [
    ("Boundaries", Boundary),
    ("Zones", Zone),
    ("Parcels", Parcel),
    ("Wells", Well),
    ("Monitoring stations", MonitoredStation),
    ("Water accounts", WaterAccount),
]

# Named demo artifacts — checked explicitly so the failure message is obvious
# even if a future model is missed by the count sweep above.
DEMO_BOUNDARY_NAMES = ["Demo Valley GSA", "Kaweah Subbasin"]


class Command(BaseCommand):
    help = (
        "Verify a fresh install has reference data only (no demo/agency "
        "content). Exits non-fatal-clean or fails with CommandError if dirty."
    )

    def handle(self, *args, **options):
        dirty = []
        for label, model in CONTENT_MODELS:
            count = model.objects.count()
            if count:
                dirty.append((label, count))

        named_demo = list(
            Boundary.objects.filter(
                name__in=DEMO_BOUNDARY_NAMES
            ).values_list("name", flat=True)
        )
        demo_agency = SiteConfig.objects.exclude(agency_name="").filter(
            agency_name__in=["Demo Valley GSA"]
        ).values_list("agency_name", flat=True)

        if dirty or named_demo or list(demo_agency):
            self.stderr.write(
                self.style.ERROR("CLEAN-INSTALL CHECK FAILED — demo/agency content present:")
            )
            for label, count in dirty:
                self.stderr.write(self.style.ERROR(f"  - {label}: {count}"))
            if named_demo:
                self.stderr.write(
                    self.style.ERROR(f"  - Demo boundaries: {', '.join(named_demo)}")
                )
            if list(demo_agency):
                self.stderr.write(
                    self.style.ERROR(
                        f"  - Demo SiteConfig agency: {', '.join(demo_agency)}"
                    )
                )
            raise CommandError(
                "A public install must ship with reference data only. "
                "Run `make seed` (reference data) — never `make demo`/`make kaweah` "
                "— for a clean install."
            )

        # Positive signal: reference data must actually be present, so a
        # silently-broken seed_data (zero everything) doesn't masquerade as clean.
        # seed_data_sources ships the external provider rows the app needs.
        ref_count = DataSource.objects.count()
        if ref_count == 0:
            raise CommandError(
                "No reference data found (zero DataSource rows). "
                "Run `make seed` before this check — an empty database is broken, not clean."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Clean-install check PASSED — {ref_count} reference data source(s) loaded, "
                "no demo/agency content."
            )
        )
