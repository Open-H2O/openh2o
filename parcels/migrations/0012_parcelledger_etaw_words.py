# 150.1-02 (2026-10-11): the engine's ledger sentences in the engineer's terms.
#
# Brent approved the terms for the whole system on 2026-10-11 (05:41 and 05:48
# PDT): ETAW, ETAW met by surface water, ETAW met by groundwater, groundwater
# extraction (estimated), surface water in excess of ETAW. The calculated row,
# the zero row, the demand-weighted split tail and the over-delivery credit
# prefix in `accounting.ledger_words` now say them. A row is rewritten by the
# engine only when its month is recalculated, so the rows already written would
# keep the old words on the Use Ledger and on every field's ledger card; this
# migration carries the new words onto them, once.
#
# The strings are COPIED here on purpose (the 0009 rule): a migration keeps
# meaning what it meant on the day it ran and never imports the live constants.
from django.db import migrations

OLD_PUMPING = (
    "Estimated groundwater consumed: the month's estimated use, less "
    "rainfall and the canal water the crop could use."
)
NEW_PUMPING = "ETAW met by groundwater (estimated): ETAW − ETAW met by surface water."

OLD_NO_PUMPING = (
    "No groundwater extraction was derived for this month; rainfall and "
    "the canal water the crop could use covered the estimated use."
)
NEW_NO_PUMPING = (
    "No ETAW met by groundwater this month, so OpenH2O estimates no "
    "groundwater extraction."
)

OLD_SPLIT_TAIL = (
    "divided up from the canal total in proportion to each field's crop "
    "water use after rain"
)
NEW_SPLIT_TAIL = "divided up from the canal total in proportion to each field's ETAW"

OLD_CREDIT = (
    "Credit for canal water delivered beyond the use area's estimated use "
    "for the month"
)
NEW_CREDIT = "Credit for surface water in excess of ETAW"


def reword_rows(ParcelLedger):
    """Rewrite every row still carrying the old words. Returns the count."""
    changed = ParcelLedger.objects.filter(
        source_type="calculated", description=OLD_PUMPING
    ).update(description=NEW_PUMPING)
    changed += ParcelLedger.objects.filter(
        source_type="calculated", description=OLD_NO_PUMPING
    ).update(description=NEW_NO_PUMPING)
    for source_type, old, new in (
        ("surface_diversion", OLD_SPLIT_TAIL, NEW_SPLIT_TAIL),
        ("recharge", OLD_CREDIT, NEW_CREDIT),
    ):
        rows = ParcelLedger.objects.filter(
            source_type=source_type, description__contains=old
        )
        for row in rows.iterator():
            ParcelLedger.objects.filter(pk=row.pk).update(
                description=row.description.replace(old, new)
            )
            changed += 1
    return changed


def reword(apps, schema_editor):
    ParcelLedger = apps.get_model("parcels", "ParcelLedger")
    # Not a change a person made: the finalized-period lock would refuse it on
    # a closed year's rows. Off for the one pass, on straight after (as 0011).
    schema_editor.execute("ALTER TABLE parcels_parcelledger DISABLE TRIGGER USER")
    try:
        reword_rows(ParcelLedger)
    finally:
        schema_editor.execute("ALTER TABLE parcels_parcelledger ENABLE TRIGGER USER")


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0011_parcelledger_share_row_words"),
    ]

    operations = [
        migrations.RunPython(reword, migrations.RunPython.noop),
    ]
