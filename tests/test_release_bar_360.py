# SPDX-License-Identifier: AGPL-3.0-or-later
"""A zone's basin recharge pool holds the recharge recorded at the sites in that zone now.

A recharge site's zone is set on the site's page and can be corrected at any time. When it
changes, the volume of the site's events moves from the old zone's pool to the new zone's,
except in a finalized year, which stays as it was filed. Voiding an event later takes its
volume back out of the pool it is in: never out of a pool it never joined.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import AccountCredit, AllocationCarryover, ReportingPeriod, WaterAccount
from accounting.services import leave_behind_share
from recharge.models import RechargeEvent
from tests import ledger_districts as ld
from tests.factories import RechargeSiteFactory, ReportingPeriodFactory, ZoneFactory

pytestmark = pytest.mark.django_db

REASON = "logged at the wrong basin"


@pytest.fixture
def client():
    user = get_user_model().objects.create_user(
        username="operator", email="operator@example.org", password="a-good-passw0rd",
        is_active=True, first_name="Jose", last_name="Lopez",
    )
    c = Client()
    c.force_login(user)
    return c


def _pool(zone):
    return sum(
        (row.amount_af for row in AllocationCarryover.objects.filter(zone=zone, origin="basin_recharge_pool")),
        D("0"),
    )


def _credits(account):
    return sum(
        (row.amount_af for row in AccountCredit.objects.filter(water_account=account, origin="managed_recharge")),
        D("0"),
    )


def _set_zone(client, site, zone):
    response = client.post(
        reverse("recharge:site_zone", args=[site.pk]), {"zone": zone.pk if zone else ""}
    )
    assert response.status_code == 302
    site.refresh_from_db()


def _log(client, site, volume, start="2025-08-01", end="2025-08-31"):
    response = client.post(
        reverse("recharge:event_create", args=[site.pk]),
        {
            "start_date": start, "end_date": end,
            "volume_acre_feet": volume, "water_type": ld.wt("GW").pk,
            "source_description": "", "notes": "",
        },
    )
    assert response.status_code == 200
    return RechargeEvent.objects.filter(recharge_site=site).order_by("-pk").first()


def _void(client, event):
    response = client.post(
        reverse("core:record_void", args=["recharge_event", event.pk]), {"void_reason": REASON}
    )
    assert response.status_code == 200


def _finalize(start, end):
    period = ReportingPeriodFactory(name="Closed WY", start_date=start, end_date=end)
    ReportingPeriod.objects.filter(pk=period.pk).update(is_finalized=True)


@pytest.fixture
def zones():
    ld.seed_reference()
    return ZoneFactory(name="Zone A (invented)"), ZoneFactory(name="Zone B (invented)")


@pytest.fixture
def account():
    return WaterAccount.objects.create(name="Basin Account (invented)", account_number="BA-1", unit_kind="farm_unit")


def test_a_corrected_zone_takes_the_recorded_recharge_with_it(client, zones):
    zone_a, zone_b = zones
    site = RechargeSiteFactory()
    _set_zone(client, site, zone_a)
    event = _log(client, site, "50")
    assert _pool(zone_a) == D("50")

    _set_zone(client, site, zone_b)

    assert _pool(zone_a) == D("0")
    assert _pool(zone_b) == D("50")

    _void(client, event)

    assert _pool(zone_a) == D("0")
    assert _pool(zone_b) == D("0")


def test_a_zone_set_later_takes_in_the_recharge_already_recorded(client, zones):
    zone_a, _ = zones
    site = RechargeSiteFactory()
    event = _log(client, site, "50")
    assert _pool(zone_a) == D("0")

    _set_zone(client, site, zone_a)

    assert _pool(zone_a) == D("50")

    _void(client, event)

    assert _pool(zone_a) == D("0")


def test_a_finalized_year_keeps_its_recharge_where_it_was_filed(client, zones):
    zone_a, zone_b = zones
    site = RechargeSiteFactory()
    _set_zone(client, site, zone_a)
    _log(client, site, "50", start="2024-03-01", end="2024-03-31")
    _log(client, site, "30")
    _finalize(dt.date(2023, 10, 1), dt.date(2024, 9, 30))

    _set_zone(client, site, zone_b)

    assert _pool(zone_a) == D("50")
    assert _pool(zone_b) == D("30")


def test_a_zone_corrected_from_one_zone_to_another_leaves_the_account_credit_as_it_was(
    client, zones, account
):
    zone_a, zone_b = zones
    site = RechargeSiteFactory(water_account=account)
    _set_zone(client, site, zone_a)
    _log(client, site, "50")
    before = _credits(account)
    assert before == D("50") * (1 - leave_behind_share())

    _set_zone(client, site, zone_b)

    assert _credits(account) == before
    assert AccountCredit.objects.filter(water_account=account).count() == 1


def test_a_zone_set_later_credits_the_account_as_logging_would(client, zones, account):
    zone_a, _ = zones
    site = RechargeSiteFactory(water_account=account)
    _log(client, site, "50")
    assert _credits(account) == D("0")

    _set_zone(client, site, zone_a)

    assert _credits(account) == D("50") * (1 - leave_behind_share())


def test_a_zone_cleared_takes_the_recharge_out_of_the_pool_and_the_credit_back(client, zones, account):
    zone_a, _ = zones
    site = RechargeSiteFactory(water_account=account)
    _set_zone(client, site, zone_a)
    _log(client, site, "50")

    _set_zone(client, site, None)

    assert _pool(zone_a) == D("0")
    assert _credits(account) == D("0")


def test_the_admin_sites_zone_change_moves_the_recharge_too(zones, rf):
    from django.contrib.admin.sites import site as admin_site

    from recharge.admin import RechargeSiteAdmin
    from recharge.models import RechargeSite

    zone_a, zone_b = zones
    site = RechargeSiteFactory(zone=zone_a)
    ld.log_event(site, dt.date(2025, 8, 1), dt.date(2025, 8, 31), "50", "GW")
    assert _pool(zone_a) == D("50")

    site = RechargeSite.objects.get(pk=site.pk)
    site.zone = zone_b
    RechargeSiteAdmin(RechargeSite, admin_site).save_model(rf.post("/"), site, form=None, change=True)

    assert _pool(zone_a) == D("0")
    assert _pool(zone_b) == D("50")


def test_an_administrator_voiding_a_finalized_years_event_takes_it_from_the_zone_it_was_filed_in(
    client, zones, settings
):
    zone_a, zone_b = zones
    site = RechargeSiteFactory()
    _set_zone(client, site, zone_a)
    closed_event = _log(client, site, "50", start="2024-03-01", end="2024-03-31")
    _finalize(dt.date(2023, 10, 1), dt.date(2024, 9, 30))
    _set_zone(client, site, zone_b)

    settings.ACCESS_CONTROL_ENFORCED = True
    boss = get_user_model().objects.create_user(
        username="boss", email="boss@example.org", password="a-good-passw0rd",
        is_active=True, agency_admin=True,
    )
    admin_client = Client()
    admin_client.force_login(boss)
    _void(admin_client, closed_event)

    assert _pool(zone_a) == D("0")
    assert _pool(zone_b) == D("0")
