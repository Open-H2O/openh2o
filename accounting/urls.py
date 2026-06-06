# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the accounting app."""
from django.urls import path

from accounting import views

app_name = "accounting"

urlpatterns = [
    # Dashboard
    path("dashboard/", views.dashboard, name="dashboard"),
    # Reporting Periods
    path("reporting-periods/", views.periods_list, name="periods_list"),
    path("reporting-periods/create/", views.period_create, name="period_create"),
    path("reporting-periods/<int:pk>/", views.period_detail, name="period_detail"),
    path(
        "reporting-periods/<int:pk>/finalize/",
        views.period_finalize,
        name="period_finalize",
    ),
    # Water Accounts
    path("accounts/", views.accounts_list, name="accounts_list"),
    path("accounts/create/", views.account_create, name="account_create"),
    path("accounts/<int:pk>/", views.account_detail, name="account_detail"),
    path(
        "accounts/<int:pk>/assign-parcel/",
        views.assign_parcel,
        name="assign_parcel",
    ),
    path(
        "accounts/<int:pk>/remove-parcel/<int:wap_pk>/",
        views.remove_parcel,
        name="remove_parcel",
    ),
    path(
        "accounts/<int:pk>/search-parcels/",
        views.parcel_search_for_assignment,
        name="parcel_search_for_assignment",
    ),
    # Allocation Plans
    path("allocations/", views.allocations_list, name="allocations_list"),
    path("allocations/create/", views.allocation_create, name="allocation_create"),
    # Ledger
    path("ledger/", views.ledger_list, name="ledger_list"),
    path("ledger/create/", views.ledger_create, name="ledger_create"),
    path("ledger/upload/", views.csv_upload, name="csv_upload"),
    path("ledger/template/", views.csv_template, name="csv_template"),
    path("ledger/export/", views.ledger_export, name="ledger_export"),
    # Calculation Run audit trail ("How was this calculated?")
    path(
        "calculation-run/<int:parcel_id>/<str:period>/",
        views.calculation_run_detail,
        name="calculation_run_detail",
    ),
    # Delivery Settings (staff-only agency efficiency + year-end policy, 55-03)
    path("delivery-settings/", views.delivery_settings, name="delivery_settings"),
    # Methodology Settings (staff-only self-serve methodology tuning, 38-07)
    path("methodology/", views.methodology_settings, name="methodology_settings"),
    path(
        "methodology/step/<int:step_id>/toggle/",
        views.methodology_step_toggle,
        name="methodology_step_toggle",
    ),
    path(
        "methodology/step/<int:step_id>/move/<str:direction>/",
        views.methodology_step_move,
        name="methodology_step_move",
    ),
    path(
        "methodology/step/<int:step_id>/config/",
        views.methodology_step_config,
        name="methodology_step_config",
    ),
    path(
        "methodology/preview/",
        views.methodology_preview,
        name="methodology_preview",
    ),
]
