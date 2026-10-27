# The canal split now divides by the shares the district entered, or by acreage
# where it entered none, so the clause the fixed-share rows carried ("because no
# use area the canal serves has an estimated use for the month") is no longer
# true of them. `accounting.ledger_words.DELIVERY_SHARE_SOURCE` holds the new
# clause; this migration carries it onto the rows already written, once. The
# readers that tell a fixed-share month from a demand-weighted one look for
# `DELIVERY_SHARE_BY_FIXED`, which these rows keep.
#
# The strings are COPIED here on purpose (the 0009 rule): a migration keeps
# meaning what it meant on the day it ran and never imports the live constants.
import re

from django.db import migrations

_OLD_TAIL = re.compile(
    r", (\d+)%, because no use area the canal serves has an estimated use for the month$"
)
_NEW_TAIL = (
    r", \1%, taken from the shares entered for the canal, or from each use "
    r"area's acreage where none were entered"
)


def reword_share_rows(ParcelLedger):
    """Rewrite every split row still carrying the old clause. Returns the count."""
    changed = 0
    rows = ParcelLedger.objects.filter(
        source_type="surface_diversion",
        description__contains="because no use area the canal serves",
    )
    for row in rows.iterator():
        new = _OLD_TAIL.sub(_NEW_TAIL, row.description)
        if new != row.description:
            ParcelLedger.objects.filter(pk=row.pk).update(description=new)
            changed += 1
    return changed


def reword(apps, schema_editor):
    ParcelLedger = apps.get_model("parcels", "ParcelLedger")
    # Not a change a person made: the finalized-period lock would refuse it on
    # a closed year's rows. Off for the one pass, on straight after (as 0011).
    schema_editor.execute("ALTER TABLE parcels_parcelledger DISABLE TRIGGER USER")
    try:
        reword_share_rows(ParcelLedger)
    finally:
        schema_editor.execute("ALTER TABLE parcels_parcelledger ENABLE TRIGGER USER")


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0018_parcel_fallow"),
    ]

    operations = [
        migrations.RunPython(reword, migrations.RunPython.noop),
    ]
