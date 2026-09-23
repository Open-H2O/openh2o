# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the drinking app."""
from django.urls import path

from drinking import views

app_name = "drinking"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("sampling-points/", views.sampling_points, name="sampling_points"),
    path("results/", views.results, name="results"),
    # The three detail pages, each named for the row it opens from. Kept beside
    # their list rather than at the bottom of the file: a reader looking for
    # "where does a sampling-point row go" should find it next to the list that
    # renders that row.
    # The list sits beside the detail it opens. No ordering hazard: an
    # exact-match prefix cannot shadow <int:pk> or geojson/.
    path("facilities/", views.facilities, name="facilities"),
    path(
        "facilities/<int:pk>/",
        views.facility_detail,
        name="facility_detail",
    ),
    # The facility door (146-04 Task 3, D9). "add" is not an int, so it cannot
    # be shadowed by the detail route above or shadow it.
    path("facilities/add/", views.facility_add, name="facility_add"),
    path(
        "facilities/<int:pk>/edit/",
        views.facility_edit,
        name="facility_edit",
    ),
    # The overview map's data source. Beside the facility route it draws, and
    # ahead of no <int:pk> it could shadow — "geojson" is not an int.
    path(
        "facilities/geojson/",
        views.facilities_geojson,
        name="facilities_geojson",
    ),
    path(
        "sampling-points/<int:pk>/",
        views.sampling_point_detail,
        name="sampling_point_detail",
    ),
    path("results/<int:pk>/", views.result_detail, name="result_detail"),
    path("import/", views.import_page, name="import"),
    path("import/preview/", views.import_preview, name="import_preview"),
    path("import/commit/", views.import_commit, name="import_commit"),
    # Production by month and source (146-04 Task 2, D7). Exact-match prefix
    # before <int:pk>-shaped routes: "add" and "import" are not ints, so no
    # ordering hazard, but "production/" is a prefix of every path below it,
    # the same shape the app-level "/drinking/" prefix already carries in
    # core/modules.py, so it is listed first among its own siblings too.
    path("production/", views.production, name="production"),
    path("production/add/", views.production_add, name="production_add"),
    path(
        "production/import/",
        views.production_import_page,
        name="production_import",
    ),
    path(
        "production/import/preview/",
        views.production_import_preview,
        name="production_import_preview",
    ),
    path(
        "production/import/commit/",
        views.production_import_commit,
        name="production_import_commit",
    ),
    # The sampling schedule (146-04 Task 4, D8).
    path("schedule/", views.schedule, name="schedule"),
    path("schedule/add/", views.schedule_add, name="schedule_add"),
    path("schedule/<int:pk>/edit/", views.schedule_edit, name="schedule_edit"),
    # Named to read as a sibling of the import flow above: page -> lookup -> commit
    # is the same shape as page -> preview -> commit, and an operator who has used
    # one already knows the other.
    path("onboard/", views.onboard_page, name="onboard"),
    path("onboard/lookup/", views.onboard_lookup, name="onboard_lookup"),
    path("onboard/commit/", views.onboard_commit, name="onboard_commit"),
    # The PWSID is in the path, not the session. Onboarding's session key is
    # deleted on commit, and this is the step *after* commit — so the builder
    # has to be reachable, bookmarkable and re-enterable on its own, which a
    # session-scoped route would not be.
    path(
        "onboard/<str:pwsid>/points/",
        views.onboard_points,
        name="onboard_points",
    ),
    path(
        "onboard/<str:pwsid>/points/add/",
        views.onboard_points_add,
        name="onboard_points_add",
    ),
]
