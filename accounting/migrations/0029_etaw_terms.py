# 150.1-02 (2026-10-11): the canal step and the groundwater disposition in
# the engineer's terms. The step's name
# becomes "Subtract delivery x irrigation efficiency" on the choice label and
# on the plan rows already written (the Methodology page prints the row's
# label), as 0028 did for the words before; the disposition's label becomes
# "ETAW met by groundwater (estimated)". A label an agency typed for itself is
# left alone. The strings are COPIED here on purpose (the parcels 0009 / 0011
# rule).
from django.db import migrations, models

OLD_LABEL = "Subtract canal water the crop could use"
NEW_LABEL = "Subtract delivery \u00d7 irrigation efficiency"


def _relabel(apps, schema_editor, old, new):
    CalculationStep = apps.get_model("accounting", "CalculationStep")
    CalculationStep.objects.filter(label=old).update(label=new)


def forward(apps, schema_editor):
    _relabel(apps, schema_editor, OLD_LABEL, NEW_LABEL)


def backward(apps, schema_editor):
    _relabel(apps, schema_editor, NEW_LABEL, OLD_LABEL)


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0028_calculationstep_canal_water_label'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calculationrun',
            name='residual_disposition',
            field=models.CharField(choices=[('groundwater', 'ETAW met by groundwater (estimated)'), ('unmet_demand', 'Unmet demand / unallocated'), ('metered', 'Metered extraction (authoritative)')], default='groundwater', help_text='How the ET − precip − surface residual was resolved: written as a calculated groundwater extraction (the parcel has a well), recorded as unmet demand (no well — under-irrigation or a surface-allocation error), or marked metered (the parcel carries an authoritative meter reading that owns its groundwater — the run is an ET reference value, no calculated row).', max_length=20),
        ),
        migrations.AlterField(
            model_name='calculationrunevent',
            name='residual_disposition',
            field=models.CharField(choices=[('groundwater', 'ETAW met by groundwater (estimated)'), ('unmet_demand', 'Unmet demand / unallocated'), ('metered', 'Metered extraction (authoritative)')], default='groundwater', help_text='How the ET − precip − surface residual was resolved: written as a calculated groundwater extraction (the parcel has a well), recorded as unmet demand (no well — under-irrigation or a surface-allocation error), or marked metered (the parcel carries an authoritative meter reading that owns its groundwater — the run is an ET reference value, no calculated row).', max_length=20),
        ),
        migrations.AlterField(
            model_name='calculationstep',
            name='step_type',
            field=models.CharField(choices=[('et_gross', 'Gross ET'), ('subtract_effective_precip', 'Subtract effective precipitation'), ('subtract_surface_water', 'Subtract delivery × irrigation efficiency'), ('facility_only_zero', 'Zero out facility-only parcels'), ('clamp_floor', 'Clamp at floor')], max_length=40),
        ),
        migrations.AlterField(
            model_name='calculationstepevent',
            name='step_type',
            field=models.CharField(choices=[('et_gross', 'Gross ET'), ('subtract_effective_precip', 'Subtract effective precipitation'), ('subtract_surface_water', 'Subtract delivery × irrigation efficiency'), ('facility_only_zero', 'Zero out facility-only parcels'), ('clamp_floor', 'Clamp at floor')], max_length=40),
        ),
        migrations.RunPython(forward, backward),
    ]
