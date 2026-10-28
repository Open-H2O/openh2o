# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the recharge app."""
from django.urls import path

from recharge import views

app_name = "recharge"

urlpatterns = [
    path("", views.recharge_sites_list, name="list"),
    path("<int:pk>/", views.recharge_site_detail, name="detail"),
    path("<int:pk>/events/add/", views.recharge_event_create, name="event_create"),
    path("<int:pk>/account/", views.recharge_site_account, name="site_account"),
    path("<int:pk>/zone/", views.recharge_site_zone, name="site_zone"),
    path("<int:pk>/events/<int:event_pk>/edit/", views.recharge_event_edit, name="event_edit"),
    path("<int:pk>/events/<int:event_pk>/delete/", views.recharge_event_delete, name="event_delete"),
    path("sites/geojson/", views.recharge_sites_geojson, name="sites_geojson"),
]
