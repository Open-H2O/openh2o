# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from config.views import about, index, getting_started, glossary, budgets_allocations, surface_deliveries, water_balances, profile

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounting/", include("accounting.urls")),
    path("parcels/", include("parcels.urls")),
    path("wells/", include("wells.urls")),
    path("surface/", include("surface.urls")),
    path("recharge/", include("recharge.urls")),
    path("map/", include("geography.urls")),
    path("datasync/", include("datasync.urls")),
    path("reporting/", include("reporting.urls")),
    path("health/", include("health.urls")),
    path("setup/", include("setup.urls")),
    path("infrastructure/", include("infrastructure.urls")),
    path("users/", include("core.urls")),
    path("about/", about, name="about"),
    path("help/getting-started/", getting_started, name="getting_started"),
    path("help/glossary/", glossary, name="glossary"),
    path("help/budgets-allocations/", budgets_allocations, name="budgets_allocations"),
    path("help/surface-deliveries/", surface_deliveries, name="surface_deliveries"),
    path("help/water-balances/", water_balances, name="water_balances"),
    path("profile/", profile, name="profile"),
    path("", index, name="index"),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
