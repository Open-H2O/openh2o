# SPDX-License-Identifier: AGPL-3.0-or-later
"""A zone's and an account's budget, worked by hand.

The districts come from ``tests.ledger_districts`` (their inputs are written at
the top of that module). Every expected figure is a literal worked with a
calculator, never recomputed with the engine's formula.

* A zone's groundwater Available is its allocation plus the groundwater it
  carried forward from last year, and nothing else: a recharge or seepage pool
  stands apart, and a pool of another water type never joins a groundwater
  budget.
* A field belongs to a zone, and to a water account, for a span of dates. A
  year's figures count the fields that belonged in that year, so taking a
  field out later leaves a finished year as it was. A field is never in two
  zones of one kind, or two accounts, at once.
* An account's share of a zone's allocation is by acres.
* The year-end rollover carries groundwater only, and carries a debt one for
  one until it is repaid; each account carries its own remainder.
"""

import datetime as dt
import importlib
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from accounting.models import AccountCredit, AllocationCarryover, WaterAccount, WaterAccountParcel
from geography.models import ParcelZone
from parcels.models import ParcelLedger

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

WY25, WY26 = "WY 2024-2025", "WY 2025-2026"


@pytest.fixture
def client():
    c = Client()
    c.force_login(get_user_model().objects.create_user(username="op", email="op@example.com", password="x"))
    return c


@pytest.fixture
def d1():
    ld.seed_reference()
    return ld.build_d1()


@pytest.fixture
def d2():
    ld.seed_reference()
    return ld.build_d2()


@pytest.fixture
def d3():
    ld.seed_reference()
    return ld.build_d3()


def run_d1():
    for m in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([m])


def run_d3():
    for m in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([m])


def carried(zone, year, code="GW"):
    rows = AllocationCarryover.objects.filter(
        zone=zone, water_year=year, water_type__code=code, origin="allocation_carryover")
    return sum((r.amount_af for r in rows), D("0"))


# ------------------------------------------------------------------ F-01
def test_d3_available_is_the_allocation_alone(d3):
    run_d3()
    row = ld.zone_budget(d3["gsa"], WY25)
    assert row["available"] == D("100.0000")
    assert row["carryover"] == D("0")
    assert row["used"] == D("20.0400")
    assert row["remaining"] == D("79.9600")


def test_d3_pools_are_their_own_lines_outside_available(d3):
    run_d3()
    row = ld.zone_budget(d3["gsa"], WY25)
    assert row["available"] == D("100.0000")
    assert row["credit_sources"] == []
    lines = dict(row["pool_sources"])
    assert lines["Managed recharge"] == D("50.0000")
    assert lines["Canal seepage"] == D("52.5000")


def test_a_surface_recharge_event_leaves_available_unchanged(d3):
    run_d3()
    ld.log_event(d3["site"], dt.date(2025, 8, 15), dt.date(2025, 8, 15), "20.0000", "SW")
    row = ld.zone_budget(d3["gsa"], WY25)
    assert row["available"] == D("100.0000")
    assert row["remaining"] == D("79.9600")


def test_dry_year_remaining_is_not_hidden_by_seepage():
    ld.seed_reference()
    d3 = ld.build_d3(dry=True, with_event=False)
    run_d3()
    row = ld.zone_budget(d3["gsa"], WY25)
    assert row["available"] == D("60.0000")
    assert row["used"] == D("82.2600")
    assert row["remaining"] == D("-22.2600")


# ------------------------------------------------------------------ F-09
def test_removing_a_field_from_a_zone_leaves_a_finished_year(d1, client):
    run_d1()
    before = ld.zone_budget(d1["gsa"], WY25)
    assert before["used"] == D("221.6667")
    link = ParcelZone.objects.get(zone=d1["gsa"], parcel=d1["F4"])
    resp = client.post(reverse("geography:zone_parcel_remove", args=[d1["gsa"].pk, link.pk]))
    assert resp.status_code == 200
    link.refresh_from_db()
    assert link.end_date == dt.date.today()
    after = ld.zone_budget(d1["gsa"], WY25)
    assert after["used"] == D("221.6667")
    assert after["remaining"] == D("-121.6667")


def test_a_field_that_left_before_a_year_began_is_not_counted_in_it(d1):
    ParcelZone.objects.filter(zone=d1["gsa"], parcel=d1["F4"]).update(end_date=dt.date(2025, 9, 30))
    ld.ledger(d1["F4"], dt.date(2026, 2, 1), -7, "meter_reading", "GW", "later reading")
    assert ld.zone_budget(d1["gsa"], WY26)["used"] == D("0.0000")
    ParcelZone.objects.filter(zone=d1["gsa"], parcel=d1["F4"]).update(end_date=None)
    assert ld.zone_budget(d1["gsa"], WY26)["used"] == D("7.0000")


