# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from wells import views

app_name = "wells"

urlpatterns = [
    path("", views.wells_list, name="list"),
    path("<int:pk>/", views.well_detail, name="detail"),
    path("<int:pk>/edit-field/", views.well_edit_field, name="edit_field"),
    path("geojson/", views.wells_geojson, name="geojson"),
]
