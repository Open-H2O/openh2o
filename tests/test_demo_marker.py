# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo-honesty marker gating (Phase 64 Plan 01).

The Merced demo is shown to outside evaluators. A surface water-right in the
``curtailed``/``revoked`` state renders the real Water Board legal term, which an
evaluator could mistake for an actual curtailment order on what is sample data.
A flag-gated ``DEMO`` meta-label disambiguates it — but ONLY when
``SiteConfig.demonstration_mode`` is on, so a real production instance renders
exactly as before.

These tests lock the gate through the request path (so the
``core.context_processors.site_config`` processor actually runs — rendering the
partial directly would bypass it):

  - present iff demonstration_mode, AND
  - only on legal-action statuses (curtailed/revoked), never on ``active``, AND
  - real-instance output (flag off) keeps the original Status caption untouched.
"""

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core.models import SiteConfig
from tests.factories import WaterRightFactory


def _login():
    """A logged-in client (the detail view requires authentication)."""
    from core.models import User

    user = User.objects.create(
        username="evaluator",
        email="evaluator@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _detail_body(status, *, demonstration_mode):
    SiteConfig.objects.create(
        agency_name="Demo GSA", demonstration_mode=demonstration_mode
    )
    water_right = WaterRightFactory(status=status)
    client = _login()
    resp = client.get(reverse("surface:detail", args=[water_right.pk]))
    assert resp.status_code == 200
    return resp.content.decode()


@pytest.mark.django_db
class TestDemoMarkerGating:
    def test_curtailed_shows_marker_in_demo_mode(self):
        body = _detail_body("curtailed", demonstration_mode=True)
        assert "badge-demo" in body
        assert ">DEMO<" in body

    def test_revoked_shows_marker_in_demo_mode(self):
        body = _detail_body("revoked", demonstration_mode=True)
        assert "badge-demo" in body
        assert ">DEMO<" in body

    def test_active_never_shows_marker_even_in_demo_mode(self):
        # `active` does not read as a legal action — the marker must not appear.
        body = _detail_body("active", demonstration_mode=True)
        assert "badge-demo" not in body
        assert ">DEMO<" not in body

    def test_curtailed_no_marker_and_original_caption_on_real_instance(self):
        body = _detail_body("curtailed", demonstration_mode=False)
        # Real instance: no marker at all.
        assert "badge-demo" not in body
        assert ">DEMO<" not in body
        # And the Status caption is byte-for-byte the pre-Phase-64 text — the
        # demo-only clause must be absent.
        assert "Curtailed rights are temporarily restricted." in body
        assert "illustrative sample data" not in body
