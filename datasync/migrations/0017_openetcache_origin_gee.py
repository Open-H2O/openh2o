# SPDX-License-Identifier: AGPL-3.0-or-later
# A row the Earth Engine tier writes (OpenET's ensemble and gridMET rainfall)
# says so, rather than "Origin not recorded". Choices only: no column changes.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0016_record_crop_et_at_upgrade"),
    ]

    operations = [
        migrations.AlterField(
            model_name="openetcache",
            name="origin",
            field=models.CharField(
                choices=[
                    ("api", "OpenET API call"),
                    ("gee", "Received through Google Earth Engine"),
                    ("fixture", "Loaded from a committed fixture"),
                    ("unknown", "Origin not recorded"),
                ],
                default="unknown",
                help_text="Whether this row cost an OpenET request",
                max_length=10,
            ),
        ),
    ]
