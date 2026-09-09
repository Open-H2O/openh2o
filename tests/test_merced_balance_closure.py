# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermetic proof that the per-parcel books stay within a REALISTIC residual band.

This is the v1.10 capstone invariant (Phase 58-03, ISS-057 / ISS-054), rewritten
from 58-01's strict-closure form to the CORRECTED acceptance bar (58-02, Brent's
domain input): real water accounting never closes to zero — deficit irrigation,
salt-flush flooding, shallow-groundwater / stream-adjacent rootzone supplement, and
conveyance loss all leave a nonzero residual in BOTH directions. The bar a demo
must meet is therefore "residuals small, realistic, and never alarming," NOT
"residual == 0." A strict-closure test would now be a FALSE specification — it would
force the seed back to perfect-supply sizing that makes the demo look fake.

After the corrected refresh runs — ``run_calculations`` (populate net consumptive
use on EVERY parcel, incl. a metered reference run) -> ``allocate_district_delivery``
(demand-weighted surface) -> ``run_calculations`` (recompute residual + recharge) —
``abs(parcel_mass_balance(...).residual_af) <= BAND * gross_et`` for every archetype
the Merced demo exercises:

  * **Surface-only** (POD, no well, ample delivery) — the ISS-054 / MER-APN-031
    case. Supply over-delivers slightly; the surplus percolates as incidental
    recharge, so the residual is ~0 — ZERO pumped groundwater, NO phantom
    ``calculated`` row (54-01).
  * **Conjunctive** (well + POD, short delivery) — the MER-APN-016 case. The
    surface shortfall is met by engine-estimated pumped groundwater, so the residual
    is ~0 on the ``calculated`` groundwater term.
  * **Basin / flood-MAR** (no well, ample delivery, in a GSA management zone) —
    the over-delivery's incidental recharge routes to the GSA basin POOL with NO
    personal credit the parcel could never pump (ISS-053); residual ~0.
  * **Metered** (well + authoritative ``meter_reading``, 58-03) — the meter owns
    the groundwater (NO ``calculated`` row); the run is the ET reference value. The
    meter is sized to pump a little MORE than the crop consumed (the on-farm
    loss / return flow), so the parcel carries a small POSITIVE residual within the
    band — never a deficit, never alarming.

The closing identity (52.6-03) is
``surface + precip + gw_recovered = et + recharge + runoff + delta_storage``; the
residual is ``sum(inputs) - sum(outputs)``. It is exercised on the engine's OWN
output (not hand-seeded run rows), so the band proves the seed's measured-ET sizing
lands supply realistically against the SAME ET the balance checks.

Hermetic ORM fixtures (no network): OpenETCache rows mirror the live GEE shape —
ET rows ``variable="ET"/model="Ensemble"`` keyed ``"et"``, precip rows
``variable="precip"/model="GRIDMET"`` keyed ``"precip"``. The fixture keeps
gross ET well above effective precip per month, so net consumptive use stays
positive and ``clamp_floor`` parks the whole surface over-delivery in
``incidental_recharge_af`` (a no-well parcel banks nothing, so any bankable
precip-surplus would otherwise vanish).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command

from accounting.models import AllocationCarryover, CalculationRun
from accounting.services import consumptive_use_balance, parcel_mass_balance
from core.models import SiteConfig
from parcels.models import CropType, Parcel, ParcelLedger, UsageLocation
from surface.models import DiversionRecord
from surface.services import allocate_district_delivery
from tests.factories import (
    DiversionRecordFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
)
from wells.models import Well, WellIrrigatedParcel, WellType

pytestmark = pytest.mark.django_db

PERIOD = "2024-01"  # inside the default ReportingPeriodFactory span (WY 2023-2024)
EFF = Decimal("0.750")  # the demo's agency-wide irrigation efficiency (55-03)

# The realistic-residual ceiling (58-03). The seed sizes a meter reading to pump up
# to ~18% MORE than the crop consumed (METER_SUPPLY band [1.05, 1.18] in
# seed_merced_ledgers) — the on-farm loss / return flow, which has no recharge sink,
# so a metered parcel's residual is at most ~18% of its net demand (≤18% of gross
# ET). Surface / conjunctive / basin parcels close to ~0 (their over-delivery
# percolates to recharge / their shortfall is pumped). BAND gives that worst case
# headroom; a residual beyond it would mean supply genuinely diverged from measured
# ET, which is what this test guards against.
BAND = Decimal("0.22")

