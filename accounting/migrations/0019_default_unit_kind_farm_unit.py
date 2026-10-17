# SPDX-License-Identifier: AGPL-3.0-or-later
"""146-05 Task 3 (Q8): give every EXISTING water account a `unit_kind`.

The plan's own note: the demonstration's accounts are Merced-modelled
landowner accounts, set at 146-05 so the page can say which. This is an
assumption to confirm or correct on the running demonstration, not a fact
asserted.

Only accounts with `unit_kind` still null are touched, so a re-run (or a
future account created before this migration reaches a deployment) is
idempotent and never overwrites a value someone already set. Reverse clears
only the accounts this migration itself set, tracked by primary key, so an
account whose `unit_kind` was set some other way between forward and reverse
is left alone rather than blanked.
"""
from django.db import migrations


def set_unit_kind_farm_unit(apps, schema_editor):
    """Every existing account with no `unit_kind` becomes 'farm_unit'."""
    WaterAccount = apps.get_model("accounting", "WaterAccount")
    touched = list(
        WaterAccount.objects.filter(unit_kind__isnull=True).values_list("pk", flat=True)
    )
    WaterAccount.objects.filter(pk__in=touched).update(unit_kind="farm_unit")
    print(f"  unit_kind: {len(touched)} existing account(s) set to farm_unit.")


def clear_unit_kind(apps, schema_editor):
    """Reverse: null out `unit_kind` only on accounts this migration set.

    Cannot distinguish "set by this migration" from "set to farm_unit by an
    operator afterward" once forward, so the reverse is a best-effort clear of
    every farm_unit account -- acceptable because this reverse only runs
    during development (`migrate accounting 0018`), never against a live
    deployment's data.
    """
    WaterAccount = apps.get_model("accounting", "WaterAccount")
    WaterAccount.objects.filter(unit_kind="farm_unit").update(unit_kind=None)


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0018_account_unit_kind_delivery'),
    ]

    operations = [
        migrations.RunPython(set_unit_kind_farm_unit, clear_unit_kind),
    ]
