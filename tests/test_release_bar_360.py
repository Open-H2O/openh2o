# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voiding a recharge event takes its water out of the pool it went into, and no other.

A recharge site's zone is set on the site's page and can be changed or cleared at any time.
An event's volume goes into the basin recharge pool of the zone the site had when the event was
saved (or none, when the site had no zone). Voiding the event later must take the volume back
out of that same pool: never out of a pool it never joined.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import AllocationCarryover
from recharge.models import RechargeEvent
from tests import ledger_districts as ld
from tests.factories import RechargeSiteFactory, ZoneFactory

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.xfail(
        strict=True,
        reason="The pool an event's volume went into is stored nowhere today; how to keep it, "
        "and what to do for events already saved, is for the maintainer to rule.",
    ),
]

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


def _set_zone(client, site, zone):
    response = client.post(
        reverse("recharge:site_zone", args=[site.pk]), {"zone": zone.pk if zone else ""}
    )
    assert response.status_code == 302


def _log(client, site, volume):
    response = client.post(
        reverse("recharge:event_create", args=[site.pk]),
        {
            "start_date": "2025-08-01", "end_date": "2025-08-31",
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


@pytest.fixture
def zones():
    ld.seed_reference()
    return ZoneFactory(name="Zone A (invented)"), ZoneFactory(name="Zone B (invented)")


def test_a_site_moved_to_another_zone_voids_from_the_zone_the_event_joined(client, zones):
    zone_a, zone_b = zones
    site = RechargeSiteFactory()
    _set_zone(client, site, zone_a)
    event = _log(client, site, "50")
    assert _pool(zone_a) == D("50")
    _set_zone(client, site, zone_b)

    _void(client, event)

    assert _pool(zone_a) == D("0")
    assert _pool(zone_b) == D("0")


def test_an_event_saved_with_no_zone_takes_nothing_from_a_zone_set_later(client, zones):
    zone_a, _ = zones
    site = RechargeSiteFactory()
    event = _log(client, site, "50")
    assert _pool(zone_a) == D("0")
    _set_zone(client, site, zone_a)

    _void(client, event)

    assert _pool(zone_a) == D("0")


def test_an_event_the_demonstration_pooled_to_a_zone_the_site_does_not_name_is_taken_back(client, zones):
    """The demonstration's loader pools each basin's events to the zone around it and leaves the
    site's own zone blank, so the event's pool is not the site's zone."""
    from accounting.services import create_recharge_ledger_entries

    zone_a, _ = zones
    site = RechargeSiteFactory()
    event = RechargeEvent.objects.create(
        recharge_site=site, start_date=dt.date(2025, 8, 1), end_date=dt.date(2025, 8, 31),
        volume_acre_feet=D("50"), water_type=ld.wt("GW"),
    )
    create_recharge_ledger_entries(event, zone=zone_a)
    assert _pool(zone_a) == D("50")

    _void(client, event)

    assert _pool(zone_a) == D("0")
