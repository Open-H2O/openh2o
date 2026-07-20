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
    # Named to read as a sibling of the import flow above: page -> lookup -> commit
    # is the same shape as page -> preview -> commit, and an operator who has used
    # one already knows the other.
    path("onboard/", views.onboard_page, name="onboard"),
    path("onboard/lookup/", views.onboard_lookup, name="onboard_lookup"),
    path("onboard/commit/", views.onboard_commit, name="onboard_commit"),
]
