# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record the figures of every finalized water year that has none on file.

OpenH2O keeps a water year's figures as they stood when it was finalized
(``accounting.statements``). A year finalized before that was kept has no record;
this command writes one for each such year, of kind ``recorded_at_upgrade``, from
the figures the pages print now. It runs inside the recorded override (the year is
already finalized) under the reason "Recorded when OpenH2O began keeping filed
figures.", so Change history says why.

It is the demonstration's last step, so a fresh build and an upgraded site end
alike, and the step an upgraded site runs once. A year that already has a record
is left alone, so running it twice writes nothing the second time, and it does
nothing on an empty database. It is a command and not a migration because a
migration never imports live code (the rule in ``parcels/migrations/0012``).
"""

from django.core.management.base import BaseCommand

from accounting.statements import record_upgrade_statements
from core.modules import is_enabled


class Command(BaseCommand):
    help = "Record the filed figures of each finalized water year that has none on file."

    def handle(self, *args, **options):
        if not is_enabled("accounting"):
            # Water accounting is switched off on this site: no figures to keep.
            return
        taken = record_upgrade_statements()
        if not taken:
            self.stdout.write("No finalized water year was missing its filed figures.")
            return
        for statement in taken:
            self.stdout.write(
                f"Recorded the filed figures of {statement.period.name} "
                f"({statement.rows.count()} figures)."
            )
