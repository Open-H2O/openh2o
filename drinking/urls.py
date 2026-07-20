# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the drinking app."""
from django.urls import path

from drinking import views

app_name = "drinking"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("sampling-points/", views.sampling_points, name="sampling_points"),
    path("results/", views.results, name="results"),
    path("import/", views.import_page, name="import"),
    path("import/preview/", views.import_preview, name="import_preview"),
    path("import/commit/", views.import_commit, name="import_commit"),
]