def test_a_field_that_joined_after_a_year_ended_is_not_counted_in_it(d1):
    run_d1()
    ParcelZone.objects.filter(zone=d1["gsa"], parcel=d1["F4"]).update(start_date=dt.date(2026, 1, 1))
    assert ld.zone_budget(d1["gsa"], WY25)["used"] == D("171.6667")


def test_removing_a_field_from_an_account_leaves_a_finished_year(d1, client):
    run_d1()
    link = WaterAccountParcel.objects.get(water_account__account_number="D1-A", parcel=d1["F2"])
    client.post(reverse("accounting:remove_parcel", args=[link.water_account_id, link.pk]))
    link.refresh_from_db()
    assert link.removed_date == dt.date.today()
    row = ld.account_row(link.water_account, WY25)
    assert row["allocation"] == D("42.8571")
    assert row["remaining"] == D("-62.1429")


def test_a_field_cannot_join_a_second_account(d1, client):
    account_b = WaterAccount.objects.get(account_number="D1-B")
    resp = client.post(reverse("accounting:assign_parcel", args=[account_b.pk]), {"parcel_id": d1["F1"].pk})
    assert resp.status_code == 200
    assert not WaterAccountParcel.objects.filter(water_account=account_b, parcel=d1["F1"]).exists()
    assert "already in water account D1-A" in resp.content.decode()


def test_a_field_can_join_an_account_once_it_has_left_the_other(d1, client):
    account_a = WaterAccount.objects.get(account_number="D1-A")
    account_b = WaterAccount.objects.get(account_number="D1-B")
    link = WaterAccountParcel.objects.get(water_account=account_a, parcel=d1["F1"])
    client.post(reverse("accounting:remove_parcel", args=[account_a.pk, link.pk]))
    client.post(reverse("accounting:assign_parcel", args=[account_b.pk]), {"parcel_id": d1["F1"].pk})
    assert WaterAccountParcel.objects.filter(water_account=account_b, parcel=d1["F1"], removed_date=None).exists()


def test_a_field_cannot_join_a_second_zone_of_one_kind(d1, client):
    second = ld.make_zone("Second GSA", "management_area", -120.7, 37.0, -120.65, 37.05)
    resp = client.post(reverse("geography:zone_parcel_assign", args=[second.pk]), {"parcel_id": d1["F1"].pk})
    assert resp.status_code == 200
    assert not ParcelZone.objects.filter(zone=second, parcel=d1["F1"]).exists()
    assert "already in D1 GSA" in resp.content.decode()
    with pytest.raises(ValidationError):
        ParcelZone(zone=second, parcel=d1["F1"]).full_clean()


def test_a_field_can_sit_in_zones_of_two_kinds(d1, client):
    other = ld.make_zone("A service area", "custom", -120.7, 37.0, -120.65, 37.05)
    resp = client.post(reverse("geography:zone_parcel_assign", args=[other.pk]), {"parcel_id": d1["F1"].pk})
    assert resp.status_code == 200
    assert ParcelZone.objects.filter(zone=other, parcel=d1["F1"], end_date=None).exists()


def test_a_field_can_rejoin_a_zone_it_left(d1, client):
    link = ParcelZone.objects.get(zone=d1["gsa"], parcel=d1["F4"])
    client.post(reverse("geography:zone_parcel_remove", args=[d1["gsa"].pk, link.pk]))
    client.post(reverse("geography:zone_parcel_assign", args=[d1["gsa"].pk]), {"parcel_id": d1["F4"].pk})
    rows = ParcelZone.objects.filter(zone=d1["gsa"], parcel=d1["F4"])
    assert rows.count() == 2
    assert rows.filter(end_date=None).count() == 1


# ------------------------------------------------------------------ F-10
def test_d1_accounts_share_the_allocation_by_acres(d1):
    run_d1()
    a = ld.account_row(WaterAccount.objects.get(account_number="D1-A"), WY25)
    b = ld.account_row(WaterAccount.objects.get(account_number="D1-B"), WY25)
    assert a["allocation"] == D("42.8571")
    assert b["allocation"] == D("57.1429")
    assert a["remaining"] == D("-62.1429")
    assert b["remaining"] == D("-59.5238")


