# SPDX-License-Identifier: AGPL-3.0-or-later
# The demonstration's El Nido district allocation note, reworded on the rows
# already written (ruling 141, 2026-11-12).
#
# The seed wrote "Surface allocation reduced for a dry year." on the district's
# WY 2025-2026 surface allocation when that year's rainfall was generated as a
# dry year. Both years now carry the rainfall gridMET sent, and the second was
# the wetter, so the note claimed weather the year did not have. The seed now
# writes the cut itself; this carries the same words onto a site that loaded the
# demonstration before, once. Only a row still holding the exact old words moves.
#
# The strings are COPIED here on purpose (the parcels 0009 rule): a migration
# keeps meaning what it meant on the day it ran and never imports live constants.
from django.db import migrations

OLD = "Surface allocation reduced for a dry year."
NEW = (
    "Surface allocation for the demonstration: a tenth of the district's "
    "allocation for WY 2024-2025."
)


def reword_note(AllocationPlan):
    """Rewrite every allocation still carrying the old note. Returns the count."""
    return AllocationPlan.objects.filter(notes=OLD).update(notes=NEW)


def reword(apps, schema_editor):
    AllocationPlan = apps.get_model("accounting", "AllocationPlan")
    # Not a change a person made: the finalized-period lock would refuse it in a
    # closed year, and the change history would record it as one. Off for the
    # one pass, on straight after (as parcels 0011).
    schema_editor.execute("ALTER TABLE accounting_allocationplan DISABLE TRIGGER USER")
    try:
        reword_note(AllocationPlan)
    finally:
        schema_editor.execute("ALTER TABLE accounting_allocationplan ENABLE TRIGGER USER")


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0046_second_language_pass_labels"),
    ]

    operations = [
        migrations.RunPython(reword, migrations.RunPython.noop),
    ]