# Meter over-pump multiple used in the metered-archetype fixture: the meter reads a
# bit above measured consumption (inside the seed's METER_SUPPLY band), so the
# residual is small and POSITIVE. Held below BAND with headroom.
METER_OVER_PUMP = Decimal("1.12")


# --- hermetic builders (mirrors tests/test_consumptive_use_spine.py) --------

def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="40"):
    return Parcel.objects.create(
        parcel_number=number, area_acres=Decimal(acres), geometry=_square()
    )


def _et_cache(parcel, et_mm, period=PERIOD):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="ET", model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}])


def _precip_cache(parcel, precip_mm, period=PERIOD):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel, geometry=_square(),
        start_date=dt.date(year, month, 1), end_date=dt.date(year, month, 28),
        variable="precip", model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}])


def _irrigate(parcel):
    """Give the parcel a crop so facility_only_zero does not zero its ET."""
    crop = CropType.objects.create(name=f"Crop-{parcel.parcel_number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)


def _well(parcel, method="unmetered_estimate"):
    wt, _ = WellType.objects.get_or_create(name="Agricultural")
    well = Well.objects.create(
        well_registration_id=f"W-{parcel.parcel_number}",
        name=f"well {parcel.parcel_number}", well_type=wt,
        location=parcel.geometry.centroid, status="active",
        measurement_method=method)
    WellIrrigatedParcel.objects.create(
        well=well, parcel=parcel, fraction=Decimal("1.0000"))
    return well


def _meter_reading(parcel, af, rp, period=PERIOD):
    """An authoritative NEGATIVE meter_reading row (production sign convention).

    Stamped with the reporting period so the period-scoped mass balance counts it.
    """
    year, month = int(period[:4]), int(period[5:7])
    d = dt.date(year, month, 15)
    return ParcelLedger.objects.create(
        parcel=parcel, transaction_date=d, effective_date=d,
        amount_acre_feet=Decimal(str(af)), source_type="meter_reading",
        description="Monthly metered groundwater extraction",
        reporting_period=rp)


def _pool_zone(name):
    """A GSA management-area zone the parcel sits in — where its basin pool lives."""
    from geography.models import Boundary, ParcelZone, Zone

    boundary = Boundary.objects.create(name=f"B-{name}", geometry=_square())
    return Zone.objects.create(
        name=name, boundary=boundary, geometry=_square(),
        zone_type="management_area"), ParcelZone


def _pod_serving(parcel, *, volume_af, rp):
    """A single-parcel POD + one recorded DiversionRecord of ``volume_af``.

    A single-parcel POD makes allocation deterministic: AMPLE hands the parcel its
    demand/efficiency cap, SHORT hands it the whole recorded delivery.
    """
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp,
        month=dt.date(int(PERIOD[:4]), int(PERIOD[5:7]), 1),
        volume_acre_feet=Decimal(str(volume_af)))
    return pod


def _setup_period():
    """A non-finalized ReportingPeriod + active calc plan + SiteConfig efficiency.

    is_finalized=False so run_calculations does not refuse without --force; the
    SiteConfig singleton supplies the efficiency allocate_district_delivery reads.
    """
    rp = ReportingPeriodFactory(is_finalized=False)
    SiteConfig.objects.create(
        agency_name="Halvern Valley GSA", default_irrigation_efficiency=EFF)
    call_command("seed_calculation_plan")
    return rp


def _two_pass_refresh(pods, rp):
    """Run the same sequence refresh_merced_accounting runs, scoped to the test.

    run_calculations (net CU) -> allocate_district_delivery per POD (demand-weighted
    surface) -> run_calculations (recompute residual + recharge). Mirrors the
    Task-1 command's three steps without needing the full physical Merced demo.
    """
    call_command("run_calculations", "--period", PERIOD)
    for pod in pods:
        allocate_district_delivery(pod, rp)
    call_command("run_calculations", "--period", PERIOD)


# --- the three archetype closure proofs -------------------------------------

