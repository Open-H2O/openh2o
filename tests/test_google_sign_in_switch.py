# SPDX-License-Identifier: AGPL-3.0-or-later
"""`allow_google_oauth` must gate the sign-in ROUTES, not just the button.

ISS-115: the flag named ``allow_google_oauth`` on ``SiteConfig`` was read in
exactly two places and both of them were templates. It hid the "Continue with
Google" button and nothing else. With the Google credentials set and the flag
off, a plain GET to ``/accounts/google/login/`` still handed the visitor to
Google, and an existing account whose email Google vouches for was signed in and
had its local password cleared (``SOCIALACCOUNT_EMAIL_AUTHENTICATION`` +
``..._AUTO_CONNECT``, ``config/settings/base.py:437-438``). openh2o.com was
running exactly that configuration on the day this module was written (measured
2026-08-28, Phase 127 DISCOVERY §4).

A switch that means what its name says is a claim about two layers at once, and
that is why both layers here read ONE predicate,
``core.oauth.google_sign_in_available``:

1. **The URL layer.** All THREE Google routes 404 while the feature is
   unavailable — including ``accounts/google/login/token/``, which ISS-115 never
   named. The routes are enumerated from this project's own URL resolver rather
   than from a list written down here, so a fourth allauth route cannot appear
   unguarded and still find this module green.
2. **The templates.** A URL guard alone is not enough, and the reason is
   measured. The button is rendered by ``{% provider_login_url 'google' %}``,
   which runs BEFORE any guarded URL is ever requested and reaches an uncaught
   ``SocialApp.DoesNotExist`` of its own. So with the flag ticked and the keys
   not yet pasted, ``/accounts/login/`` itself — the front door of the platform,
   not the button on it — returned HTTP 500.

**"Unavailable" means flag off OR credentials missing, and both halves are
asserted separately.** Keying the guard on the flag alone would leave a second
defect open: a stock install that has never touched Google served a 500 on a
public URL (DISCOVERY §6).

**The guard must delegate, not replace.** Each route is wrapped around its OWN
allauth view. Phase 127's discovery probe wired all three URLs to
``oauth2_login`` as a shortcut, which would ship a feature that cannot complete
a sign-in, so ``test_each_route_is_guarded_around_its_own_allauth_view`` pins the
delegation target per route rather than merely checking that something 404s.

**Two mechanical facts this module depends on, both measured rather than
assumed:**

- ``override_settings(SOCIALACCOUNT_PROVIDERS=...)`` takes effect per request —
  allauth reads ``app_settings.PROVIDERS`` at request time, not at import. So the
  whole credentials-present matrix runs in-process, with no container
  environment change and no ``.env`` edit.
- The test client must carry ``SERVER_NAME="localhost"``. This container's
  ``config.settings.local`` resolves ``ALLOWED_HOSTS`` to ``['localhost',
  '127.0.0.1']``, and the default ``testserver`` host raises ``DisallowedHost``
  before any view runs — which reads exactly like a passing 400 guard and is not
  one. ``raise_request_exception=False`` is what lets the 500 cells be observed
  as a status code instead of an exception escaping the client.

**Two tests here are controls, and they are labelled as such.** They were green
before the fix and must stay green after it: the working sign-in path still
reaches Google, and the callback still refuses a bare GET rather than bouncing
it onward. A guard that closes the hole by breaking the feature is not a fix.
"""

import pytest
from allauth.socialaccount.providers.google import views as google_views
from django.test import Client, override_settings
from django.urls import get_resolver, resolve

from core.models import SiteConfig

