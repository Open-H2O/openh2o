# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the feedback app."""
from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("submit/", views.submit, name="submit"),
    path("attachment/<int:pk>/", views.attachment, name="attachment"),
]
