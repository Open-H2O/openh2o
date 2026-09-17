# SPDX-License-Identifier: AGPL-3.0-or-later
"""The setup wizard says why it sent the reader back, and counts basins and
flowlines apart instead of summing them (143-09, R-052, R-054).

`_seed_session` is `tests/test_setup_polish.py`'s own mechanism: sessions are
signed-cookie backed (ISS-069), so writing into `client.session` needs the
cookie refreshed from the saved session before the next request will see it.
"""
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import Client
from django.urls import reverse

from geography.models import Boundary
from tests.factories import FlowlineFactory, ZoneFactory

User = get_user_model()

SESSION_KEY_BOUNDARY = "setup_wizard_boundary_id"


def _admin():
    return User.objects.create_user(
        username="wizard-admin", email="wizard-admin@example.com", password="x",
        is_active=True, is_staff=True, is_superuser=True,
    )


def _admin_client():
    client = Client()
    client.force_login(_admin())
    return client


def _seed_session(client, **values):
    session = client.session
    for key, value in values.items():
        session[key] = value
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def _boundary(name="R052-Boundary"):
    return Boundary.objects.create(
        name=name,
        geometry=MultiPolygon(Polygon.from_bbox((-119.5, 36.0, -119.0, 36.5))),
    )


@pytest.mark.django_db
class TestTheWizardSaysWhyItSentYouBack:
    """R-054: a redirect to step 1 for a missing wizard session carries a
    sentence, not silence."""

    def test_confirm_with_no_session_lands_on_wizard_with_the_message(self):
        client = _admin_client()
        resp = client.get(reverse("setup:confirm"), follow=True)
        assert resp.redirect_chain[0][1] == 302
        assert resp.request["PATH_INFO"] == reverse("setup:wizard")
        body = resp.content.decode()
        assert "No boundary is confirmed for this session" in body
        assert "Choose or upload one, then confirm it" in body

    def test_run_with_no_session_lands_on_wizard_with_the_message(self):
        client = _admin_client()
        resp = client.get(reverse("setup:run"), follow=True)
        assert resp.request["PATH_INFO"] == reverse("setup:wizard")
        assert "No boundary is confirmed for this session" in resp.content.decode()

    def test_confirm_with_a_deleted_boundary_names_that_it_was_deleted(self):
        client = _admin_client()
        boundary = _boundary("R054-Deleted")
        _seed_session(client, **{SESSION_KEY_BOUNDARY: boundary.pk})
        boundary.delete()
        resp = client.get(reverse("setup:confirm"), follow=True)
        body = resp.content.decode()
        assert "The boundary this session chose no longer exists" in body


@pytest.mark.django_db
class TestBasinsAndFlowlinesCountApart:
    """R-052: 'Already inside this boundary' names two counts, in their own
    words, never summed into one figure under a label that names both."""

    def test_two_zones_three_flowlines_render_apart_not_summed(self):
        boundary = _boundary("R052-Two-Three")
        ZoneFactory.create_batch(2, boundary=boundary)
        FlowlineFactory.create_batch(3, boundary=boundary)

        client = _admin_client()
        _seed_session(client, **{SESSION_KEY_BOUNDARY: boundary.pk})
        resp = client.get(reverse("setup:confirm"))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "2 basins" in body
        assert "3 flowlines" in body
        # The old shape summed the two into one figure under "Existing data".
        assert "Existing data" not in body
        assert "5 basin" not in body
        assert ">5<" not in body
