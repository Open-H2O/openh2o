# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keep every daily statistic: a statistic column on staged readings.

USGS publishes water temperature as a daily high, low and average. Until now
the adapter stored one of the three, so the unique key was (station, parameter,
observation date). The key gains the statistic, and rows already stored are
given the statistic they were stored as.

The data step follows the shapes measured on the demonstration, staging and
production (151.6-05):

* a row whose ``raw_data`` holds ``statistic_id`` gets that code;
* a USGS row without one gets the statistic the adapter used to keep:
  ``00010`` the daily maximum (``00001``), ``00060`` the daily mean (``00003``);
* any other USGS code and every other source stays blank.

The old key is narrower than the new one, so no existing row can collide under
it and the data step needs no particular place in the order. It runs last, after
the schema changes, so no DDL follows an update inside the transaction. Each rule
is one ``update()``, never a row at a time. Reversing drops the column and
restores the old key, which fails if a station has since stored two statistics
for one day.
"""

from django.db import migrations, models
from django.db.models.fields.json import KeyTextTransform

# USGS parameter code -> the statistic the adapter kept before this change.
KEPT_BEFORE = {"00010": "00001", "00060": "00003"}


def set_statistics_on_old_rows(apps, schema_editor):
    Staging = apps.get_model("datasync", "DataRecordStaging")
    blank = Staging.objects.filter(statistic="")

    # The code a row's own payload names. One update per distinct code (a
    # handful), skipping a blank or a code the column cannot hold.
    named = (
        blank.filter(raw_data__has_key="statistic_id")
        .annotate(code=KeyTextTransform("statistic_id", "raw_data"))
        .order_by()
        .values_list("code", flat=True)
        .distinct()
    )
    for code in list(named):
        if code and len(code) <= 10:
            Staging.objects.filter(statistic="", raw_data__statistic_id=code).update(
                statistic=code
            )

    for parameter, statistic in KEPT_BEFORE.items():
        Staging.objects.filter(
            statistic="", data_source__code="usgs", parameter_code=parameter
        ).update(statistic=statistic)


class Migration(migrations.Migration):

    dependencies = [
        ("datasync", "0007_usgs_water_data_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="datarecordstaging",
            name="statistic",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.RemoveConstraint(
            model_name="datarecordstaging",
            name="uniq_staging_station_param_obsdate",
        ),
        migrations.AddConstraint(
            model_name="datarecordstaging",
            constraint=models.UniqueConstraint(
                fields=["station", "parameter_code", "statistic", "observation_date"],
                name="uniq_staging_station_param_stat_obsdate",
            ),
        ),
        migrations.RunPython(set_statistics_on_old_rows, migrations.RunPython.noop),
    ]
