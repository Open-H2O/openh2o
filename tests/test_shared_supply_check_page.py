# SPDX-License-Identifier: AGPL-3.0-or-later
"""143-12, R-055 (shared-supply check) / R-089 / R-090 / R-091.

Before: the check's only control was the reporting period, its "8 hand-set
shared sources / 3 flagged / gap threshold 15 points" summary was 13px text
over the period selector, Gap printed a raw fraction (0.0804) against a rule
stated in points, and nothing marked Gap as the derived column. After: a
flagged-only filter sits beside the period selector, the flagged count is the
one large (32px) figure in a two-peer panel (the shape Brent accepted on the
lab-result page), and the table reads shares and Gap both in percent /
percentage points, Gap bracketed off as the derived column.

Fixture: `WellFactory`/`ParcelFactory` fixtures already used by
`tests/test_57_03_presentation.py::TestSharedSupplyComparison` (a hand-set
well, 0.6 / 0.4 stored, 5 / 20 demand). That test's own well and parcels are
constructed fresh per test (factory_boy sequences), so there is no collision
with the session-scoped Merced seed.

**Deviation from the plan's own guess, measured directly against the built
view rather than copied:** the plan's action text asserted the panel's two
peers would both read "1" for this fixture. Measured: both parcels in this
fixture diverge past the 0.15 threshold (|0.6-0.25| = 0.35 and |0.4-0.75| =
0.35), so BOTH rows flag, and "Fields to review" reads 2, not 1. The guard
below asserts the measured value.
"""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from core.models import User
from reporting.generators import SHARED_SUPPLY_DIVERGENCE_THRESHOLD, _compare_split
from tests.factories import ParcelFactory, ReportingPeriodFactory, WellFactory, WellIrrigatedParcelFactory

pytestmark = pytest.mark.django_db


def _run(parcel, period="2024-01", net=0):
    return CalculationRun.objects.create(
        parcel=parcel, period=period,
        gross_et_af=Decimal("0"), net_consumptive_use_af=Decimal(str(net)),
        effective_precip_af=Decimal("0"), surface_water_af=Decimal("0"),
        banked_af=Decimal("0"), drawn_af=Decimal("0"), final_af=Decimal("0"),
        breakdown=[{"step_type": "clamp_floor", "detail": {"incidental_recharge_af": "0"}}],
    )


