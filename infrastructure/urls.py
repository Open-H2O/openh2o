# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the infrastructure app."""
from django.urls import path

from infrastructure.views import (
    infrastructure_add,
    infrastructure_geojson,
    infrastructure_import,
    infrastructure_import_commit,
    infrastructure_import_preview,
    parcel_create_inline,
    parcel_search,
)

app_name = "infrastructure"

urlpatterns = [
    path("add/", infrastructure_add, name="add"),
    path("import/", infrastructure_import, name="import"),
    path("import/preview/", infrastructure_import_preview, name="import_preview"),
    path("import/commit/", infrastructure_import_commit, name="import_commit"),
    path("geojson/", infrastructure_geojson, name="geojson"),
    path("parcels/search/", parcel_search, name="parcel_search"),
    path("parcels/create/", parcel_create_inline, name="parcel_create"),
]
