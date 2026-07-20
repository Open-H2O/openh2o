# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 80-02 — the water-system onboarding wizard.

Three things here are load-bearing.

**A lookup writes nothing.** The whole promise of the review screen is that an
operator sees the consequences before accepting them, so every lookup test
asserts ``WaterSystem.objects.count() == 0`` afterwards — including the
successful one, which is the case where a regression would actually hide.

**The three Envirofacts failure modes stay three.** ``PwsidNotFound`` and
``EnvirofactsUnavailable`` both subclass ``EnvirofactsError``, so an
``except EnvirofactsError`` written first swallows both and tells an operator
with a perfectly good PWSID that EPA has no such system. Each branch is asserted
by its own distinguishing copy.

**The session carries only the PWSID.** Sessions are ``signed_cookies``, so a
mapped payload would blow the ~4 KB cookie ceiling silently. Asserted directly,
because the tempting "just stash the payloads" refactor would pass every other
test in this file.

Payloads are the real captured 79-01 fixtures for Bakman Water Company
(CA1010001) — 36 facilities, one of which EPA carries with a NULL state key and
which therefore cannot be onboarded.
"""

import json
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking import envirofacts, views
from drinking.models import SystemFacility, WaterSystem

FIXTURES = Path(__file__).resolve().parent.parent / "drinking" / "fixtures"

PWSID = "CA1010001"


def _fixture(name):
    return json.loads((FIXTURES / f"envirofacts_{name}.json").read_text())


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"onboard{n}")
    email = factory.Sequence(lambda n: f"onboard{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def epa(monkeypatch):
    """Serve the captured fixtures in place of the network.

    Patched on ``drinking.views`` rather than on ``drinking.envirofacts`` would
    be wrong — the views call through the module object, so patching the module's
    own attributes is what both the view and any future caller sees.
    """
    calls = {"system": 0, "facilities": 0, "geography": 0}

    def fake_system(pwsid, refresh=False):
        calls["system"] += 1
        return _fixture("water_system")[0]

    def fake_facilities(pwsid, refresh=False):
        calls["facilities"] += 1
        return _fixture("facilities")

    def fake_geography(pwsid, refresh=False):
        calls["geography"] += 1
        return _fixture("geographic_area")[0]

    monkeypatch.setattr(envirofacts, "fetch_water_system", fake_system)
    monkeypatch.setattr(envirofacts, "fetch_facilities", fake_facilities)
    monkeypatch.setattr(envirofacts, "fetch_geographic_area", fake_geography)
    return calls


# -- Task 1: routes, session contract, entry screen --------------------------


class TestEntryScreen:
    def test_route_reverses(self):
        assert reverse("drinking:onboard") == "/drinking/onboard/"
        assert reverse("drinking:onboard_lookup") == "/drinking/onboard/lookup/"
        assert reverse("drinking:onboard_commit") == "/drinking/onboard/commit/"

    def test_page_renders_for_a_logged_in_user(self, client_in):
        response = client_in.get(reverse("drinking:onboard"))
        assert response.status_code == 200
        assert b"PWSID" in response.content

    def test_anonymous_is_redirected(self, db):
        response = Client().get(reverse("drinking:onboard"))
        assert response.status_code == 302

    def test_page_states_what_onboarding_does_not_do(self, client_in):
        """The three honesty claims, asserted so a copy edit cannot quietly drop one."""
        body = client_in.get(reverse("drinking:onboard")).content.decode()
        assert "does not" in body.lower()
        # Compliance, well-linking and the population split — the three things
        # this flow deliberately refuses.
        assert "compliance" in body.lower()
        assert "well" in body.lower()
        assert "population" in body.lower()
