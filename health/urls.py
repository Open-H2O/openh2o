# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the health app."""
from django.urls import path

from . import views

app_name = "health"

urlpatterns = [
    path("", views.health_dashboard, name="dashboard"),
    path("api/", views.health_api, name="api"),
]