def test_surface_only_parcel_mass_balance_closes():
    """Surface-only (no well, ample delivery): closes via incidental recharge,
    with NO pumped groundwater and NO phantom `calculated` row (54-01 / ISS-054)."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-031")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    zone, ParcelZone = _pool_zone("surface-only-pool")
    ParcelZone.objects.create(parcel=parcel, zone=zone)
    pod = _pod_serving(parcel, volume_af=100, rp=rp)  # >> cap -> AMPLE

    _two_pass_refresh([pod], rp)

    balance = parcel_mass_balance(parcel, rp)
    assert abs(balance["residual_af"]) <= BAND * balance["outputs"]["et"], balance
    assert balance["inputs"]["gw_recovered"] == Decimal("0")
    assert balance["outputs"]["recharge"] > 0  # over-delivery percolated
    # 54-01 invariant: a no-well parcel writes NO phantom groundwater row.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated").exists()


def test_conjunctive_parcel_mass_balance_closes():
    """Conjunctive (well + POD, short delivery): closes on pumped groundwater."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-016")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    _well(parcel)
    pod = _pod_serving(parcel, volume_af=2, rp=rp)  # << net demand -> SHORT

    _two_pass_refresh([pod], rp)

    balance = parcel_mass_balance(parcel, rp)
    assert abs(balance["residual_af"]) <= BAND * balance["outputs"]["et"], balance
    assert balance["inputs"]["gw_recovered"] > 0  # shortfall pumped
    assert balance["outputs"]["recharge"] == Decimal("0")  # no over-delivery
    row = ParcelLedger.objects.get(parcel=parcel, source_type="calculated")
    assert row.amount_acre_feet < 0  # groundwater usage, stored negative
    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    assert run.residual_disposition == "groundwater"


def test_basin_parcel_mass_balance_closes_with_pooled_recharge():
    """Basin / flood-MAR (no well, ample delivery, in a GSA zone): closes, and the
    incidental recharge routes to the GSA basin POOL with NO personal credit
    (ISS-053)."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-BASIN")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    zone, ParcelZone = _pool_zone("basin-pool")
    ParcelZone.objects.create(parcel=parcel, zone=zone)
    pod = _pod_serving(parcel, volume_af=100, rp=rp)  # >> cap -> AMPLE

    _two_pass_refresh([pod], rp)

    balance = parcel_mass_balance(parcel, rp)
    assert abs(balance["residual_af"]) <= BAND * balance["outputs"]["et"], balance
    assert balance["inputs"]["gw_recovered"] == Decimal("0")
    assert balance["outputs"]["recharge"] > 0
    # ISS-053: the over-delivery recharge pooled to the GSA basin, NOT a personal
    # credit; the parcel keeps no positive recharge ledger row it could not pump.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="recharge", amount_acre_feet__gt=0).exists()
    pool = AllocationCarryover.objects.filter(
        zone=zone, origin="incidental_recharge_pool")
    assert pool.exists() and pool.first().amount_af > 0
    # And no phantom groundwater row (no well to pump it).
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated").exists()


def test_metered_parcel_mass_balance_within_band():
    """Metered (well + authoritative meter reading, 58-03): the engine writes an ET
    reference run with disposition "metered" and NO calculated GW row — the meter
    owns the groundwater. The meter is sized to pump a little MORE than the crop
    consumed (on-farm loss / return flow), so the parcel carries a small POSITIVE
    residual within the realistic band — never a deficit, never alarming. This locks
    the Task-1 engine path behaviorally, on the engine's OWN output."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-METER")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    # Starts unmetered so PASS 1 computes the net consumptive-use demand the meter
    # will be sized to (no meter row yet → treated as conjunctive this pass).
    well = _well(parcel)
    call_command("run_calculations", "--period", PERIOD)
    net_cu = CalculationRun.objects.get(
        parcel=parcel, period=PERIOD).net_consumptive_use_af
    assert net_cu > 0

    # Size the meter to that measured demand within the over-pump band, make it
    # authoritative, and re-run — now the parcel is metered (the seed's two passes
    # mirror this: run_calc -> size supply from the run -> run_calc).
    meter_af = (net_cu * METER_OVER_PUMP).quantize(Decimal("0.0001"))
    _meter_reading(parcel, af=-meter_af, rp=rp)
    Well.objects.filter(pk=well.pk).update(measurement_method="certified_meter")
    call_command("run_calculations", "--period", PERIOD)

    run = CalculationRun.objects.get(parcel=parcel, period=PERIOD)
    assert run.gross_et_af > 0  # the ET reference value is computed
    assert run.residual_disposition == "metered"
    # The meter is authoritative — NO calculated groundwater row.
    assert not ParcelLedger.objects.filter(
        parcel=parcel, source_type="calculated").exists()
    # The meter reading itself is untouched.
    assert ParcelLedger.objects.filter(
        parcel=parcel, source_type="meter_reading").count() == 1

    balance = parcel_mass_balance(parcel, rp)
    # Pumped a touch more than consumed → a small POSITIVE residual, within band.
    assert balance["inputs"]["gw_recovered"] > 0  # the meter reading is the GW input
    assert balance["residual_af"] > 0, balance
    assert abs(balance["residual_af"]) <= BAND * balance["outputs"]["et"], balance
    # 58-03 presentation: a small surplus reads as "realistic", NOT a warning.
    assert balance["band_status"] == "realistic", balance
    assert balance["is_surplus"] is True


