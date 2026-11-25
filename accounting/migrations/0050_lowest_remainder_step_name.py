"""The floor step takes the name Help > Settings explained gives it: Lowest remainder.

Methodology Settings called it "Clamp at floor" and Settings explained "Lowest
remainder", one setting with two names. The step's name is editable, so only a
step still holding the name new sites were given is renamed; a name an
office typed stays. The name is not in the calculation plan's hash, so no
figure or water year code moves.
"""

from django.db import migrations, models

OLD = "Clamp at floor"
NEW = "Lowest remainder"

CHOICES = [
    ("et_gross", "Gross ET"),
    ("subtract_effective_precip", "Subtract effective precipitation"),
    ("subtract_surface_water", "Subtract delivery × irrigation efficiency"),
    ("clamp_floor", NEW),
]


def rename(apps, schema_editor):
    CalculationStep = apps.get_model("accounting", "CalculationStep")
    CalculationStep.objects.filter(step_type="clamp_floor", label=OLD).update(label=NEW)


def rename_back(apps, schema_editor):
    CalculationStep = apps.get_model("accounting", "CalculationStep")
    CalculationStep.objects.filter(step_type="clamp_floor", label=NEW).update(label=OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0049_statement_kinds_filed_and_restated"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calculationstep",
            name="step_type",
            field=models.CharField(choices=CHOICES, max_length=40),
        ),
        migrations.AlterField(
            model_name="calculationstepevent",
            name="step_type",
            field=models.CharField(choices=CHOICES, max_length=40),
        ),
        migrations.RunPython(rename, rename_back),
    ]
