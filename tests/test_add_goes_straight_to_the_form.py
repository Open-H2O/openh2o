# SPDX-License-Identifier: AGPL-3.0-or-later
"""The "+ Add" buttons land on the form for the thing they name.

**The defect this pins (ISS-134, reported by Brent 2026-08-27).** Clicking
"+ Add well" went to `/infrastructure/add/?type=well`, which honoured the type
— "Groundwater well" arrived pre-selected — and then showed a four-card
"Infrastructure type" picker anyway, under a heading that said "Add Well" and a
subtitle that said "Add a single well, diversion, storage, or recharge site".
The page asked a question the URL had already answered, and contradicted itself
doing it.

**The trap in removing the picker, which is what the last test here guards.**
`storage` had no "+ Add" button anywhere in the application. The four-card
picker was its ONLY route in, so deleting the picker without giving storage a
front door would have made a whole infrastructure type unreachable. It now has
a button on Recharge Areas, which is the page that already lists it
(`ADD_TYPE_BACK["storage"]` points there, and `recharge_sites_list` filters on
nothing).
"""
import re

import pytest
from django.test import Client
from django.urls import reverse

from infrastructure.views import ADD_TYPE_LONG_LABEL, supported_add_types

# Each list page's primary add button, and the type it must land on.
ADD_ENTRY_POINTS = [
    ("/wells/", "well"),
    ("/surface/", "diversion"),
    ("/recharge/", "recharge_site"),
    ("/recharge/", "storage"),
]


@pytest.fixture
def client_admin(db, django_user_model):
    user = django_user_model.objects.create_superuser(
        username="add-probe", email="add-probe@example.gov", password="pw-not-a-secret-12345"
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.parametrize("list_path,infra_type", ADD_ENTRY_POINTS)
def test_the_list_page_links_straight_to_that_type(client_admin, list_path, infra_type):
    """Every type reachable by a button, and the button carries its own type."""
    body = client_admin.get(list_path).content.decode()
    assert f"?type={infra_type}" in body, (
        f"{list_path} has no add link for type={infra_type}"
    )


@pytest.mark.parametrize("infra_type", ["well", "diversion", "storage", "recharge_site"])
def test_the_add_page_does_not_ask_which_type(client_admin, infra_type):
    """No picker. The type is a hidden input, not a radio group."""
    body = client_admin.get(f"/infrastructure/add/?type={infra_type}").content.decode()
    assert "infra-type-card" not in body, "the four-card type picker is back"
    assert "Infrastructure type" not in body, "the picker's heading is back"
    assert 'type="radio" name="infra_type"' not in body, "infra_type is a radio again"
    assert f'<input type="hidden" name="infra_type" value="{infra_type}">' in body


@pytest.mark.parametrize("infra_type", ["well", "diversion", "storage", "recharge_site"])
def test_the_page_describes_the_type_it_is_adding(client_admin, infra_type):
    """The subtitle names this type, and no longer lists all four.

    This is the half that made the page read as generic: the heading said one
    thing and the sentence under it said another.
    """
    body = client_admin.get(f"/infrastructure/add/?type={infra_type}").content.decode()
    assert f"Add a {ADD_TYPE_LONG_LABEL[infra_type]} and place it on the map." in body
    assert "Add a single well, diversion, storage, or recharge site" not in body


def test_the_switch_offers_every_other_type_and_never_this_one(client_admin):
    """The way across is still there, so nobody is stranded on the wrong form."""
    for infra_type in supported_add_types():
        body = client_admin.get(f"/infrastructure/add/?type={infra_type}").content.decode()
        offered = set(re.findall(r'href="\?type=([a-z_]+)"', body))
        expected = set(supported_add_types()) - {infra_type}
        assert offered == expected, (
            f"on ?type={infra_type} the switch offers {offered}, expected {expected}"
        )


def test_storage_has_a_front_door_of_its_own(client_admin):
    """The regression that removing the picker could have caused.

    Before 2026-08-27 nothing in the application linked to `?type=storage`; the
    picker was the only way to reach it. If this fails, a whole infrastructure
    type is unreachable from the UI again.
    """
    body = client_admin.get(reverse("recharge:list")).content.decode()
    assert "?type=storage" in body, "storage pond has no add button anywhere"
