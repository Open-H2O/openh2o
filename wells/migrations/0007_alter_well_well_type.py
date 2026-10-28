# SPDX-License-Identifier: AGPL-3.0-or-later
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wells", "0006_wellevent_wellirrigatedparcelevent_wellmeterevent_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="well",
            name="well_type",
            field=models.ForeignKey(
                blank=True,
                help_text="Chosen from the well types on record. Blank means no well type was entered.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="wells.welltype",
            ),
        ),
    ]
