# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the core app."""
from django.urls import path

from core import corrections_views, views

app_name = "core"

urlpatterns = [
    path("", views.users_list, name="users_list"),
    path("add/", views.user_create, name="user_create"),
    path(
        "imports/<uuid:token>/status/",
        views.pending_import_status,
        name="pending_import_status",
    ),
    # Void this record. core's routes are mounted under users/ (core/modules.py), so the
    # address is /users/records/<kind>/<pk>/void/; every page reaches it by name.
    path(
        "records/<slug:kind>/<int:pk>/void/",
        corrections_views.record_void,
        name="record_void",
    ),
    # Correct this record: the same address shape, and the file a correction carries.
    path(
        "records/<slug:kind>/<int:pk>/correct/",
        corrections_views.record_correct,
        name="record_correct",
    ),
    path(
        "records/attachments/<int:pk>/",
        corrections_views.record_attachment,
        name="record_attachment",
    ),
    path("<int:pk>/role/", views.user_set_role, name="user_set_role"),
    path("<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("<int:pk>/email/", views.user_email_edit, name="user_email_edit"),
    path(
        "<int:pk>/temporary-password/",
        views.user_temp_password,
        name="user_temp_password",
    ),
]
