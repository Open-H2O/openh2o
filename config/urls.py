# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core.modules import enabled_modules, url_specs_for

from config.views import about, index, getting_started, glossary, budgets_allocations, surface_deliveries, water_balances, methods, settings_explained, profile, set_nav_mode, global_search

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
    path("accounts/", include("allauth.urls")),
] + _module_urls + [
    path("about/", about, name="about"),
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
