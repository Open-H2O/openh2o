# SPDX-License-Identifier: AGPL-3.0-or-later
"""One request-time answer to "is Google sign-in switched on here?" (ISS-115).

Before this module the question was asked in two templates and nowhere else, so
``allow_google_oauth`` hid the "Continue with Google" button and left the three
sign-in routes wide open. The button and the endpoint disagreeing is the whole
defect, and one predicate read by both layers is what stops them disagreeing
again — see ``tests/test_google_sign_in_switch.py`` and ``config/urls.py``.

**Available means BOTH halves are in place: the per-agency flag is on AND the
Google credentials are configured.** Keying on the flag alone would leave a
second defect standing — a stock install that has never touched Google returned
HTTP 500 on a public URL, because allauth's own code raises an uncaught
``SocialApp.DoesNotExist`` when asked for a provider that was never configured.
Both halves close with one question.

**The credentials are read from ``settings.SOCIALACCOUNT_PROVIDERS`` at call
time**, deliberately, and not from the ``_google_client_id`` locals in
``config/settings/base.py``. Those locals are import-time, which puts them out of
reach of ``override_settings`` — a predicate built on them could not be tested
against a credentials-present deployment without editing ``.env`` and rebuilding
the container, and an untestable guard is a guard nobody can prove works.

The flag is a database column read per request (``core/models.py``), which is
what lets an administrator tick the box in Django admin and have it take effect
without restarting anything. That affordance is the reason this is a predicate
rather than a settings-level conditional: settings are built once at import and
cannot see a value an administrator flips an hour later.
"""
import functools

from allauth.socialaccount.providers.google import views as google_views
from django.conf import settings
from django.http import Http404

from core.models import SiteConfig


def google_credentials_configured():
    """True when this deployment holds a Google client ID and secret.

    Mirrors what ``config/settings/base.py`` builds from the two
    ``GOOGLE_OAUTH_*`` environment variables: the ``google`` key exists and both
    halves of its ``APP`` are non-empty. A partially-filled entry counts as not
    configured, because half a credential authenticates nobody.
    """
    providers = getattr(settings, "SOCIALACCOUNT_PROVIDERS", None) or {}
    app = (providers.get("google") or {}).get("APP") or {}
    return bool(app.get("client_id") and app.get("secret"))


def google_sign_in_available():
    """True only when the agency switched it on AND the keys are behind it.

    Reads one indexed row per call. That is a second ``SiteConfig`` lookup on a
    page whose context already carries one, and it is accepted on purpose: the
    URL guards in ``config/urls.py`` run where no template context exists, and a
    predicate that needed one could not serve both layers — which is the single
    thing this module is for.

    Returns False rather than raising when no ``SiteConfig`` row exists at all.
    No migration seeds one, so that is the true state of a database that has
    migrated and never been set up, and the honest answer there is "no".
    """
    config = SiteConfig.objects.first()
    if config is None or not config.allow_google_oauth:
        return False
    return google_credentials_configured()


def _guarded(view):
    """Wrap an allauth view so the URL simply is not there while it is off.

    ``Http404`` and not ``HttpResponseForbidden``: ``config/urls.py`` already
    records the reasoning for a disabled module — *"a route that does not exist
    should not exist"* — and a 403 tells an unauthenticated caller that the
    endpoint is real and merely closed to them.

    ``functools.wraps`` is load-bearing rather than cosmetic here. It carries the
    wrapped view's ``__dict__`` across, which is where allauth keeps
    ``csrf_exempt = True`` on the token view; a hand-rolled wrapper would silently
    re-arm CSRF on an endpoint Google POSTs to from its own page, turning a
    working sign-in into a 403 in the one state where the feature is meant to
    work. ``tests/test_google_sign_in_switch.py`` asserts the marker survives.

    ``guarded_view`` names the view this guard delegates to. It exists so the
    tests can tell "guarded and pointing at the right view" apart from "guarded
    and pointing at the login view three times" — the shortcut Phase 127's
    discovery probe took, which closes the hole and breaks the callback.
    """

    @functools.wraps(view)
    def guard(request, *args, **kwargs):
        if not google_sign_in_available():
            raise Http404("Google sign-in is not enabled on this deployment.")
        return view(request, *args, **kwargs)

    guard.guarded_view = view
    return guard


#: One guard per route, each around ITS OWN allauth view. Wiring all three to
#: ``oauth2_login`` would ship a feature that can start a sign-in and never
#: finish one.
google_login_guard = _guarded(google_views.oauth2_login)
google_callback_guard = _guarded(google_views.oauth2_callback)
google_login_by_token_guard = _guarded(google_views.login_by_token)
