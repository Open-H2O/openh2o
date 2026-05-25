from django.urls import path

from geography import views

app_name = "geography"

urlpatterns = [
    path("", views.map_view, name="map"),
    path("boundaries/geojson/", views.boundaries_geojson, name="boundaries_geojson"),
    path("zones/geojson/", views.zones_geojson, name="zones_geojson"),
]
