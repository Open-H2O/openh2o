from django.urls import path

from wells import views

app_name = "wells"

urlpatterns = [
    path("", views.wells_list, name="list"),
    path("geojson/", views.wells_geojson, name="geojson"),
]
