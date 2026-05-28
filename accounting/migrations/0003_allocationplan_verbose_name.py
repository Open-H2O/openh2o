from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0002_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="allocationplan",
            options={
                "verbose_name": "Water Budget",
                "verbose_name_plural": "Water Budgets",
            },
        ),
        migrations.AlterField(
            model_name="allocationplan",
            name="allocation_acre_feet",
            field=models.DecimalField(
                decimal_places=4, max_digits=12, verbose_name="Water budget (AF)"
            ),
        ),
    ]
