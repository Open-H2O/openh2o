# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the parcels app."""
from django.urls import path

from parcels import views

app_name = "parcels"

urlpatterns = [
    path("", views.parcels_list, name="list"),
    path("<int:pk>/", views.parcel_detail, name="detail"),
    path("<int:pk>/edit-field/", views.parcel_edit_field, name="edit_field"),
    path("<int:pk>/fallow/add/", views.fallow_period_add, name="fallow_period_add"),
    path("<int:pk>/fallow/end/", views.fallow_period_end_edit, name="fallow_period_end_edit"),
    path("geojson/", views.parcels_geojson, name="geojson"),
]
