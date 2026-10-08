# 149.1-07 (2026-10-08), R-099: the zone type's choice labels in the platform's
# names. "Management Area" becomes "Management area" (sentence case) and
# "Custom" becomes "Agency-drawn". Django records a choice label in the field's
# state, so this migration only brings that state up to date: the stored values
# (management_area, subbasin, custom) do not change and no row is rewritten.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('geography', '0007_parcelzoneevent_zoneevent_parcelzone_insert_insert_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='zone',
            name='zone_type',
            field=models.CharField(blank=True, choices=[('management_area', 'Management area'), ('subbasin', 'Subbasin'), ('custom', 'Agency-drawn')], max_length=50),
        ),
        migrations.AlterField(
            model_name='zoneevent',
            name='zone_type',
            field=models.CharField(blank=True, choices=[('management_area', 'Management area'), ('subbasin', 'Subbasin'), ('custom', 'Agency-drawn')], max_length=50),
        ),
    ]