@pytest.fixture
def auth_client():
    user = User.objects.create(
        username="r055-shared-reader", email="r055-shared-reader@example.com",
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


class TestCompareSplitPercentKeys:
    """The generator function, called directly, never through the template."""

    def test_your_pct_et_pct_gap_points_are_two_place_decimals(self):
        links = [(1, Decimal("0.6000")), (2, Decimal("0.4000"))]
        demand = {1: Decimal("5"), 2: Decimal("15")}
        names = {1: "P1", 2: "P2"}
        result = _compare_split(links, demand, names)
        rows = {r["parcel_id"]: r for r in result["rows"]}
        assert rows[1]["your_pct"] == Decimal("60.00")
        assert rows[1]["et_pct"] == Decimal("25.00")
        assert rows[1]["gap_points"] == Decimal("35.00")
        assert rows[2]["your_pct"] == Decimal("40.00")
        assert rows[2]["et_pct"] == Decimal("75.00")
        assert rows[2]["gap_points"] == Decimal("35.00")
        # existing keys are untouched, unrenamed
        assert rows[1]["your_weight"] == Decimal("0.6000")
        assert rows[1]["divergence"] == Decimal("0.3500")

    def test_zero_demand_leaves_the_new_keys_none(self):
        links = [(1, Decimal("0.6000")), (2, Decimal("0.4000"))]
        demand = {1: Decimal("0"), 2: Decimal("0")}
        names = {1: "P1", 2: "P2"}
        result = _compare_split(links, demand, names)
        rows = {r["parcel_id"]: r for r in result["rows"]}
        assert rows[1]["et_pct"] is None
        assert rows[1]["gap_points"] is None
        # the stored split still converts even with no ET signal.
        assert rows[1]["your_pct"] == Decimal("60.00")


class TestThePanelAndTable:
    def test_the_panel_reads_one_flagged_source_and_two_diverging_rows(
        self, auth_client
    ):
        rp = ReportingPeriodFactory()
        well = WellFactory(name="Probe Shared Well 143-12")
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
        _run(a, net=5)
        _run(b, net=15)

        resp = auth_client.get(
            reverse("reporting:shared_supply_check") + f"?period={rp.pk}"
        )
        assert resp.status_code == 200
        assert resp.context["flagged_count"] == 1
        assert resp.context["source_count"] == 1
        assert resp.context["flagged_rows"] == 2
        body = resp.content.decode()
        assert (
            '<div class="budget-seg-value text-deficit">1</div>' in body
        )
        assert body.count('<div class="budget-seg-value">1</div>') == 1  # Sources checked
        assert body.count('<div class="budget-seg-value">2</div>') == 1  # Fields to review

    def test_the_rows_print_percent_and_the_gap_as_points(self, auth_client):
        rp = ReportingPeriodFactory()
        well = WellFactory(name="Probe Shared Well Two 143-12")
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
        _run(a, net=5)
        _run(b, net=15)

        resp = auth_client.get(
            reverse("reporting:shared_supply_check") + f"?period={rp.pk}"
        )
        body = resp.content.decode()
        assert body.count("60.00%") == 1
        assert body.count("25.00%") == 1
        assert body.count("40.00%") == 1
        assert body.count("75.00%") == 1
        assert body.count("35.00") == 2  # both rows' Gap
        assert (
            '<th colspan="2" class="th-group-label">Share of the source\'s water</th>'
            in body
        )
        assert '<span class="th-stack">Gap points</span>' in body
        assert 'class="th-right col-sep"' in body
        assert "15" in body  # the divergence threshold, stated as prose

    def test_two_selects_control_the_page(self, auth_client):
        rp = ReportingPeriodFactory()
        resp = auth_client.get(
            reverse("reporting:shared_supply_check") + f"?period={rp.pk}"
        )
        body = resp.content.decode()
        assert 'id="period"' in body
        assert 'id="show"' in body
        assert body.count("<select") == 2

    def test_zero_demand_group_reads_no_et_estimate_and_no_et_signal_yet(
        self, auth_client
    ):
        rp = ReportingPeriodFactory()
        well = WellFactory(name="Probe Zero-Demand Well 143-12")
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
        # No CalculationRun rows for either parcel: zero measured demand.
        resp = auth_client.get(
            reverse("reporting:shared_supply_check") + f"?period={rp.pk}"
        )
        body = resp.content.decode()
        assert body.count("No ET estimate") == 4  # 2 rows x (ET-implied cell + Gap cell)
        assert "No ET signal yet" in body

    def test_show_flagged_narrows_the_table_but_not_the_panel(self, auth_client):
        rp = ReportingPeriodFactory()
        flagged_well = WellFactory(name="Probe Flagged Well 143-12")
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=flagged_well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=flagged_well, parcel=b, fraction=Decimal("0.4000"))
        _run(a, net=5)
        _run(b, net=15)

        reasonable_well = WellFactory(name="Probe Reasonable Well 143-12")
        c, d = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=reasonable_well, parcel=c, fraction=Decimal("0.5000"))
        WellIrrigatedParcelFactory(well=reasonable_well, parcel=d, fraction=Decimal("0.5000"))
        _run(c, net=10)
        _run(d, net=10)

        resp = auth_client.get(
            reverse("reporting:shared_supply_check")
            + f"?period={rp.pk}&show=flagged"
        )
        body = resp.content.decode()
        assert body.count('tr class="row-group"') == 1
        assert "1 of 2 sources, the flagged ones" in body
        # the panel is unaffected by the filter: it still counts both sources.
        assert resp.context["source_count"] == 2
        assert resp.context["flagged_count"] == 1

    def test_flag_rule_threshold_is_15(self):
        assert int(SHARED_SUPPLY_DIVERGENCE_THRESHOLD * 100) == 15