def test_residual_band_status_classifies_three_tiers():
    """The presentation classifier: closes (≈0), realistic (small, within the band),
    and large (beyond it — a flagged shortfall)."""
    from accounting.services import residual_band_status

    et = Decimal("100")
    assert residual_band_status(Decimal("0.005"), et, closes=True) == "closes"
    # 10% of ET → realistic (meter pump loss / minor supplement, either sign).
    assert residual_band_status(Decimal("10"), et, closes=False) == "realistic"
    assert residual_band_status(Decimal("-10"), et, closes=False) == "realistic"
    # 40% of ET → large (e.g. a curtailment shortfall worth flagging).
    assert residual_band_status(Decimal("-40"), et, closes=False) == "large"


# --- Phase 67-03 diversion-reach spine-safety guards ------------------------
# The load-bearing acceptance gate: a fully-returned (hydropower) diversion writes
# a ZERO consumed magnitude, and the whole diversion-reach journey (a parcel-less
# passthrough + a downstream re-diversion) leaves the basin consumptive balance
# untouched. If either drifts, a write-site branched in 67-01 landed in the wrong
# place — STOP rather than paper over it in the seed.

def test_fully_returned_diversion_contributes_zero_surface_supply():
    """(a) A fully-returned hydro passthrough (returned_af == volume) writes a
    surface supply of ZERO, so it cannot move the consumptive spine — even though
    its gross diverted volume is large."""
    rp = _setup_period()
    parcel = _parcel("MER-APN-HYDRO")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    # returned == volume → consumed_acre_feet() == 0 (the non-consumptive endpoint).
    record = DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp,
        month=dt.date(int(PERIOD[:4]), int(PERIOD[5:7]), 1),
        volume_acre_feet=Decimal("500.0000"), returned_af=Decimal("500.0000"))

    call_command("run_calculations", "--period", PERIOD)
    allocate_district_delivery(pod, rp)

    # The recorded gross volume is 500 AF, but the consumed magnitude — the only
    # thing the ledger writers emit — is zero, so surface supply is zero.
    assert record.consumed_acre_feet() == Decimal("0")
    assert record.is_non_consumptive()
    balance = consumptive_use_balance([parcel.id], rp)
    assert balance["supplies"]["surface"] == Decimal("0"), balance


