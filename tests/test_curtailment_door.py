# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-180 D6: a curtailment order's front door (146-02 Task 4).

Three doors proven here, RED against the unfixed tree (the exact quotes live
in 146-02-EVIDENCE.md Task 4): before this task, `/admin/` was the only way to
enter a `CurtailmentOrder` at all.

  1. A curtailment order can be created through a real form and the list
     shows it back (order id, title, effective/end dates, watershed,
     cutoff, status).
  2. The order can be edited through a real form.
  3. The nav carries a "Curtailment Orders" entry beside "Water Rights", and
     the list's header carries "+ Add order".
"""
from datetime import date

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.models import CurtailmentOrder

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"curtailmentuser{n}")
    email = factory.Sequence(lambda n: f"curtailmentuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. Create through the form
# ---------------------------------------------------------------------------


def test_create_through_form(auth_client):
    resp = auth_client.post(reverse("surface:curtailment_create"), {
        "order_id": "TEST-2026-99",
        "title": "Test order created through the door",
        "effective_date": "2026-01-01",
        "end_date": "",
        "watershed": "MERCED RIVER",
        "priority_date_cutoff": "1930-01-01",
        "status": "active",
        "notes": "",
    })
    assert resp.status_code == 302

    order = CurtailmentOrder.objects.get(order_id="TEST-2026-99")
    assert order.title == "Test order created through the door"
    assert order.effective_date == date(2026, 1, 1)
    assert order.watershed == "MERCED RIVER"
    assert order.priority_date_cutoff == date(1930, 1, 1)
    assert order.status == "active"


def test_list_shows_the_order_and_the_add_action(auth_client):
    CurtailmentOrder.objects.create(
        order_id="TEST-2026-01",
        title="A listed order",
        effective_date=date(2026, 1, 1),
        watershed="MERCED RIVER",
        priority_date_cutoff=date(1930, 1, 1),
        status="active",
    )

    resp = auth_client.get(reverse("surface:curtailments_list"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "TEST-2026-01" in content
    assert "A listed order" in content
    assert "+ Add order" in content


# ---------------------------------------------------------------------------
# 2. Edit through the form
# ---------------------------------------------------------------------------


def test_edit_changes_a_field(auth_client):
    order = CurtailmentOrder.objects.create(
        order_id="TEST-2026-02",
        title="Original title",
        effective_date=date(2026, 1, 1),
        watershed="MERCED RIVER",
        priority_date_cutoff=date(1930, 1, 1),
        status="active",
    )

    resp = auth_client.post(reverse("surface:curtailment_edit", args=[order.pk]), {
        "order_id": "TEST-2026-02",
        "title": "Edited title",
        "effective_date": "2026-01-01",
        "end_date": "",
        "watershed": "MERCED RIVER",
        "priority_date_cutoff": "1930-01-01",
        "status": "expired",
        "notes": "",
    })
    assert resp.status_code == 302

    order.refresh_from_db()
    assert order.title == "Edited title"
    assert order.status == "expired"


# ---------------------------------------------------------------------------
# 3. Login required; the nav entry
# ---------------------------------------------------------------------------


def test_list_requires_login():
    c = Client()
    resp = c.get(reverse("surface:curtailments_list"))
    assert resp.status_code == 302


def test_create_requires_login():
    c = Client()
    resp = c.get(reverse("surface:curtailment_create"))
    assert resp.status_code == 302


def test_nav_carries_a_curtailment_orders_entry_beside_water_rights(auth_client):
    # Water Rights and Curtailment Orders both live in the Administration
    # section (VISIBILITY_ADMIN_MODE), which only renders in the sidebar's
    # "admin" nav_mode -- the default test client cookie is "operations"
    # (core/context_processors.py::nav_mode), so this sets it explicitly
    # rather than asserting against a section that never renders.
    auth_client.cookies["nav_mode"] = "admin"
    resp = auth_client.get(reverse("surface:water_rights_list"))
    content = resp.content.decode()
    assert "Water Rights" in content
    assert "Curtailment Orders" in content
    assert reverse("surface:curtailments_list") in content
