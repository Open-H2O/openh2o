# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the core app."""
from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.users_list, name="users_list"),
    path("add/", views.user_create, name="user_create"),
    path("<int:pk>/toggle-admin/", views.user_toggle_admin, name="user_toggle_admin"),
    path("<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
]
