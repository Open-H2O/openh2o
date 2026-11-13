# SPDX-License-Identifier: AGPL-3.0-or-later
# The recorded crop ET figure's received day is labelled "date received" (Change history read
# "Fetched"). A label only: no column changes.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasync', '0017_openetcache_origin_gee'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cropetfigure',
            name='fetched_on',
            field=models.DateField(blank=True, null=True, verbose_name='date received'),
        ),
        migrations.AlterField(
            model_name='cropetfigureevent',
            name='fetched_on',
            field=models.DateField(blank=True, null=True, verbose_name='date received'),
        ),
    ]
