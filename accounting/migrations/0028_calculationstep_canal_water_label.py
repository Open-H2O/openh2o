# 149.1-07 (2026-10-08): the canal step's name, "Subtract canal water the crop
# could use", on the choice label and on the plan rows already written.
#
# Rule 12 of DESIGN.md names the figure this step subtracts "canal water the
# crop could use" (delivered times the field's irrigation efficiency, with the
# step's apply_efficiency switch on), and the calculation page already prints
# "minus canal water the crop could use". The step itself was still named
# "Subtract surface water delivered" in two places: the choice label below and
# the label seed_calculation_plan writes onto the plan's row, which the
# Methodology page prints. A plan seeded before this change keeps the old label
# until someone edits it, so this migration carries the new words onto every
# step row that still holds the old label exactly. A label an agency typed for
# itself is left alone.
#
# The strings are COPIED here on purpose (the parcels 0009 / 0011 rule): a
# migration keeps meaning what it meant on the day it ran and never imports the
# live constants. CalculationRun.breakdown keeps the label each run was computed
# under; it is the run's record and is not rewritten.
from django.db import migrations, models

OLD_LABEL = "Subtract surface water delivered"
NEW_LABEL = "Subtract canal water the crop could use"


def _relabel(apps, schema_editor, old, new):
    CalculationStep = apps.get_model("accounting", "CalculationStep")
    # The step's history triggers stay on: unlike the ledger (parcels 0011)
    # there is no finalized-period lock on a plan step to step around, and the
    # step's history then shows the rename like any other label edit.
    CalculationStep.objects.filter(label=old).update(label=new)


def forward(apps, schema_editor):
    _relabel(apps, schema_editor, OLD_LABEL, NEW_LABEL)


def backward(apps, schema_editor):
    _relabel(apps, schema_editor, NEW_LABEL, OLD_LABEL)


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0027_alter_allocationcarryover_origin_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calculationstep',
            name='step_type',
            field=models.CharField(choices=[('et_gross', 'Gross ET'), ('subtract_effective_precip', 'Subtract effective precipitation'), ('subtract_surface_water', 'Subtract canal water the crop could use'), ('facility_only_zero', 'Zero out facility-only parcels'), ('clamp_floor', 'Clamp at floor')], max_length=40),
        ),
        migrations.AlterField(
            model_name='calculationstepevent',
            name='step_type',
            field=models.CharField(choices=[('et_gross', 'Gross ET'), ('subtract_effective_precip', 'Subtract effective precipitation'), ('subtract_surface_water', 'Subtract canal water the crop could use'), ('facility_only_zero', 'Zero out facility-only parcels'), ('clamp_floor', 'Clamp at floor')], max_length=40),
        ),
        migrations.RunPython(forward, backward),
    ]
