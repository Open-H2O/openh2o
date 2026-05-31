from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Deduplicate telemetry at the source: one observation per
    (station, parameter_code, observation_date). Repeated syncs of the same
    readings become a no-op insert instead of piling up duplicate rows.
    """

    dependencies = [
        ("datasync", "0002_openetcache"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="datarecordstaging",
            constraint=models.UniqueConstraint(
                fields=["station", "parameter_code", "observation_date"],
                name="uniq_staging_station_param_obsdate",
            ),
        ),
    ]
