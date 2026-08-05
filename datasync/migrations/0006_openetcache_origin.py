# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record how each OpenET cache row came to exist (ISS-128).

Existing rows default to "unknown", NOT "fixture". We know production's rows
came from the fixture; we do not know that about anyone else's database, and
guessing "fixture" would under-report spend on a guard whose whole job is to
stop us before the provider does. "unknown" counts toward the monthly
allowance, so the guard errs conservative, and load_openet_fixture's upsert
corrects the rows it actually owns on its next run.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0005_openetcache_openetcache_one_row_per_parcel_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="openetcache",
            name="origin",
            field=models.CharField(
                choices=[
                    ("api", "OpenET API call"),
                    ("fixture", "Loaded from a committed fixture"),
                    ("unknown", "Origin not recorded"),
                ],
                default="unknown",
                help_text="Whether this row cost an OpenET request",
                max_length=10,
            ),
        ),
    ]
