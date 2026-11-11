# SPDX-License-Identifier: AGPL-3.0-or-later
"""The production year table counts every record saved for a month and a source.

The add-month form offers a facility on each record and refuses a second record only for the
same facility, so two wells' groundwater for one month can both be saved. The year table and
the year's total must then read what was saved: 100 and 250 gallons make 350.
"""

from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from drinking.models import SystemProduction
from drinking.views.production import _production_table_context
from tests.factories import SystemFacilityFactory, WaterSystemFactory

pytestmark = pytest.mark.django_db


@pytest.mark.xfail(
    strict=True,
    reason="Whether the table adds a month's records for a source or a month holds one record "
    "per source is for the maintainer to rule.",
)
def test_two_wells_in_one_month_both_count_in_the_year():
    user = get_user_model().objects.create_user(
        username="operator", email="operator@example.org", password="a-good-passw0rd",
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    system = WaterSystemFactory()
    for name, facility_id, gallons in (("Well 7 (invented)", "007", "100"), ("Well 8 (invented)", "008", "250")):
        well = SystemFacilityFactory(system=system, name=name, facility_id=facility_id)
        response = client.post(reverse("drinking:production_add"), {
            "year": 2025, "month": 3, "type_code": "GW", "facility": well.pk,
            "volume_as_reported": gallons, "unit_as_reported": "G", "notes": "",
        })
        assert response.status_code == 302
    assert SystemProduction.objects.current().filter(system=system, month=3).count() == 2

    context = _production_table_context(system, 2025)

    groundwater = next(t for t in context["totals"] if t["type_code"] == "GW")
    assert (groundwater["gallons"], context["grand_total_gallons"]) == (D("350"), D("350"))
