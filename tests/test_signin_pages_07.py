# SPDX-License-Identifier: AGPL-3.0-or-later
"""Being told why, signing in from a link, and a server error page.

Three things a person meets at the edges of the app:

* A viewer or an operator sent away from an administrator screen lands on Home
  and is told why, once, on every module set (Home is the one page every set
  has).
* A link to a page, followed while signed out, still lands on that page after
  sign-in, and only when the address is on this site.
* An unhandled error shows a page of OpenH2O's own, built without a database
  query, a request or a context processor.
"""
import inspect
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import path, reverse

from core import access
from tests.factories import ReportingPeriodFactory

pytestmark = pytest.mark.django_db

User = get_user_model()

SENTENCE = "That screen is for administrators."
PASSWORD = "a-good-passw0rd"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password=PASSWORD,
        is_active=True,
        **flags,
    )


def _client(user):
    client = Client(SERVER_NAME="localhost")
    client.force_login(user)
    return client


# -- Told why ------------------------------------------------------------


@pytest.mark.parametrize("role", [{"read_only": True}, {}], ids=["viewer", "operator"])
@pytest.mark.parametrize("screen", ["core:users_list", "setup:wizard"])
def test_a_refused_person_lands_on_home_and_is_told_once(role, screen):
    with override_settings(ACCESS_CONTROL_ENFORCED=True):
        client = _client(_user("someone", **role))
        response = client.get(reverse(screen))
        assert response.status_code == 302
        assert response["Location"] == "/"
        home = client.get(response["Location"])
    assert home.status_code == 200
    assert home.content.decode().count(SENTENCE) == 1


def test_the_refusal_does_not_reverse_a_water_accounting_address():
    source = inspect.getsource(access.admin_required)
    assert "accounting:" not in source
    assert "accounting:" not in inspect.getsource(access)


