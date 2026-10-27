# SPDX-License-Identifier: AGPL-3.0-or-later
"""A meter reading entered once on the well, and canal water beyond crop need.

The districts come from ``tests.ledger_districts`` (their inputs are written at
the top of that module). Every expected figure is a literal worked with a
calculator, never recomputed with the engine's formula.

* A well's meter reading is entered once, on the well. The month's calculation
  splits it among the fields the well waters by each field's share of the well,
  evenly where the shares are untouched. A field on a metered well gets no
  estimate that month.
* A field that carries its own meter-reading row for the month keeps it, and
  the well's reading is not added on top of it.
* The "credited" choice for canal water beyond crop need is gone: nothing is
  credited to a field and nothing is pooled, whatever an older site stored.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import AllocationCarryover, CalculationRun
from accounting.services import consumptive_use_balance
from core.models import SiteConfig
from measurements.models import Meter, MeterReading
from parcels.models import ParcelLedger
from wells.models import WellIrrigatedParcel

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

Z = D("0.0001")


def _aware(day, hour=14):
    return timezone.make_aware(dt.datetime(day.year, day.month, day.day, hour, 0))


@pytest.fixture
def d1():
    """D1 with W1's meter taken off the two fields' ledgers: it is entered on the well instead."""
    ld.seed_reference()
    d1 = ld.build_d1()
    ParcelLedger.objects.filter(
        parcel__in=(d1["F1"], d1["F2"]), source_type="meter_reading"
    ).delete()
    d1["meter"] = Meter.objects.get(serial_number="D1-W1-METER")
    return d1


def read_well(d1, day, previous, current, volume=None):
    return MeterReading.objects.create(
        meter=d1["meter"], reading_date=_aware(day),
        previous_value=None if previous is None else D(str(previous)), current_value=D(str(current)),
        calculated_volume=None if volume is None else D(str(volume)),
    )


def set_shares(d1, f1, f2):
    WellIrrigatedParcel.objects.filter(parcel=d1["F1"]).update(fraction=D(str(f1)))
    WellIrrigatedParcel.objects.filter(parcel=d1["F2"]).update(fraction=D(str(f2)))


def meter_af(parcel, month):
    rows = ParcelLedger.objects.filter(
        parcel=parcel, source_type="meter_reading",
        effective_date__year=month.year, effective_date__month=month.month,
    )
    return sum((abs(r.amount_acre_feet) for r in rows), D("0")).quantize(Z)


def calculated_rows(parcel, month):
    return ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated",
        effective_date__year=month.year, effective_date__month=month.month,
    ).count()


def charged(d1):
    """What W1's two fields are charged: the account-row figure for the pair."""
    ids = [d1["F1"].id, d1["F2"].id]
    period = ld.period_of(ld.AUG)
    return consumptive_use_balance(ids, period)["groundwater_charged"].quantize(Z)


# ------------------------------------------------------------------ F-08
def test_a_well_reading_is_split_by_the_fields_shares(d1):
    set_shares(d1, "0.2", "0.1")  # two thirds and one third
    read_well(d1, dt.date(2025, 8, 31), 1000, 1036, volume=36)
    ld.run_months(["2025-08"])
    assert meter_af(d1["F1"], ld.AUG) == D("24.0000")
    assert meter_af(d1["F2"], ld.AUG) == D("12.0000")
    assert calculated_rows(d1["F1"], ld.AUG) == 0
    assert calculated_rows(d1["F2"], ld.AUG) == 0
    assert charged(d1) == D("36.0000")


def test_a_well_reading_is_split_evenly_where_the_shares_are_untouched(d1):
    read_well(d1, dt.date(2025, 8, 31), 1000, 1036, volume=36)
    ld.run_months(["2025-08"])
    assert meter_af(d1["F1"], ld.AUG) == D("18.0000")
    assert meter_af(d1["F2"], ld.AUG) == D("18.0000")
    assert calculated_rows(d1["F1"], ld.AUG) == 0
    assert calculated_rows(d1["F2"], ld.AUG) == 0
    assert charged(d1) == D("36.0000")


def test_a_second_calculation_does_not_count_the_reading_twice(d1):
    read_well(d1, dt.date(2025, 8, 31), 1000, 1036, volume=36)
    ld.run_months(["2025-08"])
    ld.run_months(["2025-08"])
    assert meter_af(d1["F1"], ld.AUG) == D("18.0000")
    assert charged(d1) == D("36.0000")


