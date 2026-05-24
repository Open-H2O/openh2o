from django.urls import path

from parcels import views

app_name = "parcels"

urlpatterns = [
    path("", views.parcels_list, name="list"),
    path("geojson/", views.parcels_geojson, name="geojson"),
]
