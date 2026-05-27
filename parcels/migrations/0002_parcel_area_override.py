from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="parcel",
            name="area_override",
            field=models.BooleanField(
                default=False,
                help_text="When checked, area_acres is manually set and will not be auto-calculated from geometry.",
            ),
        ),
    ]
