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
# Fix #1 — the auto-selected period is one that has activity
#
# ⚠ THESE THREE USED TO PIN THE PERIOD NAME, and the pin expired (133-02).
# They were written when WY 2025-2026 held allocations and nothing else, so
# `selected.name == PRIOR_WY` was a workable stand-in for "landed somewhere with
# usage on it". Phase 133 gave the open year a full demand AND supply side, so
# the newest period now has activity too and the pages correctly open on it —
# and the old assertion failed on a behaviour that had improved. The guard that
# matters has always been "never open on an empty period", so that is what these
# assert now, plus the new fact that makes the name-pin meaningless: BOTH years
# carry supplies.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_account_detail_opens_on_a_period_that_has_usage(seeded_site):
    """A conjunctive account opened with no period filter must land on a period
    with real usage — so usage reads non-zero and the story is visible."""
    # A conjunctive account (has groundwater extraction) — the curtailed Plainsburg
    # account qualifies (its conjunctive parcels substitute groundwater).
    account = _curtailed_account()
    resp = seeded_site.get(f"/accounting/accounts/{account.pk}/")
    assert resp.status_code == 200
    selected = resp.context["selected_period"]
    assert selected is not None, "account page should auto-select a period"
    assert selected.name in (PRIOR_WY, OPEN_WY)
    # 57-02: the page reads the consumptive lens, so "real activity" is proxied by
    # the supplies total. An empty period would land this on zero.
    assert resp.context["balance"]["supply_total"] > Decimal("0"), (
        "default account page should show non-zero supplies, not an empty period"
    )


@pytest.mark.django_db
def test_both_water_years_carry_account_usage(seeded_site):
    """Neither year is the empty one any more — which is why no name is pinned.

    This is the fact 133-02 delivered, asserted directly rather than left implicit
    in a period name: an operator switching the selector finds figures on both
    sides, and the auto-select cannot land on an empty year because there isn't
    one.
    """
    account = _curtailed_account()
    for name in (PRIOR_WY, OPEN_WY):
        supply = account_consumptive_balance(
            account, reporting_period=ReportingPeriod.objects.get(name=name)
        )["supply_total"]
        assert supply > Decimal("0"), f"{name} shows no supplies on this account"


@pytest.mark.django_db
def test_dashboard_opens_on_a_period_with_nonzero_usage(seeded_site):
    """The Budget Summary tiles must roll up a period that has real activity.

    57-02: under the consumptive lens the proxy is grand_supply_total (surface +
    groundwater supplies).
    """
    resp = seeded_site.get("/accounting/dashboard/")
    assert resp.status_code == 200
    selected = resp.context["selected_period"]
    assert selected is not None, "dashboard should auto-select a period"
    assert selected.name in (PRIOR_WY, OPEN_WY)
    assert resp.context["grand_supply_total"] > Decimal("0"), (
        "dashboard total supplies should be > 0, not an empty period"
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
# ISS-154 (Phase 137-02). The three literals below are hand-computed ONCE from
# this file's own fixture — `_build_physical_merced()` plus `seed_merced_ledgers`
# — by reading the raw ParcelLedger rows for the four parcels of the GSA the test
# selects (Halvern Valley GSA, basin 5-022.04) in WY 2024-2025 and partitioning
# them by `source_type` outside any application helper:
#
#     allocation          +672.0000   (4 rows)   -> a supply, not a use
#     meter_reading       -146.8800  (12 rows)   -> GROUNDWATER pumping
#     surface_diversion   -517.4400  (36 rows)   -> canal water DELIVERED
#
# and by reading the zone's own AllocationPlan (GW = 500.0000) and its
# AllocationCarryover rows for water year 2025 — of which this fixture has NONE,
# so the carry-over is a real, observed 0.0000 rather than an absent value.
# `seed_merced_ledgers` writes no `et_estimate` and no `calculated` rows here, so
# the billable subset is the raw subset and the groundwater magnitude is the
# meter total exactly.
#
# ⛔ The old assertions were `used > 0` and `remaining == budget - used`. Both are
# satisfied by the defect: they never look at WHICH rows landed in `used`, and the
# second re-derives the screen's own arithmetic instead of checking a value. That
# is how 1,170.93 AF of canal water sat inside a column headed *pumped* through a
# full ledger audit. Literals only from here.
GSA_PRIOR_ALLOCATION = Decimal("500.0000")
GSA_PRIOR_CARRYOVER = Decimal("0.0000")
GSA_PRIOR_GROUNDWATER_USE = Decimal("146.8800")
GSA_PRIOR_REMAINING = Decimal("353.1200")


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
    prior = [b for b in gw if b["period"].name == PRIOR_WY]
    assert prior, "GSA should carry a groundwater budget row for the prior year"
    row = prior[0]
    assert row["budget"] == GSA_PRIOR_ALLOCATION
    assert row["carryover"] == GSA_PRIOR_CARRYOVER
    assert row["used"] == GSA_PRIOR_GROUNDWATER_USE
    assert row["remaining"] == GSA_PRIOR_REMAINING


@pytest.mark.django_db
def test_gsa_zone_detail_renders_the_groundwater_figures_it_computed(seeded_site):
    """The same four numbers, in the HTML a district manager actually reads.

    Separate from the context test on purpose: a correct context dict that the
    template never prints, or prints from a different key, is the defect class
    ISS-155 names. Reading `resp.content` is the only check that cannot pass
    that way.
    """
    gsa = Zone.objects.filter(
        zone_type="management_area", basin_code="5-022.04"
    ).first()
    resp = seeded_site.get(f"/map/zones/{gsa.pk}/")
    body = resp.content.decode()
    for rendered in ("500.00", "146.88", "353.12"):
        assert rendered in body, (
            f"{rendered} is computed for the prior year's groundwater row but "
            "never reaches the rendered Allocation vs. use table"
        )
    # The canal magnitude must NOT appear as this row's use any more.
    assert "664.32" not in body, (
        "664.32 is groundwater pumping plus canal deliveries — the ISS-154 sum"
    )


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
