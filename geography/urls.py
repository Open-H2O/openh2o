# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from geography import views

app_name = "geography"

urlpatterns = [
    # Map
    path("", views.map_view, name="map"),

    # Zone management
    path("zones/", views.zone_list, name="zone_list"),
    path("zones/create/", views.zone_create, name="zone_create"),
    path("zones/<int:pk>/", views.zone_detail, name="zone_detail"),
    path("zones/<int:pk>/assign/", views.zone_parcel_assign, name="zone_parcel_assign"),
    path("zones/<int:pk>/remove/<int:pz_pk>/", views.zone_parcel_remove, name="zone_parcel_remove"),
    path("zones/<int:pk>/parcels/", views.zone_parcel_search, name="zone_parcel_search"),
    path("zones/<int:pk>/geojson/", views.zone_geojson_single, name="zone_geojson_single"),

    # GeoJSON endpoints
    path("boundaries/geojson/", views.boundaries_geojson, name="boundaries_geojson"),
    path("flowlines/geojson/", views.flowlines_geojson, name="flowlines_geojson"),
    path("zones/geojson/", views.zones_geojson, name="zones_geojson"),
    path("zones/labels/geojson/", views.zone_labels_geojson, name="zone_labels_geojson"),
    path("tie-lines/geojson/", views.tie_lines_geojson, name="tie_lines_geojson"),
]
