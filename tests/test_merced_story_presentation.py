# SPDX-License-Identifier: AGPL-3.0-or-later
"""Presentation guards for the Merced story surfaces (Phase 52-02).

52-01 proved the ledger DATA is correct. This file proves the pages an evaluator
actually lands on TELL that story — the gaps caught at the 52-02 human-verify gate:

1. The account-detail page must open on the period where the account has activity,
   not an allocation-only (or empty) year that shows usage=0 everywhere and hides
   the simple-vs-complex contrast.
2. The surface-district service-area zones must carry ParcelZone links (so the zone
   page lists its parcels AND can total delivered-vs-budget).
3. The zone-detail page must show budget VS USE (pumped for groundwater budgets,
   delivered for surface budgets), not budget alone.
4. The curtailment must read as a narrative (a flag + the order) on the curtailed
   account and district zone — not only as a quietly smaller number.

The fixture is the same hermetic Phase-51-03 physical slice the 52-01 invariant
tests build, with the 52-01 ledger seed run on top.
"""
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client

from accounting.models import ReportingPeriod, WaterAccount, WaterAccountParcel
from accounting.services import account_consumptive_balance
from geography.models import ParcelZone, Zone
from surface.models import PointOfDiversion, PointOfDiversionParcel, WaterRight

from tests.test_merced_ledgers import (
    CURTAILED_RIGHT,
    NORMAL_RIGHT,
    OPEN_WY,
    PRIOR_WY,
    _build_physical_merced,
)


