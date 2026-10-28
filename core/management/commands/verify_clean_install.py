"""Assert that a fresh install carries reference data only — no demo/sample content.

This is the invariant the public repo must always satisfy: an agency clones the
code, runs migrations + `seed_data` (reference/lookup data every install needs),
and gets an EMPTY instance ready for their own watershed. The fictional
demonstration (`load_demonstration`) is opt-in and the public never runs it.

The CI `clean-install-guard` workflow runs this after `seed_data` and fails the
build if a single row of agency/demo content is present — making it impossible
to accidentally publish the software pre-loaded with sample data. Operators can
also run it locally (`make verify-clean`) to confirm a deployment is pristine
before they start entering real data.

Exit code 1 (CommandError) if any content is found; 0 if clean.
"""

from django.core.management.base import BaseCommand, CommandError

from core import demonstration
from core.models import SiteConfig
from datasync.models import DataSource


class Command(BaseCommand):
    help = (
        "Verify a fresh install has reference data only (no demo/agency "
        "content). Exits non-fatal-clean or fails with CommandError if dirty."
    )

    def handle(self, *args, **options):
        # The same list the demonstration's load and removal use, so a new
        # table cannot be missed here.
        dirty = [
            (demonstration.SCREEN_NAMES[label][1].capitalize(), count)
            for label, count in demonstration.content_counts().items()
        ]

        demo_agency = SiteConfig.objects.filter(
            agency_name=demonstration.DEMONSTRATION_NAME
        ).values_list("agency_name", flat=True)

        if dirty or list(demo_agency):
            self.stderr.write(
                self.style.ERROR("CLEAN-INSTALL CHECK FAILED — demo/agency content present:")
            )
            for label, count in dirty:
                self.stderr.write(self.style.ERROR(f"  - {label}: {count}"))
            if list(demo_agency):
                self.stderr.write(
                    self.style.ERROR(
                        f"  - Demo SiteConfig agency: {', '.join(demo_agency)}"
                    )
                )
            raise CommandError(
                "A public install must ship with reference data only. "
                "Run `make seed` (reference data) — never `make demo` "
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
