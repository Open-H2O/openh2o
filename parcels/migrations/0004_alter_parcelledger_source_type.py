from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0003_alter_parcelledger_source_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="parcelledger",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("meter_reading", "Meter Reading"),
                    ("et_estimate", "ET Estimate"),
                    ("manual_entry", "Manual Entry"),
                    ("csv_import", "CSV Import"),
                    ("surface_diversion", "Surface Diversion"),
                    ("recharge", "Recharge"),
                    ("allocation", "Water Budget"),
                    ("adjustment", "Adjustment"),
                    ("calculated", "Calculated"),
                ],
                max_length=50,
            ),
        ),
    ]