#: Credentials shaped exactly as ``config/settings/base.py:419-429`` builds them
#: when both ``GOOGLE_OAUTH_*`` environment variables are present. The values are
#: fictional; only their presence is read.
CREDENTIALS_SET = {
    "google": {
        "APP": {"client_id": "probe-client-id", "secret": "probe-secret"},
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}

#: The fresh-install state: ``SOCIALACCOUNT_PROVIDERS`` as
#: ``config/settings/base.py:247`` leaves it when the environment is empty.
CREDENTIALS_MISSING: dict = {}

LOGIN_PAGE = "/accounts/login/"
SIGNUP_PAGE = "/accounts/signup/"
BUTTON = "Continue with Google"

#: (flag, credentials, the feature is available). Every cell of the matrix
#: measured during planning against the running container at ``9fd083e``.
MATRIX = [
    ("flag on, no credentials", True, CREDENTIALS_MISSING, False),
    ("flag on, credentials set", True, CREDENTIALS_SET, True),
    ("flag off, no credentials", False, CREDENTIALS_MISSING, False),
    ("flag off, credentials set", False, CREDENTIALS_SET, False),
]

#: The cells in which no Google sign-in route may exist.
UNAVAILABLE_CELLS = [cell for cell in MATRIX if not cell[3]]

#: The one cell in which it must work exactly as it does today.
AVAILABLE_CELL = next(cell for cell in MATRIX if cell[3])


@pytest.fixture
def visitor():
    """A client that can see this container's hosts and its own error pages."""
    return Client(SERVER_NAME="localhost", raise_request_exception=False)


def set_flag(value):
    """Set ``allow_google_oauth`` on the singleton, creating it if absent."""
    config = SiteConfig.objects.first() or SiteConfig(
        agency_name="Probe Water District"
    )
    config.allow_google_oauth = value
    config.save()
    return config


def google_routes():
    """Every concrete URL in THIS project's resolver that belongs to Google.

    Walked from the resolver rather than typed out, because the point of the
    guard is that no Google route escapes it. ``login/token/`` is in here and is
    absent from ISS-115 entirely; a fourth one arriving with a future allauth
    upgrade lands in this list too, and the guard assertions fail rather than
    quietly covering two routes out of four.
    """
    routes = set()

    def walk(patterns, prefix=""):
        for entry in patterns:
            route = prefix + str(entry.pattern)
            nested = getattr(entry, "url_patterns", None)
            if nested is not None:
                walk(nested, route)
            elif "google" in route:
                routes.add("/" + route)

    walk(get_resolver().url_patterns)
    return sorted(routes)


def test_no_google_route_exists_while_the_feature_is_unavailable(visitor):
    """Flag off OR credentials missing ⇒ the route is not there, on all three.

    404 and not 403: ``config/urls.py:11-15`` already records the reasoning for a
    disabled module — *"a route that does not exist should not exist"* — and a
    403 confirms the endpoint exists.
    """
    routes = google_routes()
    assert len(routes) == 3, (
        "the Google route inventory changed; every route below must be guarded, "
        f"so update the guards before this list: {routes}"
    )

    observed = {}
    for name, flag, credentials, _ in UNAVAILABLE_CELLS:
        set_flag(flag)
        with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
            for route in routes:
                observed[(name, route)] = visitor.get(route).status_code

    assert observed == {key: 404 for key in observed}, observed


def test_each_route_is_guarded_around_its_own_allauth_view():
    """The guard wraps each URL's own view, not one view three times.

    DISCOVERY §5's proof-of-concept routed all three URLs to ``oauth2_login``.
    That shortcut closes the hole and breaks the callback, which means a feature
    that can start a sign-in and never finish one. Pinning the delegation target
    per route is the only assertion that can tell the two apart.
    """
    expected = {
        "/accounts/google/login/": google_views.oauth2_login,
        "/accounts/google/login/callback/": google_views.oauth2_callback,
        "/accounts/google/login/token/": google_views.login_by_token,
    }

    unguarded = []
    misrouted = []
    for route, view in expected.items():
        resolved = resolve(route).func
        delegate = getattr(resolved, "guarded_view", None)
        if delegate is None:
            unguarded.append(route)
        elif delegate is not view:
            misrouted.append(f"{route} -> {delegate!r}, expected {view!r}")

    assert not unguarded, f"these routes reach allauth with no guard: {unguarded}"
    assert not misrouted, f"these routes delegate to the wrong view: {misrouted}"


def test_the_token_route_keeps_its_csrf_exemption():
    """Wrapping ``login_by_token`` must not quietly re-arm CSRF on it.

    allauth ships that view ``csrf_exempt`` because Google One Tap POSTs to it
    from Google's own page. A wrapper that drops the marker turns a working
    endpoint into a 403 in the one cell where the feature is supposed to work.
    """
    view = resolve("/accounts/google/login/token/").func
    assert getattr(view, "guarded_view", None) is google_views.login_by_token
    assert getattr(view, "csrf_exempt", False) is True


def test_the_working_sign_in_path_still_reaches_google(visitor):
    """CONTROL — green before this phase and green after.

    The guard delegates rather than replaces, so the one available cell behaves
    exactly as it does today: a redirect to Google carrying the client ID.
    """
    _, flag, credentials, _ = AVAILABLE_CELL
    set_flag(flag)
    with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
        response = visitor.get("/accounts/google/login/")

    assert response.status_code == 302
    assert "accounts.google.com" in response["Location"]


def test_the_callback_still_refuses_a_bare_get_when_the_feature_is_on(visitor):
    """CONTROL — green before this phase and green after.

    A bare GET to the callback carries no state, so allauth refuses it. If the
    callback were wired to ``oauth2_login`` instead, this would bounce onward to
    Google — which is the failure mode the delegation test above is named for,
    observed here from the outside.
    """
    _, flag, credentials, _ = AVAILABLE_CELL
    set_flag(flag)
    with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
        response = visitor.get("/accounts/google/login/callback/")

    assert response.status_code != 302, response.get("Location", "")


def test_the_login_page_survives_every_cell_of_the_matrix(visitor):
    """The front door answers 200 in all four cells.

    The cell that fails today is *flag on, no credentials*: the template tag
    reaches the same uncaught ``SocialApp.DoesNotExist`` as the endpoint and
    takes the whole login page down. An operator who ticks the switch before
    pasting the keys — an order the old ``DEPLOY.md`` prose invited — locks
    everybody out of a platform whose sign-in page will not render.
    """
    observed = {}
    for name, flag, credentials, _ in MATRIX:
        set_flag(flag)
        with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
            observed[name] = visitor.get(LOGIN_PAGE).status_code

    assert observed == {name: 200 for name in observed}, observed


def test_the_button_appears_in_exactly_the_available_cell(visitor):
    """The button and the endpoint agree by construction, not by coincidence.

    Both read ``google_sign_in_available``. This is the assertion that would
    catch them drifting apart again, which is how ISS-115 happened in the first
    place.

    **The status code is asserted alongside the button on purpose.** Without it
    this test passes against the broken tree, because the cell that returns 500
    serves an error page and an error page contains no button either — "absent"
    and "the page never rendered" are the same string search. A check that can
    only pass is not a measurement.
    """
    observed = {}
    for name, flag, credentials, available in MATRIX:
        set_flag(flag)
        with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
            response = visitor.get(LOGIN_PAGE)
        body = response.content.decode() if response.status_code == 200 else ""
        observed[name] = (response.status_code, BUTTON in body, available)

    wrong = {
        name: f"status={status}, button rendered={rendered}, available={available}"
        for name, (status, rendered, available) in observed.items()
        if status != 200 or rendered is not available
    }
    assert not wrong, wrong


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_the_signup_page_gates_the_button_on_the_same_predicate(visitor):
    """The sign-up page has the identical conditional and the identical hazard.

    It answers 200 in every cell on a default install only because
    ``ACCESS_CONTROL_ENFORCED`` is on and the closed template renders instead —
    the conditional is never reached. That 200 is not the conditional being
    safe. Turn the access switch off, which is exactly the open-demo posture
    openh2o.com runs, and it is the same code path as the login page.
    """
    observed = {}
    for name, flag, credentials, available in MATRIX:
        set_flag(flag)
        with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
            response = visitor.get(SIGNUP_PAGE)
        body = response.content.decode() if response.status_code == 200 else ""
        observed[name] = (response.status_code, BUTTON in body, available)

    wrong = {
        name: f"status={status}, button rendered={rendered}, available={available}"
        for name, (status, rendered, available) in observed.items()
        if status != 200 or rendered is not available
    }
    assert not wrong, wrong


def test_the_predicate_answers_all_four_combinations():
    """The predicate itself, exercised directly rather than through a view.

    Imported inside the test on purpose: it lets this whole module be run — and
    recorded red — against the tree before ``core/oauth.py`` existed, so the
    HTTP-level assertions above could be seen failing for their own reasons
    instead of every test collapsing into one collection error.
    """
    from core.oauth import google_sign_in_available

    observed = {}
    for name, flag, credentials, available in MATRIX:
        set_flag(flag)
        with override_settings(SOCIALACCOUNT_PROVIDERS=credentials):
            observed[name] = (google_sign_in_available(), available)

    wrong = {
        name: f"predicate said {answer}, expected {available}"
        for name, (answer, available) in observed.items()
        if answer is not available
    }
    assert not wrong, wrong


def test_the_predicate_is_false_before_any_site_config_exists():
    """A brand-new install has no ``SiteConfig`` row at all.

    ``SiteConfig.objects.first()`` returns None on a database that has migrated
    but never been set up, and no migration seeds one. The predicate must read
    that as "unavailable" rather than raising, or the guard turns the fresh-
    install 500 into a different 500.
    """
    from core.oauth import google_sign_in_available

    SiteConfig.objects.all().delete()
    with override_settings(SOCIALACCOUNT_PROVIDERS=CREDENTIALS_SET):
        assert google_sign_in_available() is False
