# SPDX-License-Identifier: AGPL-3.0-or-later
"""The month a water year starts in is a site setting, and every reader of the rule follows it.

October is the default. A site that keeps its year from January sets the
month once: recharge lands in the right year, the year lock follows, the
period lookup and the rollover command follow, and the year is named by its
calendar year. Every expected figure is a literal.
"""

import ast
import pathlib
from datetime import date
from decimal import Decimal as D

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.db import DatabaseError, transaction
from django.test import Client
from django.urls import reverse

from accounting.carryover_math import water_year_label, water_year_of
from accounting.models import AllocationCarryover
from accounting.services import (
    create_recharge_ledger_entries,
    water_year_periods,
    water_year_start_month,
)
from core.forms import DeliverySettingsForm
from core.models import SiteConfig
from tests.factories import (
    RechargeEventFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
    ParcelFactory,
    ParcelZoneFactory,
)

pytestmark = pytest.mark.django_db


def _site(month=None):
    config = SiteConfig.objects.first() or SiteConfig.objects.create(agency_name="Test Agency")
    if month is not None:
        config.water_year_start_month = month
        config.save()
    return config


def _pool(zone, year):
    return sum(
        (r.amount_af for r in AllocationCarryover.objects.filter(zone=zone, water_year=year)),
        D("0"),
    )


def _recharge_in_february(month):
    _site(month)
    zone = ZoneFactory(zone_type="management_area")
    ParcelZoneFactory(parcel=ParcelFactory(), zone=zone)
    event = RechargeEventFactory(start_date=date(2026, 2, 10), volume_acre_feet=D("100.0000"))
    create_recharge_ledger_entries(event, zone=zone)
    return zone


def test_january_start_puts_a_february_recharge_event_in_the_calendar_year():
    zone = _recharge_in_february(1)
    assert _pool(zone, 2026) == D("100.0000")
    assert _pool(zone, 2025) == D("0")


def test_default_start_puts_the_same_event_in_water_year_2025_2026():
    zone = _recharge_in_february(None)
    assert _pool(zone, 2026) == D("100.0000")
    assert _pool(zone, 2025) == D("0")
    # October's event is the one the two settings place differently.
    event = RechargeEventFactory(start_date=date(2025, 11, 5), volume_acre_feet=D("40.0000"))
    create_recharge_ledger_entries(event, zone=zone)
    assert _pool(zone, 2026) == D("140.0000")


def test_january_start_puts_a_november_event_in_its_own_calendar_year():
    _site(1)
    zone = ZoneFactory(zone_type="management_area")
    ParcelZoneFactory(parcel=ParcelFactory(), zone=zone)
    event = RechargeEventFactory(start_date=date(2025, 11, 5), volume_acre_feet=D("40.0000"))
    create_recharge_ledger_entries(event, zone=zone)
    assert _pool(zone, 2025) == D("40.0000")
    assert _pool(zone, 2026) == D("0")


def test_the_reader_returns_ten_with_no_site_row_and_the_stored_month_otherwise():
    assert water_year_start_month() == 10
    _site(4)
    assert water_year_start_month() == 4


def test_the_pure_rule_takes_the_month_and_the_label_names_a_calendar_year():
    assert water_year_of("2026-02", 1) == 2026
    assert water_year_of("2025-11", 10) == 2026
    assert water_year_label(2026, 10) == "WY 2025-2026"
    assert water_year_label(2026, 1) == "2026"
    assert water_year_label(2026, 4) == "WY 2025-2026"


def test_the_rule_module_still_imports_no_django():
    source = pathlib.Path("accounting/carryover_math.py").read_text()
    modules = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert not [m for m in modules if m.split(".")[0] == "django"]


def test_water_year_periods_under_a_january_start_returns_the_calendar_year():
    _site(1)
    calendar = ReportingPeriodFactory(
        name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    assert water_year_periods(2026) == [calendar]
    assert water_year_periods(2027) == []


def test_water_year_periods_under_the_default_keeps_october_to_september():
    _site()
    standard = ReportingPeriodFactory(
        name="WY 2025-2026", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    assert water_year_periods(2026) == [standard]


def _carryover(year):
    return AllocationCarryover(
        zone=ZoneFactory(), water_type=WaterTypeFactory(), water_year=year,
        amount_af=D("4.0000"),
    )


def test_the_lock_refuses_a_row_of_a_finalized_calendar_year_under_a_january_start():
    _site(1)
    ReportingPeriodFactory(
        name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        is_finalized=True,
    )
    with pytest.raises(DatabaseError, match="2026 is finalized"):
        with transaction.atomic():
            _carryover(2026).save()
    with transaction.atomic():
        _carryover(2025).save()


def test_the_lock_leaves_the_same_row_alone_under_the_default_start():
    _site()
    ReportingPeriodFactory(
        name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        is_finalized=True,
    )
    # A period ending in December belongs to water year 2027 under October.
    with transaction.atomic():
        _carryover(2026).save()
    with pytest.raises(DatabaseError, match="2026 is finalized"):
        with transaction.atomic():
            _carryover(2027).save()


def test_the_lock_follows_a_change_of_the_month_without_a_new_trigger():
    config = _site()
    ReportingPeriodFactory(
        name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        is_finalized=True,
    )
    config.water_year_start_month = 1
    config.save()
    with pytest.raises(DatabaseError, match="2026 is finalized"):
        with transaction.atomic():
            _carryover(2026).save()


def test_the_rollover_command_reads_the_setting_for_its_anchor_month():
    from django.core.management.base import CommandError

    _site(1)
    ReportingPeriodFactory(
        name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    # The calendar-year period is found (the next refusal is about allocations).
    with pytest.raises(CommandError, match="no AllocationPlan exists for water year 2026"):
        call_command("rollover_allocations", "--water-year", "2026", "--dry-run")
    # Under the default the same period belongs to water year 2027.
    _site(10)
    with pytest.raises(CommandError, match="no reporting period falls in water year 2026"):
        call_command("rollover_allocations", "--water-year", "2026", "--dry-run")


def test_the_well_history_groups_and_names_years_by_the_setting():
    from wells.measurement_history import water_year, water_year_label as well_label

    assert water_year(date(2026, 2, 1)) == 2026
    assert water_year(date(2025, 11, 1)) == 2026
    assert well_label(2026) == "WY 2025-2026"
    _site(1)
    assert water_year(date(2025, 11, 1)) == 2025
    assert well_label(2026) == "2026"


class _Staff(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"yearadmin{n}")
    email = factory.Sequence(lambda n: f"yearadmin{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True


def test_the_settings_page_offers_the_month_and_saves_it():
    config = _site()
    client = Client()
    client.force_login(_Staff())
    page = client.get(reverse("accounting:delivery_settings"))
    assert page.status_code == 200
    assert "Which month does your water year start in?" in page.content.decode()
    form = DeliverySettingsForm(
        {"recovery_horizon": "carry_forward", "efficiency_percent": "75",
         "water_year_start_month": "1", "diversion_report_year_rule": "water_year",
         "over_delivery_treatment": "not_credited", "canal_seepage_credit": "none",
         "leave_behind_percent": "10"},
        instance=config,
    )
    assert form.is_valid(), form.errors
    form.save()
    config.refresh_from_db()
    assert config.water_year_start_month == 1


def test_the_form_refuses_a_month_that_is_not_a_month():
    form = DeliverySettingsForm(
        {"recovery_horizon": "carry_forward", "water_year_start_month": "13"},
        instance=_site(),
    )
    assert not form.is_valid()
    assert form.errors["water_year_start_month"] == ["No month is numbered 13."]
