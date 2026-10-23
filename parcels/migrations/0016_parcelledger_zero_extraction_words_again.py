# 151.3-05 (2026-10-23): the zero row's sentence names what met the ETAW.
#
# "No ETAW met by groundwater this month, so the estimated groundwater
# extraction is zero." became "Groundwater did not meet any of this month's
# ETAW, so the estimated groundwater extraction is zero." in
# `accounting.ledger_words` (Brent's yes, 2026-10-23 05:15 PDT, on rewriting the
# saved rows too). A finalized year is never recalculated, so without this its
# rows would keep the old words for good. Only the description text moves, as
# 0014: no amount, date, count or other column is touched.
#
# The strings are COPIED here on purpose (the 0009 rule): a migration keeps
# meaning what it meant on the day it ran and never imports the live constants.
from django.db import migrations

OLD_NO_PUMPING = (
    "No ETAW met by groundwater this month, so the estimated groundwater "
    "extraction is zero."
)
NEW_NO_PUMPING = (
    "Groundwater did not meet any of this month's ETAW, so the estimated "
    "groundwater extraction is zero."
)


def reword_rows(ParcelLedger, old=OLD_NO_PUMPING, new=NEW_NO_PUMPING):
    """Rewrite every calculated row still carrying ``old``. Returns the count."""
    return ParcelLedger.objects.filter(
        source_type="calculated", description=old
    ).update(description=new)


def _run(apps, schema_editor, old, new):
    ParcelLedger = apps.get_model("parcels", "ParcelLedger")
    # Not a change a person made: the finalized-period lock would refuse it on
    # a closed year's rows. Off for the one pass, on straight after (as 0014).
    schema_editor.execute("ALTER TABLE parcels_parcelledger DISABLE TRIGGER USER")
    try:
        reword_rows(ParcelLedger, old, new)
    finally:
        schema_editor.execute("ALTER TABLE parcels_parcelledger ENABLE TRIGGER USER")


def reword(apps, schema_editor):
    _run(apps, schema_editor, OLD_NO_PUMPING, NEW_NO_PUMPING)


def unreword(apps, schema_editor):
    _run(apps, schema_editor, NEW_NO_PUMPING, OLD_NO_PUMPING)


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0015_remove_parcelledger_finalized_period_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(reword, unreword),
    ]
