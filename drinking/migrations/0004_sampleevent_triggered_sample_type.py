from django.db import migrations, models


class Migration(migrations.Migration):
    """ISS-076: add the `triggered` sample type (EPA CMDP code `TG`).

    A source sample required under the Ground Water Rule after a coliform-
    positive routine sample. `choices` are not enforced at the database level,
    so this is a no-op for existing rows — it only records the widened vocabulary
    in migration state so `makemigrations --check` stays clean.
    """

    dependencies = [
        ("drinking", "0003_systemfacility_epa_facility_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sampleevent",
            name="sample_type",
            field=models.CharField(
                choices=[
                    ("routine", "Routine"),
                    ("repeat", "Repeat"),
                    ("confirmation", "Confirmation"),
                    ("special", "Special"),
                    ("triggered", "Triggered"),
                ],
                default="routine",
                max_length=20,
            ),
        ),
    ]