def test_diversion_reach_journey_does_not_move_basin_closure():
    """(b) Seeding the journey — a fully-returned upstream passthrough + a
    downstream re-diversion, BOTH serving no parcels — leaves the whole-basin
    consumptive balance byte-identical. The journey PODs write no surface_diversion
    rows, so supplies and the closure cannot move (the −0.18%/−0.12% baseline holds
    by construction; live drift would be the red flag the plan warns about)."""
    rp = _setup_period()
    # A normal surface parcel carrying real supply — the "basin" the journey must
    # not disturb.
    parcel = _parcel("MER-APN-NORMAL")
    _et_cache(parcel, et_mm=140.0)
    _precip_cache(parcel, precip_mm=40.0)
    _irrigate(parcel)
    pod = _pod_serving(parcel, volume_af=100, rp=rp)
    _two_pass_refresh([pod], rp)

    all_ids = list(Parcel.objects.values_list("id", flat=True))
    before = consumptive_use_balance(all_ids, rp)
    assert before["supplies"]["surface"] > 0  # the basin has real surface supply

    # Seed the journey: a parcel-less upstream POD (fully returned) and a
    # parcel-less downstream re-diversion (consumptive), linked one hop.
    upstream = PointOfDiversionFactory(name="MER-POD-010-DEMO Hydro")
    downstream = PointOfDiversionFactory(
        name="MER-POD-011-DEMO Re-Diversion", rediverted_from=upstream)
    month = dt.date(int(PERIOD[:4]), int(PERIOD[5:7]), 1)
    DiversionRecordFactory(
        point_of_diversion=upstream, reporting_period=rp, month=month,
        volume_acre_feet=Decimal("500.0000"), returned_af=Decimal("500.0000"))
    DiversionRecordFactory(
        point_of_diversion=downstream, reporting_period=rp, month=month,
        volume_acre_feet=Decimal("200.0000"), returned_af=Decimal("0"))

    # allocate_district_delivery is a guaranteed no-op for a parcel-less POD.
    assert allocate_district_delivery(upstream, rp) == []
    assert allocate_district_delivery(downstream, rp) == []

    after = consumptive_use_balance(all_ids, rp)
    assert after == before, (before, after)
    # The one-hop link resolves both directions.
    assert downstream.rediverted_from_id == upstream.id
    assert list(upstream.rediversions.all()) == [downstream]
    # No surface_diversion row was written for either journey POD.
    assert not ParcelLedger.objects.filter(
        source_type="surface_diversion",
        description__icontains="MER-POD-010-DEMO").exists()
    assert DiversionRecord.objects.filter(
        point_of_diversion__in=[upstream, downstream]).count() == 2


# ---------------------------------------------------------------------------
# The rendered badge word (136-01, ISS-143 / ISS-148 words)
# ---------------------------------------------------------------------------
#
# The parcel pane's badge trio is Balanced / Residual / Deficit (Brent,
# 2026-09-05; DESIGN.md rule 12). "Surplus" read as good news to the one
# audience the platform is for, and on this pane a positive residual is the
# opposite: water recorded arriving that the parcel's uses do not account for.
# The `is_surplus` KEY in `parcel_mass_balance` keeps its name (it is code, and
# `test_metered_parcel_mass_balance_within_band` above still reads it); only the
# word on screen changed. How the badge sits beside the figure is Phase 137's.


def _pane_user():
    """A logged-in user for a pane fetch, built without the fixtures app."""
    import factory
    from django.contrib.auth.hashers import make_password

    class _User(factory.django.DjangoModelFactory):
        class Meta:
            model = "core.User"

        username = factory.Sequence(lambda n: f"paneuser{n}")
        email = factory.Sequence(lambda n: f"paneuser{n}@example.com")
        password = factory.LazyFunction(lambda: make_password("testpass123"))
        is_active = True

    return _User()


def budget_segment(html, label):
    """The markup of the one ``.budget-seg`` carrying ``label``.

    Splitting on the segment's opening tag yields one chunk per segment, so
    something found in a chunk is INSIDE that segment rather than merely later
    on the page. That containment is the whole claim ISS-148 turns on: the
    badge has to be part of the residual statement, not a verdict sitting
    beside a different number.
    """
    chunks = html.split('<div class="budget-seg">')
    matching = [chunk for chunk in chunks[1:] if f">{label}</div>" in chunk]
    assert len(matching) == 1, (
        f"expected exactly one .budget-seg labelled {label!r} on the parcel "
        f"pane; found {len(matching)}"
    )
    return matching[0]


