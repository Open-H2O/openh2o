# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who is credited with recharge and with canal seepage, worked by hand.

The districts come from ``tests.ledger_districts`` (their inputs are written at
the top of that module). Every expected figure is a literal worked with a
calculator, never recomputed with the engine's formula.

* A recharge event is credited to the water account of whoever recharged: the
  account named on the recharge site. The credit is the volume less the share
  left in the basin (10 percent unless a setting says otherwise), it moves with
  an edit of the event and goes with a delete. The basin keeps its own record of
  the water, outside Available. A site with no account credits no one.
* Canal seepage is credited to no one unless a setting says otherwise: shared by
  acre among the fields the canal serves, or to the canal's owner only, in both
  cases less the share left in the basin.
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import AccountCredit, AllocationCarryover, WaterAccount, WaterAccountParcel
from core.models import SiteConfig
from geography.models import ParcelZone
from parcels.models import ParcelLedger
from recharge.models import RechargeEvent

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

WY25 = "WY 2024-2025"
AUG = (dt.date(2025, 8, 1), dt.date(2025, 8, 31))


@pytest.fixture
def client():
    c = Client()
    c.force_login(get_user_model().objects.create_user(username="op", email="op@example.com", password="x"))
    return c


@pytest.fixture
def d3():
    """D3 with no event yet, and the district's own water account on its basin."""
    ld.seed_reference()
    d3 = ld.build_d3(with_event=False)
    acct = WaterAccount.objects.create(name="D3 District", account_number="D3-D", unit_kind="farm_unit")
    d3["account"] = acct
    return d3


def credits(account, origin):
    return list(AccountCredit.objects.filter(water_account=account, origin=origin).order_by("source_key"))


def total(account, origin):
    return sum((c.amount_af for c in credits(account, origin)), D("0"))


def pool(zone, origin="basin_recharge_pool"):
    return sum((r.amount_af for r in AllocationCarryover.objects.filter(zone=zone, origin=origin)), D("0"))


def event_post(volume, **extra):
    data = {"start_date": "2025-08-01", "end_date": "2025-08-31", "volume_acre_feet": volume,
            "water_type": ld.wt("GW").pk, "source_description": "", "notes": ""}
    data.update(extra)
    return data


# ------------------------------------------------------------------ recharge
def test_a_basin_event_is_credited_to_the_account_on_its_site(d3):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    ld.log_event(d3["site"], *AUG, "50.0000", "GW")
    rows = credits(d3["account"], "managed_recharge")
    assert [r.amount_af for r in rows] == [D("45.0000")]
    assert rows[0].water_year == 2025
    assert rows[0].water_type.code == "GW"
    # the basin keeps its record of the water, and it stays out of Available
    assert pool(d3["gsa"]) == D("50.0000")
    assert ld.zone_budget(d3["gsa"], WY25)["available"] == D("100.0000")


def test_a_site_with_no_account_credits_no_one(d3):
    ld.log_event(d3["site"], *AUG, "50.0000", "GW")
    assert AccountCredit.objects.count() == 0
    assert pool(d3["gsa"]) == D("50.0000")


def test_the_site_page_says_when_no_account_is_credited(d3, client):
    body = client.get(reverse("recharge:detail", args=[d3["site"].pk])).content.decode()
    assert "Recharge here is not credited to a water account." in body


def test_the_site_page_names_the_account_that_is_credited(d3, client):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    body = client.get(reverse("recharge:detail", args=[d3["site"].pk])).content.decode()
    assert "Recharge here is credited to D3 District." in body


def test_the_site_form_names_the_account(d3, client):
    url = reverse("recharge:site_account", args=[d3["site"].pk])
    resp = client.post(url, {"water_account": d3["account"].pk})
    assert resp.status_code in (200, 302)
    d3["site"].refresh_from_db()
    assert d3["site"].water_account_id == d3["account"].pk


