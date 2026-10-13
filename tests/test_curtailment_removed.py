# SPDX-License-Identifier: AGPL-3.0-or-later
"""Curtailment is not a feature of OpenH2O (150.5-01).

Brent, 2026-10-12 17:40 PDT: "I don't understand the value of having curtailment
involved with OpenH2O at all. I don't see how this helps a water manager or the
water balance."; 17:47: "Lets get rid fo curtailments entirely." The order's one
effect on a figure, no estimate for an unmetered point in a month it covered, is
what a typed delivery record of 0 does (tests/test_diversion_estimate.py).

The lines that changed with it were approved at 19:17 ("looks good", the help
sentence) and 19:24 ("approved", the rest).
"""
import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, reverse

from surface.models import WaterRight
from tests.factories import WaterRightFactory

pytestmark = pytest.mark.django_db

_migration = importlib.import_module("surface.migrations.0026_remove_curtailments")


@pytest.fixture
def client_in():
    user = get_user_model().objects.create_user(
        username="no-curtailment", email="nc@example.com", password="x-nc-pass-1",
        is_staff=True, is_superuser=True,
    )
    c = Client()
    c.force_login(user)
    return c


def test_a_curtailed_right_becomes_active():
    right = WaterRightFactory(status="active")
    WaterRight.objects.filter(pk=right.pk).update(status="curtailed")

    _migration.curtailed_to_active(django_apps, None)

    right.refresh_from_db()
    assert right.status == "active"


def test_the_status_choices_carry_no_curtailed():
    assert "curtailed" not in dict(WaterRight.STATUS_CHOICES)


def test_no_order_model_and_no_route():
    with pytest.raises(LookupError):
        django_apps.get_model("surface", "CurtailmentOrder")
    for name in ("surface:curtailments_list", "surface:curtailment_create"):
        with pytest.raises(NoReverseMatch):
            reverse(name)


def test_the_orders_page_is_gone(client_in):
    assert client_in.get("/surface/curtailments/").status_code == 404


def test_the_help_sentence_is_the_approved_one(client_in):
    body = client_in.get(reverse("methods")).content.decode()
    # Replaced 2026-10-13 08:17 PDT (Brent "yes, approved", 150.1-02 screen 8)
    # when a diversion with no linked right began to be estimated.
    assert (
        "OpenH2O estimates no delivery at a diversion whose water right is "
        "inactive or revoked."
    ) in body
    assert "curtail" not in body.lower()


def test_the_water_rights_page_description_is_the_approved_one(client_in):
    body = client_in.get(reverse("surface:water_rights_list")).content.decode()
    assert "The right's page also lists its diversion records.</p>" in body
    assert "curtail" not in body.lower()


def test_the_glossary_has_no_curtailment_entry(client_in):
    body = client_in.get(reverse("glossary")).content.decode()
    assert "One record per State Water Board order" not in body


def test_a_right_page_has_no_orders_panel(client_in):
    right = WaterRightFactory(status="active")
    body = client_in.get(reverse("surface:detail", args=[right.pk])).content.decode()
    assert "Curtailment orders that may apply" not in body
    assert "curtail" not in body.lower()
