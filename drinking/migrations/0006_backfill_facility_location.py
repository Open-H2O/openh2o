# SPDX-License-Identifier: AGPL-3.0-or-later
"""Copy each facility's coordinate down from the well it already points at.

Deliberately its own migration rather than a `RunPython` bolted onto 0005: a
schema change and a data change fail for different reasons and are read by
different people, and an operator reading `showmigrations` should see that rows
were touched.

**Why the well and not the source JSON.** A data migration must not depend on a
demonstration-data file that a real deployment does not ship. Both live
deployments were seeded before `SystemFacility.location` existed, and their
`Well` rows were built FROM the published GAMA coordinates by
`seed_merced_drinking._seed_wells` — so copying them back down is exact, not an
approximation of the published record.

**Why no new composition-rule exception.** `drinking/migrations/0001_initial.py`
already declares a dependency on `wells`, so the `(drinking, wells)` migration
edge predates this file; reaching the well through the existing FK introduces no
new edge. `SCHEMA_EXCEPTIONS` stays at nine.

Reverse is a no-op. Un-setting a coordinate that was published is not a rollback
anybody wants, and a reverse that destroyed data would make 0005 un-revertable
in practice.
"""
from django.db import migrations
from django.db.utils import ProgrammingError


def copy_location_from_well(apps, schema_editor):
    """Set `location` on every facility that has a well and no location yet."""
    SystemFacility = apps.get_model("drinking", "SystemFacility")

    moved = 0
    try:
        facilities = SystemFacility.objects.filter(
            location__isnull=True, well__isnull=False
        ).select_related("well")
        for facility in facilities.iterator():
            if facility.well.location is None:
                continue
            facility.location = facility.well.location
            facility.save(update_fields=["location"])
            moved += 1
    except ProgrammingError:
        # A deployment whose `wells` tables were never created (true removal, an
        # option priced in ISSUES.md) should MIGRATE, not die. There is nothing
        # to copy from, and that is a complete answer rather than an error.
        print("  Facility locations: wells table unreachable; nothing to backfill.")
        return

    print(f"  Facility locations: {moved} backfilled from linked wells.")


class Migration(migrations.Migration):

    dependencies = [
        ("drinking", "0005_systemfacility_location"),
    ]

    operations = [
        migrations.RunPython(copy_location_from_well, migrations.RunPython.noop),
    ]
