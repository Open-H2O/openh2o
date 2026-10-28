# SPDX-License-Identifier: AGPL-3.0-or-later
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recharge", "0006_rechargesite_water_account"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rechargesite",
            name="capacity_acre_feet",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="The volume the site holds per fill, as entered.",
                max_digits=12,
                null=True,
                verbose_name="Capacity per fill (AF)",
            ),
        ),
    ]