def test_parcel_pane_states_one_subtraction_with_the_badge_inside_it():
    """One meter reading of 110 AF against 100 AF of gross ET.

    Inputs 110 (pumped), outputs 100 (ET), so the residual is +10.00 AF: 10% of
    ET, inside REALISTIC_RESIDUAL_BAND (25%), so the badge is the green
    Residual. The pane must state that subtraction ONCE — Supplies 110.00 −
    Uses 100.00 = Residual 10.00 — with the badge inside the residual segment.
    The literals are hand-computed from the fixture above and pasted, never
    re-derived from the code under test (DESIGN.md rule 12, review question 2).
    """
    from django.test import Client
    from django.urls import reverse

    from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

    rp = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )
    parcel = ParcelFactory()
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=Decimal("-110.0000"),
        transaction_date=dt.date(2026, 1, 15), effective_date=dt.date(2026, 1, 15),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal("100.0000"),
        net_consumptive_use_af=Decimal("100.0000"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("100.0000"),
    )

    client = Client()
    client.force_login(_pane_user())
    response = client.get(reverse("parcels:detail", args=[parcel.pk]), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    html = response.content.decode()

    supplies = budget_segment(html, "Supplies")
    uses = budget_segment(html, "Uses")
    residual = budget_segment(html, "Residual")

    assert (
        '<div class="budget-seg-value text-supply">110.00'
        '<span class="budget-seg-unit">AF</span></div>'
    ) in supplies
    assert (
        '<div class="budget-seg-value text-usage">100.00'
        '<span class="budget-seg-unit">AF</span></div>'
    ) in uses
    assert (
        '<div class="budget-seg-value text-surplus">10.00'
        '<span class="budget-seg-unit">AF</span></div>'
    ) in residual

    assert '<span class="badge badge-green">Residual</span>' in residual, (
        "the badge is not inside the residual segment. ISS-148 is that the pane "
        "gave the answer twice in two identities and put the badge beside the "
        "one it does not judge; the badge belongs in the statement it judges."
    )

    assert "Supplies \u2212 consumptive use" not in html, (
        "card 3 (supplies minus gross ET) is still on the pane. The panel states "
        "the MASS BALANCE, which also carries recharge and storage change; two "
        "identities on one pane is ISS-148."
    )
    assert "Surplus" not in html, (
        "the parcel pane still says Surplus; the badge word is Residual "
        "(Brent, 2026-09-05; DESIGN.md rule 12)"
    )


def test_parcel_pane_panel_reads_a_flood_mar_field_as_a_deficit():
    """The same 110 AF in and 100 AF of ET, plus 20 AF spread to recharge.

    This is the shape ISS-148 was filed over. Card 3's identity (supplies minus
    gross ET) prints +10.00 and reads as spare supply; the mass balance, which
    also carries the water that left for the basin, is 110 − 120 = -10.00 and
    reads as a deficit. The panel states the mass balance, so the sign and the
    badge word agree, and the uses foot shows where the 20 AF went.

    Recharge is read off the engine's own breakdown (the ``clamp_floor`` step's
    ``incidental_recharge_af``), which is where ``parcel_mass_balance`` looks.
    """
    from django.test import Client
    from django.urls import reverse

    from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

    rp = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )
    parcel = ParcelFactory()
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=Decimal("-110.0000"),
        transaction_date=dt.date(2026, 1, 15), effective_date=dt.date(2026, 1, 15),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal("100.0000"),
        net_consumptive_use_af=Decimal("100.0000"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("100.0000"),
        breakdown=[
            {
                "step_type": "clamp_floor",
                "detail": {"incidental_recharge_af": "20.0000"},
            }
        ],
    )

    client = Client()
    client.force_login(_pane_user())
    response = client.get(reverse("parcels:detail", args=[parcel.pk]), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    html = response.content.decode()

    assert (
        '<div class="budget-seg-value text-supply">110.00'
        '<span class="budget-seg-unit">AF</span></div>'
    ) in budget_segment(html, "Supplies")
    assert (
        '<div class="budget-seg-value text-usage">120.00'
        '<span class="budget-seg-unit">AF</span></div>'
    ) in budget_segment(html, "Uses")

    residual = budget_segment(html, "Residual")
    assert (
        '<div class="budget-seg-value text-deficit">-10.00'
        '<span class="budget-seg-unit">AF</span></div>'
    ) in residual
    assert '<span class="badge badge-orange">Deficit</span>' in residual

    assert (
        '<span>Recharge <span class="text-tertiary">(estimated)</span></span><b>20.00</b>'
    ) in html, (
        "the uses breakdown does not show the 20.00 AF that left this field for the "
        "basin, so the residual is not legible from the panel. Incidental "
        "recharge is always engine-derived, so it carries the (estimated) label "
        "whenever it is non-zero (ISS-158)."
    )


def test_a_balanced_field_does_not_paint_its_residual_as_a_deficit():
    """A residual of -0.0020 AF: inside MASS_BALANCE_TOLERANCE, so it CLOSES.

    `is_surplus` is `residual >= 0`, which makes a hair-below-zero closing
    residual "not a surplus" and painted it deficit orange under a grey Balanced
    badge. Observed on the served page for MER-APN-032 (residual -0.0001 AF)
    while building the panel. The colour and the badge word describe the same
    number and may not disagree.
    """
    from django.test import Client
    from django.urls import reverse

    from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

    rp = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )
    parcel = ParcelFactory()
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=Decimal("-100.0000"),
        transaction_date=dt.date(2026, 1, 15), effective_date=dt.date(2026, 1, 15),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal("100.0020"),
        net_consumptive_use_af=Decimal("100.0020"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("100.0020"),
    )

    client = Client()
    client.force_login(_pane_user())
    response = client.get(reverse("parcels:detail", args=[parcel.pk]), HTTP_HX_REQUEST="true")
    assert response.status_code == 200

    residual = budget_segment(response.content.decode(), "Residual")
    assert '<span class="badge badge-grey">Balanced</span>' in residual
    assert "budget-seg-value text-deficit" not in residual, (
        "a field whose books CLOSE is painting its residual deficit orange under "
        "a grey Balanced badge"
    )
    assert "budget-seg-value text-neutral" in residual


