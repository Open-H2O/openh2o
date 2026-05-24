from django.urls import path

from surface import views

app_name = "surface"

urlpatterns = [
    path("", views.water_rights_list, name="water_rights_list"),
    path("pods/geojson/", views.pods_geojson, name="pods_geojson"),
]
