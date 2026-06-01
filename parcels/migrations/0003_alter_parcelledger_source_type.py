from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0002_parcel_area_override"),
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
                ],
                max_length=50,
            ),
        ),
    ]
