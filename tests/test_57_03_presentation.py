# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 57-03 presentation guards.

Three surfaces and one confirmation:

  * The per-parcel water-balance card on the parcel detail page (Tasks 1-2):
    consumptive use vs supplies + the closing mass balance, an honest
    "ET not yet computed" state for not-yet-engine-billed parcels, and an audit
    drill-down to each engine-run month's waterfall.
  * The ISS-056 measured-vs-ET shared-supply comparison (Task 3): for each
    hand-set shared well / POD, the stored split beside the ET-implied split with
    a soft divergence flag, zero-demand safe.
  * Confirmation (Task 4) that the GEARS / CalWATRS generators still map to
    groundwater extraction / surface diversions and are INDEPENDENT of the
    consumptive-use reframe — the reframe must not move a single filed number.
"""
from datetime import date
from decimal import Decimal

import csv
import io

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from reporting.generators import (
    build_shared_supply_comparison,
    generate_calwatrs_csv,
    generate_gears_csv,
)
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db

JAN = date(2024, 1, 1)  # inside ReportingPeriodFactory's WY 2023-10 .. 2024-09.


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"guarduser{n}")
    email = factory.Sequence(lambda n: f"guarduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(UserFactory())
    return c


def _run(parcel, period="2024-01", *, gross_et=0, net=0, precip=0, surface=0,
         banked=0, drawn=0, final=0, incidental=0):
    """A CalculationRun with known terms. ``net`` drives the ISS-056 demand."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal(str(gross_et)),
        net_consumptive_use_af=Decimal(str(net)),
        effective_precip_af=Decimal(str(precip)),
        surface_water_af=Decimal(str(surface)),
        banked_af=Decimal(str(banked)),
        drawn_af=Decimal(str(drawn)),
        final_af=Decimal(str(final)),
        breakdown=[
            {"step_type": "clamp_floor",
             "detail": {"incidental_recharge_af": str(incidental)}}
        ],
    )


def _surface_row(parcel, rp, magnitude, eff_date=JAN):
    """A surface_diversion ledger row, stored NEGATIVE (production convention)."""
    return ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, effective_date=eff_date,
        transaction_date=eff_date,
        amount_acre_feet=Decimal(str(-abs(magnitude))),
        source_type="surface_diversion",
    )


def _calculated_row(parcel, rp, magnitude, eff_date=JAN):
    """A netted `calculated` groundwater row, stored NEGATIVE (usage)."""
    return ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, effective_date=eff_date,
        transaction_date=eff_date,
        amount_acre_feet=Decimal(str(-abs(magnitude))),
        source_type="calculated",
    )


def _meter_row(parcel, magnitude, eff_date=JAN):
    return ParcelLedgerFactory(
        parcel=parcel, effective_date=eff_date, transaction_date=eff_date,
        amount_acre_feet=Decimal(str(magnitude)), source_type="meter_reading",
    )


# ---------------------------------------------------------------------------
# Tasks 1-2: the per-parcel water-balance card + audit drill-down.
# ---------------------------------------------------------------------------

class TestParcelBalanceCard:
    def test_conjunctive_parcel_card_closes_and_drills_down(self, auth_client):
        """A conjunctive closing month: card context closes, drill-down resolves."""
        rp = ReportingPeriodFactory()
        parcel = ParcelFactory(parcel_number="MER-APN-016")
        WellIrrigatedParcelFactory(parcel=parcel)  # CONJUNCTIVE

        # gross ET 20 met by 10 surface + 3 precip + 7 pumped groundwater.
        _run(parcel, "2024-01", gross_et=20, net=17, precip=3, surface=10, final=7)
        _surface_row(parcel, rp, 10)
        _calculated_row(parcel, rp, 7)

        resp = auth_client.get(reverse("parcels:detail", args=[parcel.pk]))
        assert resp.status_code == 200

        mb = resp.context["mass_balance"]
        assert mb["closes"] is True
        assert resp.context["balance_period"].pk == rp.pk
        assert resp.context["run_periods"] == ["2024-01"]
        # consumptive lens present and consistent (surface from the ledger).
        assert resp.context["consumptive_balance"]["supplies"]["surface"] == Decimal("10")

        # The drill-down link is rendered AND resolves to a 200 audit page.
        audit_url = reverse("accounting:calculation_run_detail",
                            args=[parcel.pk, "2024-01"])
        assert audit_url in resp.content.decode()
        assert auth_client.get(audit_url).status_code == 200

    def test_surface_only_parcel_shows_honest_open_state(self, auth_client):
        """A surface-only parcel with no CalculationRun: no runs, honest message."""
        rp = ReportingPeriodFactory()
        parcel = ParcelFactory(parcel_number="MER-APN-031")
        # Real surface activity (so a period resolves) but ET never computed.
        _surface_row(parcel, rp, 9)

        resp = auth_client.get(reverse("parcels:detail", args=[parcel.pk]))
        assert resp.status_code == 200
        assert resp.context["run_periods"] == []          # nothing to audit yet
        body = resp.content.decode()
        assert "ET has not been computed" in body          # honest open state
        # surface supply still shown honestly, no fabricated closing term.
        assert resp.context["consumptive_balance"]["supplies"]["surface"] == Decimal("9")
        # no dangling drill-down link when there are no runs.
        assert reverse("accounting:calculation_run_detail",
                       args=[parcel.pk, "2024-01"]) not in body


