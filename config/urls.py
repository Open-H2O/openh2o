# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core.modules import enabled_modules, url_specs_for
from core.oauth import (
    google_callback_guard,
    google_login_by_token_guard,
    google_login_guard,
)

from config.views import about, demonstration_data, index, getting_started, glossary, budgets_allocations, surface_deliveries, water_balances, methods, settings_explained, profile, set_nav_mode, global_search

# Module-owned routes, composed from OPENH2O_MODULES via the registry, in the
# same prefix order the hand-written list used. A DISABLED module's paths are
# simply never registered, so they 404 for free — there is deliberately no
# catch-all and no friendly "module disabled" page. A route that does not exist
# should not exist.
_module_urls = [
    path(prefix, include(url_module))
    for prefix, url_module in url_specs_for(enabled_modules())
]

# Everything below is hand-written and NOT module-owned: the Django admin,
# allauth, the root index, the static help/about pages, the nav-mode toggle and
# global search.
urlpatterns = [
    path("admin/", admin.site.urls),
    # Google sign-in exists only where the per-agency flag is ON *and* the
    # credentials are configured (core.oauth.google_sign_in_available, the same
    # predicate the login and sign-up templates read). While either half is
    # missing these three routes 404, for the reason recorded above: a route
    # that does not exist should not exist, and a 403 would confirm the endpoint
    # is real. Before this guard the flag hid the button and nothing else, so a
    # plain GET here still handed the visitor to Google and could clear an
    # existing account's password on the way back (ISS-115).
    #
    # Declared BEFORE allauth's mount on purpose: Django resolves patterns in
    # declaration order, so these win over `allauth.urls`. They are deliberately
    # left unnamed — allauth registers `google_login`/`google_callback`/
    # `google_login_by_token` on the identical paths, and shadowing those names
    # in the reverse table would buy nothing while making `reverse()` ambiguous.
    path("accounts/google/login/", google_login_guard),
    path("accounts/google/login/callback/", google_callback_guard),
    path("accounts/google/login/token/", google_login_by_token_guard),
    path("accounts/", include("allauth.urls")),
] + _module_urls + [
    path("about/", about, name="about"),
    # Reachable regardless of demonstration_mode: a link shared in answer to
    # "this data is fake" must not 404 once the flag is off.
    path(
        "about/demonstration-data/",
        demonstration_data,
        name="demonstration_data",
    ),
    path("help/getting-started/", getting_started, name="getting_started"),
    path("help/glossary/", glossary, name="glossary"),
    path("help/budgets-allocations/", budgets_allocations, name="budgets_allocations"),
    path("help/surface-deliveries/", surface_deliveries, name="surface_deliveries"),
    path("help/water-balances/", water_balances, name="water_balances"),
    path("help/methods/", methods, name="methods"),
    path("help/settings/", settings_explained, name="settings_explained"),
    path("profile/", profile, name="profile"),
    path("nav-mode/", set_nav_mode, name="set_nav_mode"),
    path("search/", global_search, name="global_search"),
    path("", index, name="index"),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
