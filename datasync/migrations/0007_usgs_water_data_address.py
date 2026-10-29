# SPDX-License-Identifier: AGPL-3.0-or-later
"""Point the stored USGS source at the USGS Water Data APIs.

USGS shuts down its older WaterServices site on 2027-02-22. The source row
seeded on earlier installs holds that site's address. Only a row that still
holds the seeded address moves; an address an operator edited stays as they
left it. The reverse puts the seeded address back under the same condition.
"""

from django.db import migrations

OLD_URL = "https://waterservices.usgs.gov"
NEW_URL = "https://api.waterdata.usgs.gov"


def forward(apps, schema_editor):
    DataSource = apps.get_model("datasync", "DataSource")
    DataSource.objects.filter(code="usgs", url=OLD_URL).update(url=NEW_URL)


def reverse(apps, schema_editor):
    DataSource = apps.get_model("datasync", "DataSource")
    DataSource.objects.filter(code="usgs", url=NEW_URL).update(url=OLD_URL)


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0006_openetcache_origin"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