# ---------------------------------------------------------------------------
# Task 3: ISS-056 measured-vs-ET shared-supply comparison.
# ---------------------------------------------------------------------------

def _rows_by_parcel(group):
    return {r["parcel_id"]: r for r in group["rows"]}


class TestSharedSupplyComparison:
    def test_handset_well_renders_both_splits(self):
        """A hand-set shared well shows stored split beside the ET-implied split."""
        rp = ReportingPeriodFactory()
        well = WellFactory(name="Shared Well A")
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
        _run(a, net=5)   # ET says b is thirstier than the hand-set 0.6/0.4
        _run(b, net=15)

        groups = build_shared_supply_comparison(rp)
        assert len(groups) == 1
        g = groups[0]
        assert g["kind"] == "Well"
        assert g["has_et_signal"] is True
        rows = _rows_by_parcel(g)
        assert rows[a.pk]["your_weight"] == Decimal("0.6000")   # stored split
        assert rows[b.pk]["your_weight"] == Decimal("0.4000")
        assert rows[a.pk]["et_weight"] == Decimal("0.2500")     # 5 / 20 demand
        assert rows[b.pk]["et_weight"] == Decimal("0.7500")

    def test_divergent_demand_raises_soft_flag(self):
        """Stored 0.5/0.5 vs ET-implied 0.05/0.95 → divergence past threshold flags."""
        rp = ReportingPeriodFactory()
        well = WellFactory()
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.5000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.5000"))
        _run(a, net=5)
        _run(b, net=95)

        g = build_shared_supply_comparison(rp)[0]
        rows = _rows_by_parcel(g)
        assert rows[a.pk]["divergence"] == Decimal("0.4500")    # |0.5 - 0.05|
        assert rows[a.pk]["flag"] is True
        assert g["any_flag"] is True

    def test_zero_demand_group_no_et_signal_no_flag(self):
        """Hand-set group with zero measured demand: 'no ET signal', no flag, no crash."""
        rp = ReportingPeriodFactory()
        well = WellFactory()
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
        # No CalculationRuns → zero demand (the live-demo state until Phase 58).

        g = build_shared_supply_comparison(rp)[0]
        assert g["has_et_signal"] is False
        assert g["any_flag"] is False
        rows = _rows_by_parcel(g)
        assert rows[a.pk]["et_weight"] is None
        assert rows[a.pk]["divergence"] is None
        assert rows[a.pk]["flag"] is False
        # the stored split is still shown for reference.
        assert rows[a.pk]["your_weight"] == Decimal("0.6000")

    def test_untouched_fractions_excluded(self):
        """A shared source with untouched 1.0 fractions is NOT hand-set → excluded."""
        rp = ReportingPeriodFactory()
        well = WellFactory()
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("1.0000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("1.0000"))
        _run(a, net=5)
        _run(b, net=15)

        assert build_shared_supply_comparison(rp) == []

    def test_single_parcel_source_excluded(self):
        """A source serving one parcel has no split to compare → excluded."""
        rp = ReportingPeriodFactory()
        well = WellFactory()
        p = ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=p, fraction=Decimal("0.5000"))

        assert build_shared_supply_comparison(rp) == []

    def test_handset_pod_group_included(self):
        """A hand-set shared POD also appears, labeled as a point of diversion."""
        rp = ReportingPeriodFactory()
        pod = PointOfDiversionFactory(name="Shared POD X")
        a, b = ParcelFactory(), ParcelFactory()
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=a, fraction=Decimal("0.7000"))
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=b, fraction=Decimal("0.3000"))
        _run(a, net=10)
        _run(b, net=10)

        g = build_shared_supply_comparison(rp)[0]
        assert g["kind"] == "Point of diversion"
        assert g["source_name"] == "Shared POD X"
        rows = _rows_by_parcel(g)
        assert rows[a.pk]["et_weight"] == Decimal("0.5000")    # equal demand

    def test_groups_carry_source_id_and_kind_for_edit_links(self):
        """Each group exposes the source pk + kind so the template can link to the
        well / POD detail page where the split is actually edited."""
        rp = ReportingPeriodFactory()
        well = WellFactory(name="Edit-link Well")
        wa, wb = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=wa, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=wb, fraction=Decimal("0.4000"))
        pod = PointOfDiversionFactory(name="Edit-link POD")
        pa, pb = ParcelFactory(), ParcelFactory()
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=pa, fraction=Decimal("0.7000"))
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=pb, fraction=Decimal("0.3000"))

        by_kind = {g["kind"]: g for g in build_shared_supply_comparison(rp)}
        assert by_kind["Well"]["source_kind"] == "well"
        assert by_kind["Well"]["source_id"] == well.pk
        assert by_kind["Point of diversion"]["source_kind"] == "pod"
        assert by_kind["Point of diversion"]["source_id"] == pod.pk

    def test_view_renders(self, auth_client):
        """The shared-supply check page returns 200 and lists a hand-set group."""
        rp = ReportingPeriodFactory()
        well = WellFactory(name="Visible Shared Well")
        a, b = ParcelFactory(), ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=a, fraction=Decimal("0.6000"))
        WellIrrigatedParcelFactory(well=well, parcel=b, fraction=Decimal("0.4000"))
        _run(a, net=5)
        _run(b, net=15)
        _surface_row(a, rp, 1)  # give the period real activity so it defaults here

        resp = auth_client.get(reverse("reporting:shared_supply_check") + f"?period={rp.pk}")
        assert resp.status_code == 200
        assert "Visible Shared Well" in resp.content.decode()


