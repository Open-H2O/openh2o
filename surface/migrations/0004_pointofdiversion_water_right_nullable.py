from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("surface", "0003_add_pointofdiversionparcel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pointofdiversion",
            name="water_right",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="surface.waterright",
            ),
        ),
    ]