@pytest.fixture
def seeded_site(db):
    """Physical slice + ledger seed + a logged-in client."""
    _build_physical_merced()
    call_command("seed_merced_ledgers")
    from core.models import User

    user = User.objects.create(
        username="viewer", email="viewer@example.com",
        password=make_password("x"), is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _district_zone(right_id):
    return Zone.objects.get(
        zone_type="custom",
        name__startswith="MER Surface Service Area",
        name__contains=right_id,
    )


def _curtailed_account():
    """The account whose parcels are served by the curtailed right."""
    pods = PointOfDiversion.objects.filter(water_right__right_id=CURTAILED_RIGHT)
    parcel_ids = PointOfDiversionParcel.objects.filter(
        point_of_diversion__in=pods
    ).values_list("parcel_id", flat=True)
    acct_id = (
        WaterAccountParcel.objects.filter(parcel_id__in=parcel_ids)
        .values_list("water_account_id", flat=True)
        .first()
    )
    return WaterAccount.objects.get(id=acct_id)


# ---------------------------------------------------------------------------
# Fix #1 — account-detail default period lands on the activity year
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_account_detail_defaults_to_activity_period_not_empty_open_year(seeded_site):
    """A conjunctive account opened with no period filter must land on the period
    that has real usage — so usage reads non-zero and the story is visible."""
    # A conjunctive account (has groundwater extraction) — the curtailed Plainsburg
    # account qualifies (its conjunctive parcels substitute groundwater).
    account = _curtailed_account()
    resp = seeded_site.get(f"/accounting/accounts/{account.pk}/")
    assert resp.status_code == 200
    selected = resp.context["selected_period"]
    assert selected is not None, "account page should auto-select a period"
    assert selected.name == PRIOR_WY, (
        f"expected the activity year {PRIOR_WY}, got {selected.name} "
        "(the open year shows allocations only — usage would read 0 everywhere)"
    )
    # And the balance on that default page actually shows supplies (the story
    # lands). 57-02: the page now reads the consumptive lens, so we proxy "real
    # activity" with the supplies total — non-zero in the activity year, zero in
    # the allocation-only open year. (Consumptive use itself reads 0 in this
    # engine-less fixture until Phase 58 runs the engine.)
    assert resp.context["balance"]["supply_total"] > Decimal("0"), (
        "default account page should show non-zero supplies, not an empty open year"
    )


@pytest.mark.django_db
def test_account_default_period_has_more_usage_than_open_year(seeded_site):
    """Guard the regression directly: the open year shows ~zero activity; the
    default must not be the open year (measured by the supplies total under the
    57-02 consumptive lens)."""
    account = _curtailed_account()
    open_year_supply = account_consumptive_balance(
        account, reporting_period=ReportingPeriod.objects.get(name=OPEN_WY)
    )["supply_total"]
    resp = seeded_site.get(f"/accounting/accounts/{account.pk}/")
    default_supply = resp.context["balance"]["supply_total"]
    assert default_supply > open_year_supply


@pytest.mark.django_db
def test_dashboard_defaults_to_activity_period_with_nonzero_usage(seeded_site):
    """The Budget Summary tiles must roll up a period that has real activity, not
    the open year that holds only allocations. 57-02: under the consumptive lens
    the proxy is grand_supply_total (the surface + groundwater supplies), non-zero
    only in the activity year."""
    resp = seeded_site.get("/accounting/dashboard/")
    assert resp.status_code == 200
    selected = resp.context["selected_period"]
    assert selected is not None and selected.name == PRIOR_WY, (
        f"dashboard should open on the activity year {PRIOR_WY}, got "
        f"{getattr(selected, 'name', None)}"
    )
    assert resp.context["grand_supply_total"] > Decimal("0"), (
        "dashboard total supplies should be > 0, not the empty open year"
    )


# ---------------------------------------------------------------------------
# Fix #2 — district service-area zones carry ParcelZone links
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_district_zones_have_parcel_links(seeded_site):
    for right_id in (NORMAL_RIGHT, CURTAILED_RIGHT):
        zone = _district_zone(right_id)
        served = ParcelZone.objects.filter(zone=zone).count()
        assert served > 0, (
            f"district zone for {right_id} has no parcel links — its page would "
            "list no parcels and total zero delivered"
        )


# ---------------------------------------------------------------------------
# Fix #3 — zone-detail shows budget VS USE
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_gsa_zone_detail_shows_groundwater_pumped_against_budget(seeded_site):
    gsa = Zone.objects.filter(
        zone_type="management_area", basin_code="5-022.04"
    ).first()
    resp = seeded_site.get(f"/map/zones/{gsa.pk}/")
    assert resp.status_code == 200
    budgets = resp.context["budgets"]
    assert budgets, "GSA zone should expose budget-vs-use rows"
    gw = [b for b in budgets if (b["water_type"].code or "").upper() == "GW"]
    assert gw, "GSA zone should have a groundwater budget row"
    assert all(b["used_label"] == "pumped" for b in gw)
    # The prior (activity) year should show real pumping against the budget.
    prior = [b for b in gw if b["period"].name == PRIOR_WY]
    assert prior and prior[0]["used"] > Decimal("0"), (
        "GSA prior-year groundwater 'used' should be > 0 (pumping happened)"
    )
    assert prior[0]["remaining"] == prior[0]["budget"] - prior[0]["used"]


@pytest.mark.django_db
def test_surface_district_zone_detail_shows_delivered_against_budget(seeded_site):
    zone = _district_zone(NORMAL_RIGHT)
    resp = seeded_site.get(f"/map/zones/{zone.pk}/")
    assert resp.status_code == 200
    budgets = resp.context["budgets"]
    sw = [b for b in budgets if (b["water_type"].code or "").upper() == "SW"]
    assert sw, "district zone should have a surface budget row"
    assert all(b["used_label"] == "delivered" for b in sw)
    prior = [b for b in sw if b["period"].name == PRIOR_WY]
    assert prior and prior[0]["used"] > Decimal("0"), (
        "district prior-year surface 'delivered' should be > 0"
    )


# ---------------------------------------------------------------------------
# Fix #4 — curtailment reads as a narrative
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_curtailed_district_zone_is_flagged(seeded_site):
    zone = _district_zone(CURTAILED_RIGHT)
    resp = seeded_site.get(f"/map/zones/{zone.pk}/")
    assert resp.context["is_curtailed"] is True
    assert resp.context["curtailment_orders"], (
        "curtailed district zone should surface its curtailment order"
    )


@pytest.mark.django_db
def test_normal_district_zone_is_not_flagged(seeded_site):
    zone = _district_zone(NORMAL_RIGHT)
    resp = seeded_site.get(f"/map/zones/{zone.pk}/")
    assert resp.context["is_curtailed"] is False


@pytest.mark.django_db
def test_curtailed_account_is_flagged(seeded_site):
    account = _curtailed_account()
    resp = seeded_site.get(f"/accounting/accounts/{account.pk}/")
    assert resp.context["is_curtailed"] is True
    assert resp.context["curtailment_orders"]


@pytest.mark.django_db
def test_normal_account_is_not_flagged(seeded_site):
    """An account with no curtailed right shows no curtailment banner."""
    # Find an account none of whose parcels is under a curtailed right.
    curtailed_pids = set(
        WaterRight.objects.filter(status="curtailed")
        .values_list("water_right_parcels__parcel_id", flat=True)
    )
    normal = None
    for acct in WaterAccount.objects.filter(account_number__startswith="MER-ACCT-"):
        pids = set(
            WaterAccountParcel.objects.filter(water_account=acct).values_list(
                "parcel_id", flat=True
            )
        )
        if pids and not (pids & curtailed_pids):
            normal = acct
            break
    assert normal is not None, "fixture should have a non-curtailed account"
    resp = seeded_site.get(f"/accounting/accounts/{normal.pk}/")
    assert resp.context["is_curtailed"] is False