# ---------------------------------------------------------------------------
# Task 4: GEARS / CalWATRS unchanged by the consumptive-use reframe.
# ---------------------------------------------------------------------------

class TestReportsIndependentOfReframe:
    def test_gears_maps_groundwater_extraction_not_surface(self):
        """A GEARS by-well row reports metered GROUNDWATER; a surface row is ignored."""
        rp = ReportingPeriodFactory()
        well = WellFactory(well_registration_id="REG-GW-1")
        p = ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=p, fraction=Decimal("1.0000"))
        _meter_row(p, "10.0000")            # groundwater extraction
        _surface_row(p, rp, 99)             # surface delivery must NOT leak in

        rows = list(csv.reader(io.StringIO(
            generate_gears_csv(rp, "by_well").getvalue())))[1:]
        assert len(rows) == 1
        assert Decimal(rows[0][5]) == Decimal("10")   # extraction, not 99 or 109

    def test_calwatrs_maps_surface_diversions_not_groundwater(self):
        """A CalWATRS row reports the diverted SURFACE volume; groundwater ignored."""
        rp = ReportingPeriodFactory()
        wr = WaterRightFactory()
        pod = PointOfDiversionFactory(water_right=wr)
        p = ParcelFactory()
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=p, fraction=Decimal("1.0000"))
        _meter_row(p, "77.0000")            # groundwater must NOT leak in
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=rp, month=JAN,
            volume_acre_feet=Decimal("100.0000"), diversion_type="direct_use",
        )

        rows = list(csv.reader(io.StringIO(
            generate_calwatrs_csv(rp, "a1").getvalue())))[1:]
        assert sum(Decimal(r[7]) for r in rows) == Decimal("100")  # surface only

    def test_filings_invariant_to_precip_a_reframe_only_term(self):
        """effective_precip_af feeds ONLY the consumptive lens, never the filings.

        Generate both CSVs, then add a large precip term to every run (which moves
        the consumptive-use card's precip supply but nothing the kernel or the
        generators read) and regenerate. Byte-identical output proves the reframe
        cannot move a filed number.
        """
        rp = ReportingPeriodFactory()
        wr = WaterRightFactory()
        pod = PointOfDiversionFactory(water_right=wr)
        well = WellFactory(well_registration_id="REG-INV-1")
        a, b = ParcelFactory(), ParcelFactory()
        for p in (a, b):
            PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=p, fraction=Decimal("1.0000"))
            WellIrrigatedParcelFactory(well=well, parcel=p, fraction=Decimal("1.0000"))
            _meter_row(p, "10.0000")
        _run(a, net=5, precip=0)
        _run(b, net=15, precip=0)
        DiversionRecordFactory(
            point_of_diversion=pod, reporting_period=rp, month=JAN,
            volume_acre_feet=Decimal("100.0000"), diversion_type="direct_use",
        )

        gears_before = generate_gears_csv(rp, "by_well").getvalue()
        calwatrs_before = generate_calwatrs_csv(rp, "a1").getvalue()

        # Mutate ONLY the reframe-surfaced precip term.
        CalculationRun.objects.filter(parcel=a).update(effective_precip_af=Decimal("500"))
        CalculationRun.objects.filter(parcel=b).update(effective_precip_af=Decimal("900"))

        assert generate_gears_csv(rp, "by_well").getvalue() == gears_before
        assert generate_calwatrs_csv(rp, "a1").getvalue() == calwatrs_before
