from django.urls import path

from geography import views

app_name = "geography"

urlpatterns = [
    path("", views.map_view, name="map"),
]
