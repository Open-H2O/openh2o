# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from parcels import views

app_name = "parcels"

urlpatterns = [
    path("", views.parcels_list, name="list"),
    path("<int:pk>/", views.parcel_detail, name="detail"),
    path("<int:pk>/edit-field/", views.parcel_edit_field, name="edit_field"),
    path("geojson/", views.parcels_geojson, name="geojson"),
]
