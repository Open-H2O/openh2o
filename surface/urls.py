# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from surface import views

app_name = "surface"

urlpatterns = [
    # POD-centric views (primary entry point)
    path("", views.pod_list, name="pod_list"),
    path("diversion/<int:pk>/", views.pod_detail, name="pod_detail"),
    path("diversion/<int:pk>/record/", views.diversion_record_create, name="diversion_record_create"),

    # Water rights views (compliance navigation)
    path("rights/", views.water_rights_list, name="water_rights_list"),
    path("rights/<int:pk>/", views.water_right_detail, name="detail"),

    # GeoJSON
    path("pods/geojson/", views.pods_geojson, name="pods_geojson"),
]
