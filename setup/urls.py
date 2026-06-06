# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the first-run setup wizard."""
from django.urls import path

from setup import views

app_name = "setup"

urlpatterns = [
    path("", views.setup_wizard, name="wizard"),
    path("confirm/", views.setup_confirm, name="confirm"),
    path("run/", views.setup_run, name="run"),
    path("progress/", views.setup_progress, name="progress"),
    path("activate-stations/", views.setup_activate_stations, name="activate_stations"),
]
