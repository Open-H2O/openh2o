# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add ``origin`` to AllocationCarryover and widen its unique key (52.6-02, ISS-053).

Existing rows default to ``allocation_carryover`` so they keep their meaning. The
new ``basin_recharge_pool`` / ``incidental_recharge_pool`` values let a zone-year
hold both a rollover carryover and its basin recharge pool without colliding —
hence ``origin`` joins the unique_together key.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0008_calculationrun_provenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="allocationcarryover",
            name="origin",
            field=models.CharField(
                choices=[
                    ("allocation_carryover", "Allocation carryover"),
                    ("basin_recharge_pool", "Basin recharge pool (managed)"),
                    ("incidental_recharge_pool", "Basin recharge pool (incidental)"),
                ],
                default="allocation_carryover",
                help_text=(
                    "What kind of row this is: a year-end allocation carryover, or "
                    "a GSA basin recharge pool (managed / incidental)."
                ),
                max_length=24,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="allocationcarryover",
            unique_together={("zone", "water_type", "water_year", "origin")},
        ),
    ]
