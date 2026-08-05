# SPDX-License-Identifier: AGPL-3.0-or-later
"""The front door must not offer an account that cannot be created (ISS-126).

Under the shipped default (``ACCESS_CONTROL_ENFORCED=True``) self-signup is
closed at ``core/adapters.py``, and the login page nevertheless said *"No
account yet? Create one"* and linked to allauth's own refusal page — which
answers "We are sorry, but the sign up is currently closed" and carries no link
of any kind. A district engineer who followed that invitation was told no and
given nowhere to go.

**Every assertion here is against a rendered response, not template source.**
The switch is read at request time by ``core/context_processors.py`` and by the
adapter, so reading the template file would prove only that a ``{% if %}`` was
typed, never that it fires.

The open posture is tested just as hard as the gated one: openh2o.com runs
``ACCESS_CONTROL_ENFORCED=False``, so a regression there breaks the public demo.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

SIGNUP = reverse("account_signup")
LOGIN = reverse("account_login")
RESET = reverse("account_reset_password")


def _body(response):
    return response.content.decode()


class TestTheLoginPageInvitation:
    @override_settings(ACCESS_CONTROL_ENFORCED=True)
    def test_the_gated_posture_does_not_offer_signup(self, client):
        body = _body(client.get(LOGIN))

        assert SIGNUP not in body, (
            "the login page still links to signup while self-registration is "
            "closed, so the invitation leads straight to a refusal"
        )
        assert "Create one" not in body

    @override_settings(ACCESS_CONTROL_ENFORCED=False)
    def test_the_open_posture_still_offers_signup(self, client):
        # This is the posture openh2o.com runs. A regression here removes the
        # public demo's way in.
        body = _body(client.get(LOGIN))

        assert SIGNUP in body, (
            "the open-signup posture lost its invitation to create an account, "
            "which is how visitors get into the public demo"
        )
        assert "Create one" in body


class TestTheRefusalPage:
    @override_settings(ACCESS_CONTROL_ENFORCED=True)
    def test_it_tells_the_reader_what_to_do_instead(self, client):
        response = client.get(SIGNUP)
        body = _body(response)

        assert response.status_code == 200
        assert f'href="{LOGIN}"' in body, (
            "the refusal page is a dead end: it does not link back to login"
        )
        assert f'href="{RESET}"' in body, (
            "the refusal page does not offer the password reset, which is what "
            "most people who land here actually need"
        )
        assert "administrator" in body.lower() or "runs this site" in body, (
            "the refusal page does not say who creates accounts, so it answers "
            "'no' without answering 'then what'"
        )
        assert "sign up is currently closed" not in body, (
            "allauth's own linkless page is still rendering — the override at "
            "templates/account/signup_closed.html is not being picked up"
        )

    @override_settings(ACCESS_CONTROL_ENFORCED=True)
    def test_it_wears_the_house_panel(self, client):
        # DESIGN.md: a lifted passage is a plain .card-raised, never a bespoke
        # accent box. Guards against the page drifting back to framework chrome.
        assert "card-raised" in _body(client.get(SIGNUP))

    @override_settings(ACCESS_CONTROL_ENFORCED=False)
    def test_signup_still_works_when_the_switch_is_off(self, client):
        response = client.get(SIGNUP)
        body = _body(response)

        assert response.status_code == 200
        assert f'action="{SIGNUP}"' in body, (
            "the open posture stopped serving a working signup form"
        )
