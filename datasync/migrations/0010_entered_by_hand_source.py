# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add the "Entered by hand" data source to a site that already has data sources.

A station of this source never syncs: a person types each reading on the
station's page. A new install gets the source from ``seed_data_sources``; this
step is for a site that seeded its sources before the source existed, so the
upgrade gives it the source with no extra command. A site with no data sources
at all is a new install and is left to the seed. The step adds nothing when the
code is already there, so it can run twice. Reversing removes the source only
while no station uses it.
"""

from django.db import migrations

CODE = "manual"
NAME = "Entered by hand"


def add_source(apps, schema_editor):
    DataSource = apps.get_model("datasync", "DataSource")
    if not DataSource.objects.exists():
        return
    DataSource.objects.get_or_create(
        code=CODE,
        defaults={
            "name": NAME,
            "url": "",
            "auth_type": "none",
            "sync_interval_hours": 24,
            "description": "Readings typed on the station's page by an Operator or Administrator",
            "is_active": True,
        },
    )


def remove_source(apps, schema_editor):
    DataSource = apps.get_model("datasync", "DataSource")
    MonitoredStation = apps.get_model("datasync", "MonitoredStation")
    if not MonitoredStation.objects.filter(data_source__code=CODE).exists():
        DataSource.objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0009_typed_readings_and_station_logs"),
    ]

    operations = [
        migrations.RunPython(add_source, remove_source),
    ]
