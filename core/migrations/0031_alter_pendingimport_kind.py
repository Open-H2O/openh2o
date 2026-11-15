# SPDX-License-Identifier: AGPL-3.0-or-later
# Import zones and Import accounts store their uploads as pending imports of their own kinds.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_alter_pendingimport_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pendingimport",
            name="kind",
            field=models.CharField(choices=[('water_rights', 'Water rights'), ('diversions', 'Diversion volumes'), ('lab_results', 'Lab results'), ('production', 'Production'), ('infrastructure', 'Wells, diversions and recharge sites'), ('water_levels', 'Water levels'), ('use_areas', 'Use areas'), ('setup_parcels', 'List of parcel numbers'), ('zones', 'Zone outlines'), ('accounts', 'Accounts and their use areas')], max_length=24),
        ),
    ]