def test_a_changed_reading_replaces_what_the_last_calculation_wrote(d1):
    reading = read_well(d1, dt.date(2025, 8, 31), 1000, 1036, volume=36)
    ld.run_months(["2025-08"])
    reading.calculated_volume = D("40")
    reading.save()
    ld.run_months(["2025-08"])
    assert charged(d1) == D("40.0000")
    reading.delete()
    ld.run_months(["2025-08"])
    assert meter_af(d1["F1"], ld.AUG) == D("0.0000")
    assert calculated_rows(d1["F1"], ld.AUG) == 1  # no meter that month: estimated again


def test_a_totalizer_without_a_stored_volume_is_the_difference_against_the_last_reading(d1):
    read_well(d1, dt.date(2025, 7, 31), 960, 1000, volume=None)
    read_well(d1, dt.date(2025, 8, 31), None, 1036, volume=None)
    ld.run_months(["2025-08"])
    assert charged(d1) == D("36.0000")


def test_a_meter_in_gallons_is_turned_into_acre_feet(d1):
    d1["meter"].unit = "gallons"
    d1["meter"].save()
    read_well(d1, dt.date(2025, 8, 31), 0, 3258510, volume=3258510)  # 10 AF
    ld.run_months(["2025-08"])
    assert charged(d1) == D("10.0000")


def test_a_field_with_its_own_meter_row_keeps_it_and_takes_no_share_of_the_well(d1):
    ld.ledger(d1["F1"], ld.AUG, -24, "meter_reading", "GW", "meter reading entered on the field")
    read_well(d1, dt.date(2025, 8, 31), 1000, 1036, volume=36)
    ld.run_months(["2025-08"])
    assert meter_af(d1["F1"], ld.AUG) == D("24.0000")
    assert meter_af(d1["F2"], ld.AUG) == D("0.0000")


def test_the_well_page_takes_a_reading_and_lists_it(d1):
    user = get_user_model().objects.create_user(username="reader-eb", password="pw-eb-12345")
    client = Client()
    client.force_login(user)
    url = reverse("wells:meter_reading_add", kwargs={"pk": d1["W1"].pk})
    response = client.post(url, {"reading_date": "2025-08-31", "current_value": "1036.0000"})
    assert response.status_code in (200, 302)
    reading = MeterReading.objects.get(meter=d1["meter"])
    assert reading.current_value == D("1036.0000")
    page = client.get(reverse("wells:detail", kwargs={"pk": d1["W1"].pk})).content.decode()
    assert "Record a meter reading" in page
    assert "1,036.00" in page


def test_the_well_page_refuses_a_reading_with_no_date(d1):
    user = get_user_model().objects.create_user(username="reader-eb2", password="pw-eb-12345")
    client = Client()
    client.force_login(user)
    url = reverse("wells:meter_reading_add", kwargs={"pk": d1["W1"].pk})
    client.post(url, {"reading_date": "", "current_value": "1036"})
    assert MeterReading.objects.filter(meter=d1["meter"]).count() == 0


# ------------------------------------------------------------------ F-17
def _s5b():
    ld.seed_reference()
    d3 = ld.build_d3(with_event=False)
    ld.add_h3_h4(d3)
    return d3


def test_delivery_settings_offers_two_choices_for_canal_water_beyond_crop_need():
    from core.forms import DeliverySettingsForm

    ld.seed_reference()
    form = DeliverySettingsForm(instance=SiteConfig.objects.first())
    values = [value for value, _ in form.fields["over_delivery_treatment"].choices]
    assert values == ["not_credited", "named_line"]


def test_a_site_stored_as_credited_writes_no_recharge_row_and_no_pool():
    d3 = _s5b()
    SiteConfig.objects.update(over_delivery_treatment="credited")
    ld.run_months(["2025-01"])
    assert ParcelLedger.objects.filter(source_type="recharge").count() == 0
    assert AllocationCarryover.objects.count() == 0
    run = CalculationRun.objects.get(parcel=d3["H3"], period="2025-01")
    assert run.over_delivery_credited_af is None
    assert run.over_delivery_credit_pooled is False


def test_the_migration_moves_a_credited_site_to_not_credited():
    import importlib

    ld.seed_reference()
    SiteConfig.objects.update(over_delivery_treatment="credited")
    from django.apps import apps as django_apps

    module = importlib.import_module("core.migrations.%s" % _MIGRATION)
    module.move_credited_to_not_credited(django_apps, None)
    assert SiteConfig.objects.first().over_delivery_treatment == "not_credited"


_MIGRATION = "0018_credited_over_delivery_removed"
