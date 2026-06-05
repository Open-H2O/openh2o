# SPDX-License-Identifier: AGPL-3.0-or-later
# Hand-written (no local Django runtime): adds the demonstration_mode flag to
# SiteConfig (Phase 53-02). Default False so a fresh real-agency install reads
# clean (no demo stamping); the Merced demo seed opts in by setting it True.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_siteconfig_delivery_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteconfig',
            name='demonstration_mode',
            field=models.BooleanField(
                default=False,
                help_text="When on, every report surface and generated file is "
                "stamped 'demonstration — not submittable'. Off for a real agency "
                "deployment; the Merced demo seed turns it on.",
            ),
        ),
    ]
