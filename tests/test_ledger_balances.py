# SPDX-License-Identifier: AGPL-3.0-or-later
"""What counts as groundwater, how it is balanced, and what the footers add.

The districts come from ``tests.ledger_districts`` (their inputs are written at
the top of that module). Every expected figure is a literal worked with a
calculator, never recomputed with the engine's formula.

* A groundwater figure (Used, an account's Groundwater, Remaining) counts rows
  of the groundwater water type and the engine's own estimates. A row of another
  type, or of none, is not groundwater, and a satellite estimate on a field with
  no well is unmet demand, never pumping.
* Groundwater is counted as pumped (extraction) on a metered field and on an
  estimated one alike, with the water the crop did not consume shown as a use,
  so two fields farmed alike balance alike. An account with no calculation runs
  adds nothing to the balance in the footer.
* The Use Ledger's "Delivered and pumped" adds estimated pumping, not the
  consumption an estimate was made from.
* The field page's line for applied water not consumed counts canal water beyond
  what the crop could use, canal water beyond its need, and pumped water beyond
  what it consumed.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun, ReportingPeriod, WaterAccount, WaterAccountParcel
from accounting.services import parcel_consumptive_balance, parcel_mass_balance
from accounting.views.accounts import _account_rows_with_totals
from parcels.models import ParcelLedger

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

WY25 = "WY 2024-2025"
JUL = dt.date(2025, 7, 1)


@pytest.fixture
def client():
    c = Client()
    c.force_login(get_user_model().objects.create_user(username="op-bl", email="op-bl@example.com", password="x"))
    return c


@pytest.fixture
def d1():
    ld.seed_reference()
    return ld.build_d1()


def _raw_row(parcel, date, amount, source, wtype=None, desc="hand-entered test input"):
    """A ledger row with its water type left as given (``None`` is a row with no type)."""
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=ld.TODAY, effective_date=date, amount_acre_feet=D(str(amount)),
        source_type=source, water_type=ld.wt(wtype) if wtype else None, description=desc,
        reporting_period=ld.period_of(date))


# ------------------------------------------------------------------ groundwater
def test_an_entry_with_no_water_type_leaves_groundwater_and_remaining_unchanged(d1):
    account = WaterAccount.objects.get(account_number="D1-A")
    before = ld.account_row(account, WY25)
    assert before["groundwater"] == D("105.0000")  # 45 + 36 + 24 AF of meter rows on F1 and F2
    _raw_row(d1["F1"], dt.date(2025, 8, 15), "-10.0000", "manual_entry")
    after = ld.account_row(account, WY25)
    assert after["groundwater"] == D("105.0000")
    assert after["remaining"] == before["remaining"]


def test_a_satellite_row_on_a_field_with_no_well_adds_nothing_to_used(d1):
    f5 = ld.add_field("F5", 100, "Alfalfa", None, [d1["gsa"]], -120.47, 37.2, [{"2025-07": 91.44}])
    assert ld.zone_budget(d1["gsa"], WY25)["used"] == D("105.0000")
    _raw_row(f5, JUL, "-21.4209", "et_estimate")
    assert ld.zone_budget(d1["gsa"], WY25)["used"] == D("105.0000")


def test_a_satellite_row_on_a_field_with_a_well_is_still_pumping(d1):
    _raw_row(d1["F3"], JUL, "-10.0000", "et_estimate")  # F3 has its own well W2
    assert ld.zone_budget(d1["gsa"], WY25)["used"] == D("115.0000")


def test_a_meter_row_with_no_water_type_is_pumping_but_one_typed_as_canal_water_is_not(d1):
    _raw_row(d1["F3"], dt.date(2025, 8, 15), "-10.0000", "meter_reading")
    assert ld.zone_budget(d1["gsa"], WY25)["used"] == D("115.0000")
    _raw_row(d1["F3"], dt.date(2025, 8, 16), "-10.0000", "meter_reading", "SW")
    assert ld.zone_budget(d1["gsa"], WY25)["used"] == D("115.0000")


# ------------------------------------------------------------------ the balance
def _twins():
    """Two fields farmed alike: 100 acres, 100 AF of crop ET in July, a well each, efficiency 0.75.

    ``A`` has no meter (the engine estimates its pumping). ``B`` carries a meter
    reading of 133.3333 AF, which at 0.75 is exactly the 100 AF the crop used.
    """
    ld.seed_reference()
    gsa = ld.make_zone("Twin GSA", "management_area", -120.6, 37.1, -120.4, 37.3)
    a = ld.add_field("TA", 100, "Alfalfa", None, [gsa], -120.55, 37.2, [{"2025-07": 304.8}],
                     ld.make_well("TWA", -120.545, 37.21))
    b = ld.add_field("TB", 100, "Alfalfa", None, [gsa], -120.51, 37.2, [{"2025-07": 304.8}],
                     ld.make_well("TWB", -120.505, 37.21))
    ld.ledger(b, JUL, "-133.3333", "meter_reading", "GW", "meter reading entered on the field")
    ld.run_months(["2025-07"])
    return a, b


def test_a_metered_and_an_estimated_field_farmed_alike_both_balance_at_zero():
    a, b = _twins()
    est = parcel_consumptive_balance(a, ReportingPeriod.objects.get(name=WY25))
    met = parcel_consumptive_balance(b, ReportingPeriod.objects.get(name=WY25))
    assert est["supplies"]["groundwater"] == D("133.3333")
    assert met["supplies"]["groundwater"] == D("133.3333")
    assert round(est["net_vs_supply"], 2) == D("0.00")
    assert round(met["net_vs_supply"], 2) == D("0.00")


def test_an_account_with_supply_and_no_runs_adds_nothing_to_the_footer_balance():
    ld.seed_reference()
    gsa = ld.make_zone("Quiet GSA", "management_area", -120.6, 37.1, -120.4, 37.3)
    f = ld.add_field("Q1", 100, "Alfalfa", None, [gsa], -120.55, 37.2, [])
    account = WaterAccount.objects.create(name="Quiet", account_number="Q-1", unit_kind="farm_unit")
    WaterAccountParcel.objects.create(water_account=account, parcel=f)
    ld.ledger(f, JUL, "-50.0000", "surface_diversion", "SW", "canal delivery with no calculation run")
    period = ReportingPeriod.objects.get(name=WY25)
    rows, totals = _account_rows_with_totals(WaterAccount.objects.filter(pk=account.pk), period, False, None)
    assert rows[0]["has_calculations"] is False
    assert rows[0]["surface"] == D("50.0000")
    assert totals["grand_net"] == D("0")


# ------------------------------------------------------------------ the Use Ledger footer
def test_delivered_and_pumped_adds_estimated_pumping_not_consumption(client):
    ld.seed_reference()
    gsa = ld.make_zone("Footer GSA", "management_area", -120.6, 37.1, -120.4, 37.3)
    f = ld.add_field("L1", 100, "Alfalfa", None, [gsa], -120.55, 37.2, [])
    ld.ledger(f, dt.date(2025, 7, 10), "-10.0000", "surface_diversion", "SW")
    ld.ledger(f, dt.date(2025, 8, 10), "-5.0000", "meter_reading", "GW")
    ld.ledger(f, dt.date(2025, 9, 1), "-7.5000", "calculated", "GW", "engine estimate")
    CalculationRun.objects.create(
        parcel=f, period="2025-09", gross_et_af=D("7.5"), net_consumptive_use_af=D("7.5"), final_af=D("7.5"),
        gw_extracted_af=D("10.0000"), groundwater_application_efficiency=D("0.750"),
        deep_percolation_gw_af=D("2.5000"))
    period = ReportingPeriod.objects.get(name=WY25)
    response = client.get(reverse("accounting:ledger_list") + f"?period={period.pk}")
    assert response.context["ledger_total_water"] == D("25.0000")


# ------------------------------------------------------------------ applied water not consumed
def test_ten_af_of_canal_water_at_0_80_against_a_need_of_six_shows_four():
    ld.seed_reference()
    gsa = ld.make_zone("Canal GSA", "management_area", -120.6, 37.1, -120.4, 37.3)
    f = ld.add_field("C1", 100, "Alfalfa", None, [gsa], -120.55, 37.2, [])
    ld.ledger(f, JUL, "-10.0000", "surface_diversion", "SW", "canal delivery")
    CalculationRun.objects.create(
        parcel=f, period="2025-07", gross_et_af=D("6"), net_consumptive_use_af=D("6"), final_af=D("0"),
        surface_delivered_af=D("10"), surface_water_af=D("8"), surface_efficiency=D("0.800"),
        over_delivery_af=D("2"), effective_precip_af=D("0"))
    result = parcel_mass_balance(f, ReportingPeriod.objects.get(name=WY25))
    assert result["deep_percolation_af"] == D("4.0000")


def test_a_winter_flood_shows_48_af_applied_and_not_consumed_on_both_fields():
    ld.seed_reference()
    d3 = ld.build_d3(with_event=False)
    ld.add_h3_h4(d3)
    ld.run_months(["2025-01"])
    for key in ("H3", "H4"):
        assert parcel_mass_balance(d3[key])["deep_percolation_af"] == D("48.0000")
