# SPDX-License-Identifier: AGPL-3.0-or-later
# Hand-written (no local Django runtime): adds the agency-wide delivery
# accounting policy fields to SiteConfig (Phase 55-02). Both carry defaults, so
# the existing live demo's singleton SiteConfig reads sensible values on migrate
# with zero behavior change (efficiency 0.750, recovery horizon carry_forward =
# the historic rollover behavior).
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteconfig',
            name='default_irrigation_efficiency',
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal('0.750'),
                help_text='Share of delivered water the crop actually consumes; '
                'the rest returns to the aquifer as recharge.',
                max_digits=4,
            ),
        ),
        migrations.AddField(
            model_name='siteconfig',
            name='default_recovery_horizon',
            field=models.CharField(
                choices=[
                    ('carry_forward', 'Carry unused water forward as a credit'),
                    ('same_water_year', 'Unused water expires at year-end'),
                ],
                default='carry_forward',
                help_text="What happens to a district's unused water budget at "
                'year-end (agency-wide default; a district may override it).',
                max_length=16,
            ),
        ),
    ]
