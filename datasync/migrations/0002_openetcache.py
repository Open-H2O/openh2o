import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0001_initial"),
        ("parcels", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OpenETCache",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "geometry",
                    django.contrib.gis.db.models.fields.MultiPolygonField(
                        help_text="Queried geometry", srid=4326
                    ),
                ),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                (
                    "variable",
                    models.CharField(default="ET", max_length=20),
                ),
                (
                    "model_name",
                    models.CharField(default="Ensemble", max_length=50),
                ),
                (
                    "et_data",
                    models.JSONField(
                        help_text="Monthly ET values from API response"
                    ),
                ),
                (
                    "queried_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "parcel",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="parcels.parcel",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["parcel", "start_date", "end_date"],
                        name="datasync_op_parcel__a6c8d7_idx",
                    ),
                    models.Index(
                        fields=["queried_at"],
                        name="datasync_op_queried_4f2e1a_idx",
                    ),
                ],
            },
        ),
    ]
