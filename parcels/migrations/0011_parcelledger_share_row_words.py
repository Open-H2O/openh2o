# 149.1-05 (2026-10-07): the canal split's fallback sentence, reworded on the
# rows already written.
#
# Brent rejected the fixed-share rows on staging on 2026-09-17 08:31 PDT ("This
# is illegible to anyone including a district engineer. What is a fixed share?").
# `accounting.ledger_words.DELIVERY_SHARE_BY_FIXED` and the tail composed in
# `delivery_share_words` now name the thing and the rule. A split row is only
# rewritten by the engine when its headgate month is recalculated, so the rows
# written before this change would keep the struck words on the Use Ledger and
# on every field's ledger card until then; and `_delivery_split_kind` and
# `accounting.services` tell a fixed-share month from a demand-weighted one by
# `description__contains=DELIVERY_SHARE_BY_FIXED`, so those months would also
# have read as demand-weighted on the calculation page. This migration carries
# the new words onto the existing rows, once.
#
# The strings are COPIED here on purpose (the 0009 rule): a migration keeps
# meaning what it meant on the day it ran and never imports the live constants.
import re

from django.db import migrations

#: "…Canal Headgate: 20%, the fixed share on file, because no use area it
#: serves has an estimated use for the month" (143.1-01, 2026-09-17 to 2026-10-07).
_OLD_TAIL = re.compile(
    r": (\d+)%, the fixed share on file, because no use area it serves has an "
    r"estimated use for the month$"
)
#: "…Canal Headgate, split by the fixed share on file (20%); no estimated use
#: on record for the month" (before 143.1-01).
_OLDER_TAIL = re.compile(
    r", split by the fixed share on file \((\d+)%\); no estimated use on record "
    r"for the month$"
)
_NEW_TAIL = (
    r", divided up from the canal total by this use area's share of the canal "
    r"on file, \1%, because no use area the canal serves has an estimated use "
    r"for the month"
)


def reword_fixed_share_rows(ParcelLedger):
    """Rewrite every split row still carrying a struck tail. Returns the count."""
    changed = 0
    rows = ParcelLedger.objects.filter(
        source_type="surface_diversion",
        description__contains="the fixed share on file",
    )
    for row in rows.iterator():
        new = _OLD_TAIL.sub(_NEW_TAIL, row.description)
        if new == row.description:
            new = _OLDER_TAIL.sub(_NEW_TAIL, row.description)
        if new != row.description:
            ParcelLedger.objects.filter(pk=row.pk).update(description=new)
            changed += 1
    return changed


def reword(apps, schema_editor):
    ParcelLedger = apps.get_model("parcels", "ParcelLedger")
    # Not a change a person made: the finalized-period lock would refuse it on
    # a closed year's rows. Off for the one pass, on straight after (as 0009).
    schema_editor.execute("ALTER TABLE parcels_parcelledger DISABLE TRIGGER USER")
    try:
        reword_fixed_share_rows(ParcelLedger)
    finally:
        schema_editor.execute("ALTER TABLE parcels_parcelledger ENABLE TRIGGER USER")


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0010_parcelledger_divided_from_point_pk"),
    ]

    operations = [
        migrations.RunPython(reword, migrations.RunPython.noop),
    ]
