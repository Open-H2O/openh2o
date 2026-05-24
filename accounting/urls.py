from django.urls import path

from accounting import views

app_name = "accounting"

urlpatterns = [
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
]
