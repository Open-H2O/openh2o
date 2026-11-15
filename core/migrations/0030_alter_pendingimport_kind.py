# SPDX-License-Identifier: AGPL-3.0-or-later
# The Setup Wizard's parcel download runs as a pending import of its own kind.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_second_language_pass_help_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pendingimport",
            name="kind",
            field=models.CharField(choices=[('water_rights', 'Water rights'), ('diversions', 'Diversion volumes'), ('lab_results', 'Lab results'), ('production', 'Production'), ('infrastructure', 'Wells, diversions and recharge sites'), ('water_levels', 'Water levels'), ('use_areas', 'Use areas'), ('setup_parcels', 'List of parcel numbers')], max_length=24),
        ),
    ]
