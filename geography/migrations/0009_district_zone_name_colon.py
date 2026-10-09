# 150-04 V11 (2026-10-09): the demonstration's surface-district zone names lose
# their em dash. seed_merced_ledgers built each one as
# "MER Surface Service Area <em dash> <holder> (<right id>)"; it now builds
# "MER Surface Service Area: <holder> (<right id>)" (district_zone_name), and
# this migration renames the rows an earlier seed wrote, so a re-seed finds them
# by the new name instead of writing a second zone beside each.
#
# Only a name that starts with the old prefix exactly is touched; a zone an
# agency named for itself is left alone. The strings are COPIED here on purpose
# (the accounting 0028 rule): a migration keeps meaning what it meant on the day
# it ran and never imports the live constants. The zone's history triggers stay
# on, so its history shows the rename like any other edit; Zone carries no
# finalized-period lock. The allocation plans named after these zones keep their
# stored names until the seed next writes them (AllocationPlan is locked inside a
# finalized period, so a migration does not rewrite it).
from django.db import migrations

OLD_PREFIX = "MER Surface Service Area \u2014 "
NEW_PREFIX = "MER Surface Service Area: "


def _rename(apps, schema_editor, old, new):
    Zone = apps.get_model("geography", "Zone")
    for zone in Zone.objects.filter(name__startswith=old):
        zone.name = new + zone.name[len(old):]
        zone.save(update_fields=["name"])


def forward(apps, schema_editor):
    _rename(apps, schema_editor, OLD_PREFIX, NEW_PREFIX)


def backward(apps, schema_editor):
    _rename(apps, schema_editor, NEW_PREFIX, OLD_PREFIX)


class Migration(migrations.Migration):

    dependencies = [
        ('geography', '0008_zone_type_choice_labels'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
