# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL routes for the accounting app."""
from django.urls import path

from accounting.views import (
    accounts,
    allocations,
    calculation_runs,
    dashboard,
    ledger,
    periods,
    settings_pages,
)

app_name = "accounting"

urlpatterns = [
    # Dashboard
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    # Reporting Periods
    path("reporting-periods/", periods.periods_list, name="periods_list"),
    path("reporting-periods/create/", periods.period_create, name="period_create"),
    path("reporting-periods/<int:pk>/", periods.period_detail, name="period_detail"),
    path(
        "reporting-periods/<int:pk>/calculate/",
        periods.period_calculate,
        name="period_calculate",
    ),
    path(
        "reporting-periods/<int:pk>/calculation-status/",
        periods.period_calculation_status,
        name="period_calculation_status",
    ),
    path(
        "reporting-periods/<int:pk>/finalize/",
        periods.period_finalize,
        name="period_finalize",
    ),
    # Water Accounts
    path("accounts/", accounts.accounts_list, name="accounts_list"),
    path("accounts/create/", accounts.account_create, name="account_create"),
    path("accounts/<int:pk>/", accounts.account_detail, name="account_detail"),
    path("accounts/<int:pk>/edit/", accounts.account_edit, name="account_edit"),
    path(
        "accounts/<int:pk>/assign-parcel/",
        accounts.assign_parcel,
        name="assign_parcel",
    ),
    path(
        "accounts/<int:pk>/remove-parcel/<int:wap_pk>/",
        accounts.remove_parcel,
        name="remove_parcel",
    ),
    path(
        "accounts/<int:pk>/search-parcels/",
        accounts.parcel_search_for_assignment,
        name="parcel_search_for_assignment",
    ),
    # Allocation Plans
    path("allocations/", allocations.allocations_list, name="allocations_list"),
    path("allocations/create/", allocations.allocation_create, name="allocation_create"),
    # Ledger
    path("ledger/", ledger.ledger_list, name="ledger_list"),
    path("ledger/create/", ledger.ledger_create, name="ledger_create"),
    path("ledger/upload/", ledger.csv_upload, name="csv_upload"),
    path("ledger/template/", ledger.csv_template, name="csv_template"),
    path("ledger/export/", ledger.ledger_export, name="ledger_export"),
    # Calculation Run audit trail ("How was this calculated?")
    path(
        "calculation-run/<int:parcel_id>/<str:period>/",
        calculation_runs.calculation_run_detail,
        name="calculation_run_detail",
    ),
    # Delivery Settings (staff-only agency efficiency + year-end policy)
    path("delivery-settings/", settings_pages.delivery_settings, name="delivery_settings"),
    # Methodology Settings (staff-only self-serve methodology tuning)
    path("methodology/", settings_pages.methodology_settings, name="methodology_settings"),
    path(
        "methodology/step/<int:step_id>/toggle/",
        settings_pages.methodology_step_toggle,
        name="methodology_step_toggle",
    ),
    path(
        "methodology/step/<int:step_id>/move/<str:direction>/",
        settings_pages.methodology_step_move,
        name="methodology_step_move",
    ),
    path(
        "methodology/step/<int:step_id>/config/",
        settings_pages.methodology_step_config,
        name="methodology_step_config",
    ),
    path(
        "methodology/load-default/",
        settings_pages.methodology_load_default,
        name="methodology_load_default",
    ),
    path(
        "methodology/preview/",
        settings_pages.methodology_preview,
        name="methodology_preview",
    ),
]