def test_an_account_remaining_includes_its_credits(d1):
    run_d1()
    ld.rollover(2025)
    a = WaterAccount.objects.get(account_number="D1-A")
    row = ld.account_row(a, WY26)
    assert row["allocation"] == D("42.8571")
    assert row["remaining"] == D("-19.2858")
    AccountCredit.objects.create(
        water_account=a, water_type=ld.wt("GW"), water_year=2026, origin="managed_recharge",
        amount_af=D("10.0000"), source_key="test", description="Recharge you logged")
    assert ld.account_row(a, WY26)["remaining"] == D("-9.2858")


def test_the_account_page_lists_each_credit_under_the_allocation(d1, client):
    run_d1()
    ld.rollover(2025)
    a = WaterAccount.objects.get(account_number="D1-A")
    resp = client.get(reverse("accounting:account_detail", args=[a.pk]) + f"?period={ld.period_of(dt.date(2025, 12, 1)).pk}")
    body = resp.content.decode()
    assert "Carried forward from WY 2024-2025" in body
    assert "-62.14" in body


# ------------------------------------------------------------------ F-11
def test_the_rollover_writes_no_surface_row(d2):
    ld.run_months(["2025-07"])
    ld.run_months(["2025-08"])
    ld.rollover(2025)
    assert not AllocationCarryover.objects.filter(water_type__code="SW").exists()
    assert AllocationCarryover.objects.count() == 0


def test_a_debt_is_carried_one_for_one(d1):
    run_d1()
    ld.rollover(2025)
    assert carried(d1["gsa"], 2026) == D("-121.6667")
    row = ld.zone_budget(d1["gsa"], WY26)
    assert row["available"] == D("-21.6667")
    assert row["remaining"] == D("-21.6667")


def test_a_debt_is_still_owed_after_a_year_of_no_use(d1):
    run_d1()
    ld.rollover(2025)
    ld.rollover(2026)
    assert carried(d1["gsa"], 2027) == D("-21.6667")


def test_each_account_carries_its_own_remainder(d1):
    run_d1()
    ld.rollover(2025)
    a = AccountCredit.objects.get(water_account__account_number="D1-A", water_year=2026)
    b = AccountCredit.objects.get(water_account__account_number="D1-B", water_year=2026)
    assert (a.origin, a.water_type.code, a.amount_af) == ("carried_forward", "GW", D("-62.1429"))
    assert b.amount_af == D("-59.5238")
    assert a.description == "Carried forward from WY 2024-2025"
    ld.rollover(2026)
    assert AccountCredit.objects.get(water_account__account_number="D1-A", water_year=2027).amount_af == D("-19.2858")
    assert AccountCredit.objects.get(water_account__account_number="D1-B", water_year=2027).amount_af == D("-2.3809")


def test_rolling_twice_writes_each_row_once(d1):
    run_d1()
    ld.rollover(2025)
    ld.rollover(2025)
    assert AccountCredit.objects.filter(origin="carried_forward").count() == 2
    assert AllocationCarryover.objects.filter(water_year=2026).count() == 1


def test_a_surplus_carries_unless_the_zone_lets_it_expire(d3):
    run_d3()
    ld.rollover(2025)
    assert carried(d3["gsa"], 2026) == D("79.9600")
    d3["gsa"].recovery_horizon = "same_water_year"
    d3["gsa"].save()
    ld.rollover(2025)
    assert carried(d3["gsa"], 2026) == D("0")


# ------------------------------------------------------------------ the canal row sentence
def test_a_share_row_says_where_its_share_came_from(d2):
    ld.run_months(["2025-07"])
    row = ParcelLedger.objects.filter(parcel=d2["G1"], divided_from_headgate=True, source_type="surface_diversion").get()
    assert row.description.endswith(
        "50%, taken from the shares entered for the canal, or from each use area's acreage where none were entered")
    assert "because no use area" not in row.description


def test_rows_stored_with_the_old_sentence_are_reworded(d2):
    ld.run_months(["2025-07"])
    row = ParcelLedger.objects.filter(parcel=d2["G1"], divided_from_headgate=True, source_type="surface_diversion").get()
    old = row.description.replace(
        ", taken from the shares entered for the canal, or from each use area's acreage where none were entered",
        ", because no use area the canal serves has an estimated use for the month")
    ParcelLedger.objects.filter(pk=row.pk).update(description=old)
    migration = importlib.import_module("parcels.migrations.0019_parcelledger_share_row_words_again")
    assert migration.reword_share_rows(ParcelLedger) == 1
    row.refresh_from_db()
    assert row.description.endswith("50%, taken from the shares entered for the canal, or from each use area's acreage where none were entered")
