# SPDX-License-Identifier: AGPL-3.0-or-later
# Hand-written (no local Django runtime): adds the nullable per-district
# recovery-horizon override to Zone (Phase 55-02). Nullable + blank, so it
# applies cleanly to every existing zone (null = "inherit the agency default"),
# changing no behavior on migrate.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('geography', '0003_boundary_basin_code_boundary_huc_zone_basin_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='zone',
            name='recovery_horizon',
            field=models.CharField(
                blank=True,
                choices=[
                    ('carry_forward', 'Carry unused water forward as a credit'),
                    ('same_water_year', 'Unused water expires at year-end'),
                ],
                help_text='Override the agency default for this district. '
                'Blank = use the agency default.',
                max_length=16,
                null=True,
            ),
        ),
    ]
