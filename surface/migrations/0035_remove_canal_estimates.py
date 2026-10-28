from django.db import migrations
from django.db.models import Q


def remove_open_year_estimates(apps, schema_editor):
    """Delete the records the retired crop-need estimate wrote, in every year that is not finalized.

    A record in a finalized year stays: the database lock refuses to change it,
    and the migration does not override the lock. A record counts as finalized
    when its water year link or its month falls inside a finalized water year,
    which is how the lock reads it.
    """
    DiversionRecord = apps.get_model("surface", "DiversionRecord")
    ReportingPeriod = apps.get_model("accounting", "ReportingPeriod")
    in_finalized_year = Q(reporting_period__is_finalized=True)
    for start, end in ReportingPeriod.objects.filter(is_finalized=True).values_list(
        "start_date", "end_date"
    ):
        in_finalized_year |= Q(month__gte=start, month__lte=end)
    DiversionRecord.objects.filter(method="estimated_from_use").exclude(
        in_finalized_year
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("surface", "0034_canalmonthloss_unserved_af"),
        ("accounting", "0037_finalized_lock_reads_water_year_start"),
    ]

    operations = [
        migrations.RunPython(remove_open_year_estimates, migrations.RunPython.noop),
    ]