def test_the_view_credits_the_account_and_deleting_the_event_takes_it_back(d3, client):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    client.post(reverse("recharge:event_create", args=[d3["site"].pk]), event_post("50.0000"))
    assert total(d3["account"], "managed_recharge") == D("45.0000")
    assert pool(d3["gsa"]) == D("50.0000")
    event = RechargeEvent.objects.get()
    resp = client.post(reverse("recharge:event_delete", args=[d3["site"].pk, event.pk]))
    assert resp.status_code in (200, 302)
    assert RechargeEvent.objects.count() == 0
    assert AccountCredit.objects.count() == 0
    assert AllocationCarryover.objects.filter(origin="basin_recharge_pool").count() == 0


def test_editing_the_event_moves_the_credit_and_the_pool(d3, client):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    client.post(reverse("recharge:event_create", args=[d3["site"].pk]), event_post("50.0000"))
    event = RechargeEvent.objects.get()
    resp = client.post(reverse("recharge:event_edit", args=[d3["site"].pk, event.pk]), event_post("40.0000"))
    assert resp.status_code in (200, 302)
    assert [r.amount_af for r in credits(d3["account"], "managed_recharge")] == [D("36.0000")]
    assert pool(d3["gsa"]) == D("40.0000")


def test_moving_the_event_to_another_water_year_moves_the_credit(d3, client):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    client.post(reverse("recharge:event_create", args=[d3["site"].pk]), event_post("50.0000"))
    event = RechargeEvent.objects.get()
    client.post(reverse("recharge:event_edit", args=[d3["site"].pk, event.pk]),
                event_post("50.0000", start_date="2025-11-01", end_date="2025-11-30"))
    rows = credits(d3["account"], "managed_recharge")
    assert [(r.water_year, r.amount_af) for r in rows] == [(2026, D("45.0000"))]


def test_the_share_left_in_the_basin_is_a_setting(d3):
    SiteConfig.objects.update(over_delivery_leave_behind=D("0.200"))
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    ld.log_event(d3["site"], *AUG, "50.0000", "GW")
    assert total(d3["account"], "managed_recharge") == D("40.0000")


def test_a_has_well_field_recharge_credits_its_account_not_its_ledger(d3):
    from accounting.services import create_recharge_ledger_entries

    acct = WaterAccount.objects.create(name="H1 Farm", account_number="H1-F", unit_kind="farm_unit")
    WaterAccountParcel.objects.create(water_account=acct, parcel=d3["H1"])
    ev = RechargeEvent.objects.create(recharge_site=d3["site"], start_date=AUG[0], end_date=AUG[1],
                                      volume_acre_feet=D("10.0000"), water_type=ld.wt("GW"))
    entries = create_recharge_ledger_entries(ev, zone=d3["gsa"], parcel=d3["H1"])
    assert entries == []
    assert total(acct, "managed_recharge") == D("9.0000")
    assert not ParcelLedger.objects.filter(parcel=d3["H1"], source_type="recharge").exists()
    assert pool(d3["gsa"]) == D("0")


def test_a_surface_water_event_is_not_a_groundwater_credit(d3):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    ld.log_event(d3["site"], *AUG, "20.0000", "SW")
    credit = AccountCredit.objects.get()
    assert (credit.water_type.code, credit.amount_af) == ("SW", D("18.0000"))
    assert [c for c in AccountCredit.objects.filter(water_type__code="GW")] == []


def test_the_account_page_lists_the_recharge_credit(d3, client):
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    ld.log_event(d3["site"], *AUG, "50.0000", "GW")
    WaterAccountParcel.objects.create(water_account=d3["account"], parcel=d3["H1"])
    period = ld.period_of(dt.date(2025, 8, 1))
    body = client.get(reverse("accounting:account_detail", args=[d3["account"].pk]) + f"?period={period.pk}").content.decode()
    assert "Recharge at RB" in body
    assert "45.00" in body