def test_a_plugged_figure_says_it_is_an_estimate():
    """The engine's own output re-entering the balance is labelled as such.

    A field with a well and no meter has its groundwater written BY the engine
    as the leftover after crop use minus rainfall minus surface water, and that
    figure then re-enters this balance as a supply — so the residual closes by
    construction. Measured 2026-09-06: 113 of 152 field-years read 0.00, and
    every one had such a plug; not one field-year carrying a meter closes. A
    bare 0.00 with no label reads as a reconciliation that never happened
    (ISS-158).
    """
    from django.test import Client
    from django.urls import reverse

    from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

    rp = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )
    client = Client()
    client.force_login(_pane_user())

    def render(parcel):
        response = client.get(
            reverse("parcels:detail", args=[parcel.pk]), HTTP_HX_REQUEST="true"
        )
        assert response.status_code == 200
        return response.content.decode()

    def run_for(parcel):
        CalculationRun.objects.create(
            parcel=parcel, period="2026-01",
            gross_et_af=Decimal("100.0000"),
            net_consumptive_use_af=Decimal("100.0000"),
            effective_precip_af=Decimal("0.0000"),
            final_af=Decimal("100.0000"),
        )

    # The engine wrote this pumping figure: a `calculated` row.
    plugged = ParcelFactory()
    ParcelLedgerFactory(
        parcel=plugged, reporting_period=rp, source_type="calculated",
        amount_acre_feet=Decimal("-100.0000"),
        transaction_date=dt.date(2026, 1, 15), effective_date=dt.date(2026, 1, 15),
    )
    run_for(plugged)
    # 143-01: the figure sits in a titled breakdown row, marker beside the
    # name and the number in the row's own <b>.
    assert (
        '<span>Groundwater <span class="text-tertiary">(estimated)</span></span><b>100.00</b>'
    ) in render(plugged)

    # A meter owns this one: the engine had nothing to solve for.
    metered = ParcelFactory()
    ParcelLedgerFactory(
        parcel=metered, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=Decimal("-110.0000"),
        transaction_date=dt.date(2026, 1, 15), effective_date=dt.date(2026, 1, 15),
    )
    run_for(metered)
    metered_html = render(metered)
    assert "<span>Groundwater</span><b>110.00</b>" in metered_html, (
        "a metered groundwater figure is a recorded measurement and must not be "
        "labelled an estimate"
    )
    assert "(estimated)" not in metered_html
