# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from reporting import views

app_name = "reporting"

urlpatterns = [
    path("reports/", views.report_list, name="report_list"),
    path("reports/shared-supply-check/", views.shared_supply_check, name="shared_supply_check"),
    path("reports/generate/", views.report_generate, name="report_generate"),
    path("reports/<int:pk>/", views.report_detail, name="report_detail"),
    path("reports/<int:pk>/download/", views.report_download, name="report_download"),
    path("reports/<int:pk>/transition/", views.report_transition, name="report_transition"),
    path("reports/<int:pk>/calwatrs-worksheet/", views.calwatrs_worksheet, name="calwatrs_worksheet"),
    path("reports/<int:pk>/prefill/", views.report_prefill, name="report_prefill"),
]