def test_an_account_with_no_use_area_still_lists_its_recharge_credit(d3, client):
    # A district that runs basins and farms nothing has no zone ceiling, so no
    # allocation; its credit must still show on its page.
    d3["site"].water_account = d3["account"]
    d3["site"].save()
    ld.log_event(d3["site"], *AUG, "50.0000", "GW")
    period = ld.period_of(dt.date(2025, 8, 1))
    body = client.get(reverse("accounting:account_detail", args=[d3["account"].pk]) + f"?period={period.pk}").content.decode()
    assert "Groundwater budget" in body
    assert "Recharge at RB" in body
    assert "45.00" in body

# -------------------------------------------------------------- the settings
def test_delivery_settings_shows_and_saves_the_share_left_in_the_basin(client):
    ld.seed_reference()
    from django.contrib.auth import get_user_model as gum

    admin = gum().objects.create_user(username="ad", email="ad@example.com", password="x", agency_admin=True)
    client.force_login(admin)
    url = reverse("accounting:delivery_settings")
    body = client.get(url).content.decode()
    assert "Share left in the basin" in body
    form_values = {"efficiency_percent": 75, "recovery_horizon": "carry_forward",
                   "diversion_report_year_rule": "water_year", "over_delivery_treatment": "not_credited",
                   "canal_seepage_credit": "by_acre", "leave_behind_percent": 20}
    resp = client.post(url, form_values)
    assert resp.status_code == 302
    cfg = SiteConfig.objects.get()
    assert cfg.over_delivery_leave_behind == D("0.200")
    assert cfg.canal_seepage_credit == "by_acre"


def test_delivery_settings_defaults_credit_seepage_to_no_one():
    ld.seed_reference()
    assert SiteConfig.objects.get().canal_seepage_credit == "none"
    assert SiteConfig.objects.get().over_delivery_leave_behind == D("0.100")


# ------------------------------------------------------------------- seepage
def run_d3():
    for m in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([m])


def own_accounts(d3):
    a1 = WaterAccount.objects.create(name="H1 Farm", account_number="H1-F", unit_kind="farm_unit")
    a2 = WaterAccount.objects.create(name="H2 Farm", account_number="H2-F", unit_kind="farm_unit")
    WaterAccountParcel.objects.create(water_account=a1, parcel=d3["H1"])
    WaterAccountParcel.objects.create(water_account=a2, parcel=d3["H2"])
    return a1, a2


def test_seepage_is_credited_to_no_one_by_default(d3):
    own_accounts(d3)
    run_d3()
    assert AccountCredit.objects.filter(origin="canal_seepage").count() == 0
    assert pool(d3["gsa"], "conveyance_seepage_pool") == D("52.5000")
    assert ld.zone_budget(d3["gsa"], WY25)["available"] == D("100.0000")


def test_seepage_shared_by_acre_less_the_share_left_in_the_basin(d3):
    a1, a2 = own_accounts(d3)
    SiteConfig.objects.update(canal_seepage_credit="by_acre")
    run_d3()
    assert total(a1, "canal_seepage") == D("23.6250")
    assert total(a2, "canal_seepage") == D("23.6250")
    assert len(credits(a1, "canal_seepage")) == 3  # one per point and month
    assert pool(d3["gsa"], "conveyance_seepage_pool") == D("52.5000")
    assert ld.zone_budget(d3["gsa"], WY25)["available"] == D("100.0000")


def test_a_rerun_does_not_credit_seepage_twice(d3):
    a1, a2 = own_accounts(d3)
    SiteConfig.objects.update(canal_seepage_credit="by_acre")
    run_d3()
    ld.run_months(["2025-08"])
    run_d3()
    assert total(a1, "canal_seepage") == D("23.6250")
    assert len(credits(a1, "canal_seepage")) == 3


