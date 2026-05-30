# Generated for Phase 29 Plan 03: OpenET pre-fill storage on the submission.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0002_remove_reportsubmission_reviewer_notes_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportsubmission',
            name='prefill_overrides',
            field=models.JSONField(blank=True, default=dict, help_text="User-edited OpenET pre-fill values, keyed by entity+month (e.g. 'well:12:2024-03'). These are the agency's reviewed figures for data entry; they are NOT written back to the parcel ledger, so they never double-count against the et_estimate entries the generators read."),
        ),
    ]
