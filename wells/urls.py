# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the wells app."""
from django.urls import path

from wells import views

app_name = "wells"

urlpatterns = [
    path("", views.wells_list, name="list"),
    path("<int:pk>/", views.well_detail, name="detail"),
    path("<int:pk>/edit-field/", views.well_edit_field, name="edit_field"),
    # The share editor on a well's linked use area.
    path(
        "<int:pk>/irrigated-parcel/<int:wip_pk>/share/",
        views.well_irrigated_parcel_edit_share,
        name="irrigated_parcel_edit_share",
    ),
    # A meter reading is entered once, on the well.
    path(
        "<int:pk>/meter-reading/add/",
        views.meter_reading_add,
        name="meter_reading_add",
    ),
    # A depth to water is entered once, on the well, or imported from a file.
    path(
        "<int:pk>/water-level/add/",
        views.water_level_add,
        name="water_level_add",
    ),
    path(
        "water-levels/import/",
        views.water_level_import,
        name="water_level_import",
    ),
    path(
        "water-levels/import/preview/",
        views.water_level_import_preview,
        name="water_level_import_preview",
    ),
    path(
        "water-levels/import/commit/",
        views.water_level_import_commit,
        name="water_level_import_commit",
    ),
    path("geojson/", views.wells_geojson, name="geojson"),
]
