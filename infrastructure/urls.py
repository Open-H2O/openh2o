from django.urls import path

from infrastructure.views import (
    infrastructure_add,
    infrastructure_geojson,
    infrastructure_upload,
    parcel_create_inline,
    parcel_search,
)

app_name = "infrastructure"

urlpatterns = [
    path("add/", infrastructure_add, name="add"),
    path("upload/", infrastructure_upload, name="upload"),
    path("geojson/", infrastructure_geojson, name="geojson"),
    path("parcels/search/", parcel_search, name="parcel_search"),
    path("parcels/create/", parcel_create_inline, name="parcel_create"),
]
