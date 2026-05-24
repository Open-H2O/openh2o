from django.contrib import admin
from django.urls import include, path

from config.views import index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", index, name="index"),
]