class _AddsAMessage:
    """Puts one message on every request, after the messages middleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib import messages

        messages.success(request, "A probe sentence for the page.")
        return self.get_response(request)


def _middleware_with_probe():
    from django.conf import settings

    middleware = list(settings.MIDDLEWARE)
    at = middleware.index("django.contrib.messages.middleware.MessageMiddleware")
    middleware.insert(at + 1, f"{__name__}._AddsAMessage")
    return middleware


def _pages():
    period = ReportingPeriodFactory()
    return [
        reverse("accounting:delivery_settings"),
        reverse("accounting:ledger_list"),
        reverse("accounting:period_detail", args=[period.pk]),
        reverse("profile"),
        reverse("core:users_list"),
        reverse("drinking:onboard"),
        reverse("setup:demonstration"),
        reverse("setup:wizard"),
    ]


def test_each_page_that_placed_messages_shows_one_exactly_once():
    user = _user("boss", is_staff=True, is_superuser=True)
    client = _client(user)
    with override_settings(MIDDLEWARE=_middleware_with_probe()):
        pages = _pages()
        shown = {}
        for url in pages:
            response = client.get(url)
            assert response.status_code == 200, url
            shown[url] = response.content.decode().count("A probe sentence for the page.")
    assert shown == {url: 1 for url in pages}


def test_a_page_with_no_override_shows_a_message_once_from_the_base_page():
    # Home places no messages of its own: the base page shows it.
    client = _client(_user("boss", is_staff=True, is_superuser=True))
    with override_settings(MIDDLEWARE=_middleware_with_probe()):
        html = client.get("/").content.decode()
    assert html.count("A probe sentence for the page.") == 1


# -- Signing in from a link ---------------------------------------------

LINK = "/help/water-balances/"


def _account():
    return _user("walker")


def test_the_login_form_carries_the_address_it_was_opened_with():
    html = Client(SERVER_NAME="localhost").get(f"/accounts/login/?next={LINK}").content.decode()
    assert re.search(
        r'<input[^>]*type="hidden"[^>]*name="next"[^>]*value="%s"' % re.escape(LINK), html
    ) or re.search(
        r'<input[^>]*name="next"[^>]*value="%s"[^>]*type="hidden"' % re.escape(LINK), html
    )


def test_the_login_form_without_an_address_carries_no_field():
    html = Client(SERVER_NAME="localhost").get("/accounts/login/").content.decode()
    assert 'name="next"' not in html


def test_signing_in_from_a_link_lands_on_the_linked_page():
    _account()
    response = Client(SERVER_NAME="localhost").post(
        "/accounts/login/", {"login": "walker@example.org", "password": PASSWORD, "next": LINK}
    )
    assert response.status_code == 302
    assert response["Location"] == LINK


# A site's own address list decides what counts as "this site". The local
# settings default to accepting any address (["*"]), which the sign-in's check
# then also accepts, so the test names the one address a real site would list.
@override_settings(ALLOWED_HOSTS=["localhost"])
def test_an_address_on_another_site_lands_on_home():
    _account()
    response = Client(SERVER_NAME="localhost").post(
        "/accounts/login/",
        {"login": "walker@example.org", "password": PASSWORD, "next": "https://example.com/"},
    )
    assert response.status_code == 302
    assert response["Location"] == "/"


def test_the_google_link_carries_the_address():
    from tests.test_google_sign_in_switch import CREDENTIALS_SET, set_flag

    set_flag(True)
    with override_settings(SOCIALACCOUNT_PROVIDERS=CREDENTIALS_SET):
        html = (
            Client(SERVER_NAME="localhost")
            .get(f"/accounts/login/?next={LINK}")
            .content.decode()
        )
    link = re.search(r'href="([^"]*google/login/[^"]*)"', html)
    assert link, "the Google link is not on the page"
    assert "next=%2Fhelp%2Fwater-balances%2F" in link.group(1).replace("&amp;", "&")


def test_a_first_sign_in_keeps_the_linked_page_through_choosing_a_password():
    user = _account()
    user.must_choose_password = True
    user.save(update_fields=["must_choose_password"])
    client = Client(SERVER_NAME="localhost")
    response = client.post(
        "/accounts/login/", {"login": "walker@example.org", "password": PASSWORD, "next": LINK}
    )
    assert response.status_code == 302
    follow = client.get(response["Location"])
    assert follow.status_code == 302
    assert follow["Location"] == reverse("choose_password")
    done = client.post(
        reverse("choose_password"),
        {"password1": "another-good-passw0rd-9", "password2": "another-good-passw0rd-9"},
    )
    assert done.status_code == 302
    assert done["Location"] == LINK


# -- A server error ------------------------------------------------------


def _boom(request):
    raise RuntimeError("probe failure")


urlpatterns = [path("boom/", _boom)]


@override_settings(DEBUG=False, ROOT_URLCONF=__name__)
def test_an_unhandled_error_shows_the_site_own_page():
    response = Client(SERVER_NAME="localhost", raise_request_exception=False).get("/boom/")
    html = response.content.decode()
    assert response.status_code == 500
    assert "<h1" in html and "Server error" in html
    assert 'href="/"' in html
    assert "probe failure" not in html


def test_the_error_page_renders_with_no_query_and_no_request(django_assert_num_queries):
    with django_assert_num_queries(0):
        html = render_to_string("500.html")
    assert "Server error" in html
    assert 'href="/"' in html


def test_the_error_page_extends_nothing_and_names_no_url_tag():
    source = (TEMPLATES / "500.html").read_text()
    assert "{% extends" not in source
    assert "{% url" not in source


@pytest.mark.django_db
def test_choosing_a_password_still_needs_a_signed_in_person():
    """Signed out, Choose a password sends the person to sign in first."""
    response = Client(SERVER_NAME="localhost").get(reverse("choose_password"))
    assert response.status_code == 302
    assert reverse("account_login") in response["Location"]
