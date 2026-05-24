from django.conf import settings
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
    path("datasync/", include("datasync.urls")),
    path("reporting/", include("reporting.urls")),
    path("health/", include("health.urls")),
    path("", index, name="index"),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
