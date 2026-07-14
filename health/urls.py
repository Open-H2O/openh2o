# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the health app."""
from django.urls import path

from . import views

app_name = "health"

urlpatterns = [
    path("", views.health_dashboard, name="dashboard"),
    path("api/", views.health_api, name="api"),
    # DB-free liveness probe for the Docker HEALTHCHECK + Caddy readiness gate.
    path("live/", views.livez, name="live"),
    # DB-touching probe (SELECT 1) so external monitors can MEASURE database
    # health instead of inferring it from page loads (ISS-008).
    path("db/", views.dbz, name="db"),
]
