# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-195: a recharge event before any water year exists is a page, not a crash.

`recharge/views.py::_recharge_site_detail_context` groups a site's events by
`ReportingPeriod`; an event outside every period's range (or, as here, a
database with no `ReportingPeriod` at all) closes into a single trailing
"Outside any water year on record" group whose `period_key` is `None`
(`_group_recharge_events`). Before this fix, `current_totals` could resolve
to that group and the `later.index(current_totals)` lookup on the very next
line raised `ValueError`, because `later` excludes every group whose
`period_key` is `None` -- including `current_totals` itself. Reproduced on
a fresh instance's first recharge event (145-02 walk of shape 5); the fix
is the missing case, not the water year: `previous_totals` is computed only
when `current_totals["period_key"] is not None`.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    RechargeEventFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db

_login_count = 0


def _login():
    from core.models import User

    global _login_count
    _login_count += 1
    user = User.objects.create(
        username=f"noperiodreader{_login_count}",
        email=f"noperiodreader{_login_count}@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


class TestRechargeSitePageWithoutAnyReportingPeriod:
    """A site's first event, logged before any water year exists on the
    instance, renders the page instead of raising ValueError (ISS-195)."""

    def test_one_event_no_reporting_period_renders_200_and_lists_the_event(self):
        site = RechargeSiteFactory()
        RechargeEventFactory(
            recharge_site=site,
            start_date=date(2026, 3, 1),
            volume_acre_feet=Decimal("42.0000"),
        )

        response = _login().get(reverse("recharge:detail", args=[site.pk]))

        assert response.status_code == 200
        html = response.content.decode()
        assert "42.00" in html


class TestRechargeSitePagePeerYearStillRendersWithAPeriod:
    """A site whose event DOES fall inside a ReportingPeriod still gets its
    peer ('water year before') computed as today -- this fix touches only
    the no-period case."""

    def test_event_inside_a_period_still_renders_with_its_peer(self):
        current = ReportingPeriodFactory(
            name="WY 2025-2026", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        prior = ReportingPeriodFactory(
            name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
        )
        site = RechargeSiteFactory()
        RechargeEventFactory(
            recharge_site=site,
            start_date=date(2026, 1, 1),
            volume_acre_feet=Decimal("15.0000"),
        )
        RechargeEventFactory(
            recharge_site=site,
            start_date=date(2025, 1, 1),
            volume_acre_feet=Decimal("9.0000"),
        )

        response = _login().get(reverse("recharge:detail", args=[site.pk]))

        assert response.status_code == 200
        html = response.content.decode()
        assert "15.00" in html
        assert "9.00" in html
        assert current.name in html
        assert prior.name in html
