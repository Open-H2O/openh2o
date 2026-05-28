from django.urls import path

from datasync import views

app_name = "datasync"

urlpatterns = [
    path("stations/", views.station_list, name="station_list"),
    path("stations/add/", views.station_add, name="station_add"),
    path("stations/<int:pk>/", views.station_detail, name="station_detail"),
    path("stations/<int:pk>/toggle/", views.station_toggle, name="station_toggle"),
    path("stations/<int:pk>/chart-data/", views.station_chart_data, name="station_chart_data"),
    path("stations/geojson/", views.stations_geojson, name="stations_geojson"),
    path("stations/freshness-geojson/", views.stations_freshness_geojson, name="stations_freshness_geojson"),
    path("monitoring/", views.monitoring_dashboard, name="monitoring_dashboard"),
]
