from django.contrib import admin
from django.urls import include, path

from config.views import index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounting/", include("accounting.urls")),
    path("parcels/", include("parcels.urls")),
    path("wells/", include("wells.urls")),
    path("surface/", include("surface.urls")),
    path("recharge/", include("recharge.urls")),
    path("map/", include("geography.urls")),
    path("", index, name="index"),
]
