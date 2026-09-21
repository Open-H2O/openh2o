# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the surface app."""
from django.urls import path

from surface import views

app_name = "surface"

urlpatterns = [
    # POD-centric views (primary entry point)
    path("", views.pod_list, name="pod_list"),
    path("diversion/<int:pk>/", views.pod_detail, name="pod_detail"),
    path("diversion/<int:pk>/record/", views.diversion_record_create, name="diversion_record_create"),
    # 146-02 Task 3 (ISS-181): edit and delete a diversion record.
    path(
        "diversion/<int:pk>/record/<int:rpk>/edit/",
        views.diversion_record_edit,
        name="diversion_record_edit",
    ),
    path(
        "diversion/<int:pk>/record/<int:rpk>/delete/",
        views.diversion_record_delete,
        name="diversion_record_delete",
    ),
    # 146-02 D2: the point-to-right link.
    path("diversion/<int:pk>/link-right/", views.pod_link_right, name="pod_link_right"),
    # 146-02 D3: the share editor on a POD's linked use area.
    path(
        "diversion/<int:pk>/parcel/<int:pp_pk>/share/",
        views.pod_parcel_edit_share,
        name="pod_parcel_edit_share",
    ),

    # Water rights views (compliance navigation)
    path("rights/", views.water_rights_list, name="water_rights_list"),
    path("rights/add/", views.water_right_create, name="water_right_create"),
    path("rights/import/", views.water_right_import, name="water_right_import"),
    path("rights/import/preview/", views.water_right_import_preview, name="water_right_import_preview"),
    path("rights/import/commit/", views.water_right_import_commit, name="water_right_import_commit"),
    path("rights/<int:pk>/", views.water_right_detail, name="detail"),
    path("rights/<int:pk>/edit/", views.water_right_edit, name="water_right_edit"),
    # 146-02 D3: a right's places of use.
    path(
        "rights/<int:pk>/assign-parcel/",
        views.water_right_assign_parcel,
        name="water_right_assign_parcel",
    ),
    path(
        "rights/<int:pk>/remove-parcel/<int:wrp_pk>/",
        views.water_right_remove_parcel,
        name="water_right_remove_parcel",
    ),
    path(
        "rights/<int:pk>/search-parcels/",
        views.water_right_search_parcels,
        name="water_right_search_parcels",
    ),

    # Curtailment orders (146-02 D6, ISS-180)
    path("curtailments/", views.curtailments_list, name="curtailments_list"),
    path("curtailments/add/", views.curtailment_create, name="curtailment_create"),
    path("curtailments/<int:pk>/edit/", views.curtailment_edit, name="curtailment_edit"),

    # GeoJSON
    path("pods/geojson/", views.pods_geojson, name="pods_geojson"),
]
