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


# -- Task 2: lookup + review -------------------------------------------------


class TestLookupReview:
    def test_review_shows_the_system_and_its_facilities(self, client_in, epa):
        response = client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": PWSID})
        body = response.content.decode()

        assert response.status_code == 200
        assert "BAKMAN WATER COMPANY" in body.upper()
        assert PWSID in body
        # 36 in EPA's payload, 35 writable — the one gap this screen exists to show.
        assert "36" in body
        assert "35" in body
        # The state key is what a PS Code is built from, so it is what is shown.
        assert "010" in body

    def test_the_skipped_facility_is_named_with_a_reason(self, client_in, epa):
        """CA1010001001 "WELL 01 - INACTIVE" has a NULL state key in EPA's own data.

        Silently dropping it would leave an operator believing EPA sent 35
        facilities. The reason has to be on the screen, not in a log line.
        """
        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()

        assert "skipped" in body.lower()
        assert "state_facility_id" in body

    def test_a_lookup_writes_nothing(self, client_in, epa):
        """The successful path is the one where a stray save would hide."""
        client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": PWSID})

        assert WaterSystem.objects.count() == 0
        assert SystemFacility.objects.count() == 0

    def test_the_session_holds_only_the_pwsid(self, client_in, epa):
        """The cookie-ceiling contract, asserted directly.

        Sessions are signed_cookies, so stashing the mapped payloads here would
        silently truncate or drop the cookie rather than raise. Every other test
        in this file would still pass.
        """
        client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": PWSID})

        session = dict(client_in.session)
        assert session[views.SESSION_KEY_ONBOARD_PWSID] == PWSID
        assert [k for k in session if k.startswith("drinking_onboard")] == [
            views.SESSION_KEY_ONBOARD_PWSID
        ]

    def test_pwsid_is_normalized(self, client_in, epa):
        client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "  ca1010001 "})
        assert client_in.session[views.SESSION_KEY_ONBOARD_PWSID] == PWSID

    def test_an_already_onboarded_system_reads_as_a_refresh(self, client_in, epa):
        WaterSystem.objects.create(pwsid=PWSID, name="Already here")

        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()

        assert "refresh" in body.lower()
        assert "Refresh" in body  # the commit button says which act it performs

    def test_a_new_system_reads_as_a_create(self, client_in, epa):
        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()
        assert "New system" in body
        assert "Create" in body

    def test_epa_totals_are_shown_but_not_written(self, client_in, epa):
        """The aggregate is a fact worth showing; splitting it would be invention."""
        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()

        assert "Population served (EPA total)" in body
        assert "Shown, not written" in body

    def test_the_mailing_state_is_never_called_the_regulating_state(self, client_in, epa):
        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()

        assert "Mailing address" in body
        assert "regulating state" not in body.lower()

    def test_no_pwsid_asks_for_one(self, client_in, epa):
        response = client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "   "})
        assert response.status_code == 200
        assert "Enter a PWSID" in response.content.decode()


class TestLookupFailureModes:
    """Three exceptions, three screens. Specific-first, or two of them collapse."""

    def _raise(self, monkeypatch, exc):
        def boom(pwsid, refresh=False):
            raise exc

        monkeypatch.setattr(envirofacts, "fetch_water_system", boom)

    def test_unknown_pwsid_says_so_without_blaming_epa(self, client_in, monkeypatch):
        self._raise(monkeypatch, envirofacts.PwsidNotFound("CA9999999"))

        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": "CA9999999"}
        ).content.decode()

        assert "No system with that PWSID" in body
        assert "not a sign that EPA is down" in body
        assert WaterSystem.objects.count() == 0

    def test_a_timeout_never_reads_as_not_found(self, client_in, monkeypatch):
        """The failure that matters most: a good id must not be called nonexistent."""
        self._raise(
            monkeypatch,
            envirofacts.EnvirofactsUnavailable("EPA's service did not respond in time."),
        )

        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()

        assert "EPA did not answer in time" in body
        assert "may be perfectly good" in body
        assert "No system with that PWSID" not in body
        assert WaterSystem.objects.count() == 0

    def test_a_service_error_blames_neither_the_operator_nor_the_id(
        self, client_in, monkeypatch
    ):
        self._raise(
            monkeypatch,
            envirofacts.EnvirofactsError("WATER_SYSTEM: The table is not available."),
        )

        body = client_in.post(
            reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
        ).content.decode()

        assert "EPA answered with an error" in body
        assert "The table is not available." in body
        assert "No system with that PWSID" not in body
        assert WaterSystem.objects.count() == 0

    def test_the_three_screens_are_actually_distinct(self, client_in, monkeypatch):
        """Guards the specific-first ordering itself, not just one branch of it."""
        bodies = []
        for exc in (
            envirofacts.PwsidNotFound(PWSID),
            envirofacts.EnvirofactsUnavailable("timeout"),
            envirofacts.EnvirofactsError("bad envelope"),
        ):
            self._raise(monkeypatch, exc)
            bodies.append(
                client_in.post(
                    reverse("drinking:onboard_lookup"), {"pwsid": PWSID}
                ).content.decode()
            )

        assert len(set(bodies)) == 3

    def test_a_failed_lookup_leaves_no_pwsid_in_the_session(self, client_in, monkeypatch):
        self._raise(monkeypatch, envirofacts.PwsidNotFound(PWSID))
        client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": PWSID})
        assert views.SESSION_KEY_ONBOARD_PWSID not in client_in.session
