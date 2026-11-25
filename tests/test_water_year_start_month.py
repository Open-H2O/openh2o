# SPDX-License-Identifier: AGPL-3.0-or-later
"""The water year's first month cannot move under a closed year, and no water year disagrees with it.

Two things read the setting as it is now: the lock on a finalized year's carry-over and
account credit rows, and the pool a voided recharge event takes its water from. Moving
the month after a year is finalized would protect the wrong rows. So the settings page
refuses a new first month once any water year is finalized or any recharge event is on
file, and a water year must start in the site's first month.

Test data is INVENTED.
"""
from datetime import date
from decimal import Decimal as D
from io import StringIO

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.test import RequestFactory

from accounting.forms import ReportingPeriodForm
from accounting.models import AllocationCarryover, ReportingPeriod
from core.forms import DeliverySettingsForm
from core.models import SiteConfig
from tests.factories import WaterTypeFactory, ZoneFactory

pytestmark = pytest.mark.django_db

SETTINGS = {
    "recovery_horizon": "carry_forward", "efficiency_percent": "75",
    "diversion_report_year_rule": "water_year", "over_delivery_treatment": "not_credited",
    "canal_seepage_credit": "none", "leave_behind_percent": "10",
}


def _site(month=10):
    config = SiteConfig.objects.first() or SiteConfig.objects.create(agency_name="Test Agency")
    config.water_year_start_month = month
    config.save()
    return config


def _finalized_year():
    return ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30),
        is_finalized=True,
    )


def _change_month_to(month):
    form = DeliverySettingsForm({**SETTINGS, "water_year_start_month": str(month)}, instance=_site_row())
    valid = form.is_valid()
    if valid:
        form.save()
    return form, valid


def _site_row():
    return SiteConfig.objects.order_by("pk").first()


# -- The settings page --------------------------------------------------------------------


def test_the_first_month_can_change_before_any_year_is_finalized():
    _site(10)
    ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30),
    )
    form, valid = _change_month_to(7)
    assert valid, form.errors
    assert _site_row().water_year_start_month == 7


def test_the_first_month_cannot_change_after_a_year_is_finalized():
    _site(10)
    _finalized_year()
    form, valid = _change_month_to(7)
    assert not valid
    assert form.errors.get("water_year_start_month")
    assert _site_row().water_year_start_month == 10


def test_the_same_month_sent_again_is_not_refused():
    # The page sends every field back; saving another setting keeps the month as it was.
    _site(10)
    _finalized_year()
    form, valid = _change_month_to(10)
    assert valid, form.errors


def test_the_first_month_cannot_change_after_a_recharge_event():
    from tests.factories import RechargeEventFactory

    _site(10)
    RechargeEventFactory()
    form, valid = _change_month_to(7)
    assert not valid
    assert form.errors.get("water_year_start_month")
    assert _site_row().water_year_start_month == 10


def test_the_admin_page_shows_the_month_read_only_once_it_is_locked():
    from core.admin import SiteConfigAdmin

    config = _site(10)
    request = RequestFactory().get("/")
    model_admin = SiteConfigAdmin(SiteConfig, admin.site)
    assert "water_year_start_month" not in model_admin.get_readonly_fields(request, config)
    _finalized_year()
    assert "water_year_start_month" in model_admin.get_readonly_fields(request, config)


def test_after_a_refused_change_the_lock_still_protects_the_closed_years_carryover():
    # Today's harm, had the change gone through: under a July start the closed year
    # Oct 2024 to Sep 2025 would be named 2026, and its own carry-over row (2025)
    # would be editable.
    _site(10)
    _finalized_year()
    zone, water_type = ZoneFactory(), WaterTypeFactory()
    _change_month_to(7)
    with pytest.raises(DatabaseError, match="finalized"):
        with transaction.atomic():
            AllocationCarryover.objects.create(
                zone=zone, water_type=water_type, water_year=2025, amount_af=D("4.0000"),
            )


# -- Creating a water year ------------------------------------------------------------------


def _form(start, end, name="A water year"):
    return ReportingPeriodForm({"name": name, "start_date": start, "end_date": end, "notes": ""})


def test_a_water_year_must_start_in_the_sites_first_month():
    _site(10)
    form = _form("2024-04-01", "2025-03-31")
    assert not form.is_valid()
    assert form.errors.get("start_date")


def test_a_water_year_starting_in_the_sites_month_is_accepted():
    _site(4)
    form = _form("2024-04-01", "2025-03-31")
    assert form.is_valid(), form.errors


def test_the_command_refuses_a_year_in_another_month_and_saves_nothing():
    _site(10)
    with pytest.raises(CommandError):
        call_command(
            "create_water_year", "--name", "April Year", "--start", "2024-04-01",
            "--end", "2025-03-31", stdout=StringIO(),
        )
    assert not ReportingPeriod.objects.exists()


def test_editing_an_older_year_that_disagrees_is_not_refused_for_its_month():
    # A year made before this rule keeps its dates; changing only its notes is allowed.
    _site(10)
    year = ReportingPeriod.objects.create(
        name="Calendar 2023", start_date=date(2023, 1, 1), end_date=date(2023, 12, 31),
    )
    form = ReportingPeriodForm(
        {"name": year.name, "start_date": "2023-01-01", "end_date": "2023-12-31", "notes": "x"},
        instance=year,
    )
    assert form.is_valid(), form.errors


def test_the_admin_page_refuses_a_year_in_another_month():
    from accounting.forms import ReportingPeriodAdminForm

    _site(10)
    form = ReportingPeriodAdminForm(
        {"name": "April Year", "start_date": "2024-04-01", "end_date": "2025-03-31", "notes": ""}
    )
    assert not form.is_valid()
    assert form.errors.get("start_date")