def test_a_field_with_no_account_is_skipped_and_its_part_is_credited_to_no_one(d3):
    a1, _ = own_accounts(d3)
    WaterAccountParcel.objects.filter(parcel=d3["H2"]).delete()
    SiteConfig.objects.update(canal_seepage_credit="by_acre")
    run_d3()
    assert total(a1, "canal_seepage") == D("23.6250")
    assert AccountCredit.objects.filter(origin="canal_seepage").count() == 3


def test_seepage_to_the_canal_owner_only(d3):
    a1, a2 = own_accounts(d3)
    d3["P3"].owner_account = d3["account"]
    d3["P3"].save()
    SiteConfig.objects.update(canal_seepage_credit="owner")
    run_d3()
    assert total(d3["account"], "canal_seepage") == D("47.2500")
    assert total(a1, "canal_seepage") == D("0")
    assert total(a2, "canal_seepage") == D("0")


def test_a_point_with_no_owner_credits_no_one_under_the_owner_choice(d3):
    own_accounts(d3)
    SiteConfig.objects.update(canal_seepage_credit="owner")
    run_d3()
    assert AccountCredit.objects.filter(origin="canal_seepage").count() == 0


def test_going_back_to_no_one_takes_the_seepage_credits_away(d3):
    own_accounts(d3)
    SiteConfig.objects.update(canal_seepage_credit="by_acre")
    run_d3()
    assert AccountCredit.objects.filter(origin="canal_seepage").count() == 6
    SiteConfig.objects.update(canal_seepage_credit="none")
    run_d3()
    assert AccountCredit.objects.filter(origin="canal_seepage").count() == 0


def test_the_point_form_names_the_owner(d3, client):
    url = reverse("surface:pod_edit", args=[d3["P3"].pk])
    assert "Canal owner" in client.get(url).content.decode()


def test_the_point_form_saves_the_owner(d3, client):
    url = reverse("surface:pod_edit", args=[d3["P3"].pk])
    resp = client.get(url)
    form = resp.context["form"]
    data = {name: (form[name].value() if form[name].value() is not None else "") for name in form.fields}
    data["owner_account"] = d3["account"].pk
    resp = client.post(url, data)
    assert resp.status_code == 302, getattr(resp, "context", None) and resp.context["form"].errors
    d3["P3"].refresh_from_db()
    assert d3["P3"].owner_account_id == d3["account"].pk


# ------------------------------------------------------------- the canal page
def test_the_canal_page_shows_the_left_over_column_only_when_dividing_by_crop_et(d3, client):
    run_d3()
    url = reverse("surface:pod_detail", args=[d3["P3"].pk])
    heading = "Left after each field received its ETAW divided by its irrigation efficiency"
    assert heading not in client.get(url).content.decode()
    d3["P3"].division_method = "crop_need"
    d3["P3"].save()
    assert heading in client.get(url).content.decode()


# ------------------------------------------------- membership in force
def test_the_pool_zone_is_the_membership_in_force(d3):
    from accounting.services import parcel_pool_zone

    ParcelZone.objects.filter(parcel=d3["H1"], zone=d3["gsa"]).update(end_date=dt.date(2025, 3, 31))
    assert parcel_pool_zone(d3["H1"], on=dt.date(2025, 2, 1)) == d3["gsa"]
    assert parcel_pool_zone(d3["H1"], on=dt.date(2025, 8, 1)) is None


def test_the_use_ledger_zone_filter_reads_membership_in_the_period(d3, client):
    ld.ledger(d3["H1"], dt.date(2025, 11, 1), -7, "meter_reading", "GW", desc="marker-row-nov")
    period = ld.period_of(dt.date(2025, 11, 1))
    url = reverse("accounting:ledger_list") + f"?zone={d3['gsa'].pk}&period={period.pk}"
    assert "marker-row-nov" in client.get(url).content.decode()
    ParcelZone.objects.filter(parcel=d3["H1"], zone=d3["gsa"]).update(end_date=dt.date(2025, 3, 31))
    assert "marker-row-nov" not in client.get(url).content.decode()
