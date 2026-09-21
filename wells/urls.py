# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the wells app."""
from django.urls import path

from wells import views

app_name = "wells"

urlpatterns = [
    path("", views.wells_list, name="list"),
    path("<int:pk>/", views.well_detail, name="detail"),
    path("<int:pk>/edit-field/", views.well_edit_field, name="edit_field"),
    # 146-02 D3: the share editor on a well's linked use area.
    path(
        "<int:pk>/irrigated-parcel/<int:wip_pk>/share/",
        views.well_irrigated_parcel_edit_share,
        name="irrigated_parcel_edit_share",
    ),
    path("geojson/", views.wells_geojson, name="geojson"),
]
