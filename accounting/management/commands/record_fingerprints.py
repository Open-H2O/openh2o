# SPDX-License-Identifier: AGPL-3.0-or-later
"""Take the fingerprint of every finalized water year that has none.

A year finalized before OpenH2O kept fingerprints, and the demonstration's
finalized year, get one here: computed from the records as they stand, marked as
taken at the upgrade so the downloaded file says so. A year that already has a
code is left alone, so running it twice writes nothing the second time, and it
does nothing when water accounting is off or the database is empty. It is a
command and not a migration because a migration never imports live code (the
rule in ``parcels/migrations/0012``).

It runs straight after ``record_filed_figures`` at start, so a year's statement
is among the records its code reads.
"""

from django.core.management.base import BaseCommand

from accounting.fingerprints import record_upgrade_fingerprints
from core.modules import is_enabled


class Command(BaseCommand):
    help = "Take the fingerprint of each finalized water year that has none."

    def handle(self, *args, **options):
        if not is_enabled("accounting"):
            # Water accounting is switched off on this site: no years to fingerprint.
            return
        taken = record_upgrade_fingerprints()
        if not taken:
            self.stdout.write("No finalized water year was missing its fingerprint.")
            return
        for period in taken:
            self.stdout.write(f"Took the fingerprint of {period.name}.")
