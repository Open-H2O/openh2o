# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounting-layer invariant guard for the Merced synthetic ledgers (Phase 52-01).

These tests are the SPEC for ``seed_merced_ledgers``. They build a compact but
structurally faithful slice of the Phase 51-03 physical demo directly via the ORM
(no network, no large fixtures), run the ledger seed on top of it, and assert the
accounting invariants the seed MUST satisfy. They are written RED-first: until the
command exists, ``call_command("seed_merced_ledgers")`` raises and every test fails.

The five invariant groups (the headline cases of the whole Merced rebuild):

1. water_source keying / two-authority separation — a groundwater-only parcel never
   gets a surface delivery; a surface-only parcel never gets a groundwater extraction;
   conjunctive parcels get both.
2. Budgets for BOTH authorities — a groundwater Water Budget per GSA zone and a
   surface Water Budget per surface-district zone, in both reporting periods.
3. Curtailment — parcels served by the curtailed El Nido right lose surface deliveries
   after the curtailment month; the conjunctive ones among them substitute groundwater.
4. Shared-well apportionment — a shared well's monthly extraction splits across its
   parcels by the stored fraction and sums back to the well total (no double-count).
5. Idempotency — running the seed twice leaves ledger/account/budget counts unchanged.

The fixture mirrors the real selection's shape (surface-only / groundwater-only /
conjunctive; a curtailed district reaching surface + conjunctive parcels; two shared
well groups) at a fraction of the size so the suite stays fast and hermetic.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import call_command

from accounting.models import (
    AllocationPlan,
    ReportingPeriod,
    WaterAccount,
    WaterType,
)
from geography.models import Boundary, ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger
from surface.models import (
    PointOfDiversion,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightParcel,
    WaterRightType,
)
from wells.models import Well, WellIrrigatedParcel, WellType

# --- The accounting contract the seed must meet (independent of its internals) ---
GW_EXTRACTION_SOURCES = {"meter_reading", "et_estimate"}
# The full transactional ledger lives in the finalized prior water year, mirroring
# the proven Kaweah engine path (Oct 2024 – Sep 2025).
PRIOR_WY = "WY 2024-2025"
OPEN_WY = "WY 2025-2026"
# The junior El Nido right is curtailed going into the peak irrigation season: the
# last month with a surface delivery is June 2025, so July–September are dry.
FIRST_CURTAILED_MONTH = date(2025, 7, 1)
POST_CURTAILMENT_MONTHS = {7, 8, 9}
QUANT = Decimal("0.0001")

# Surface districts modeled in the fixture (a right whose POD(s) serve real parcels).
NORMAL_RIGHT = "MER-WR-004"
CURTAILED_RIGHT = "MER-WR-009"


def _box(cx, cy, size=0.01):
    half = size / 2
    ring = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
        (cx - half, cy - half),
    ]
    return MultiPolygon(Polygon(ring))


def _source_of(parcel):
    """The QGIS-tagged water source, read back from the parcel note (the oracle)."""
    for chunk in parcel.notes.split("|"):
        chunk = chunk.strip()
        if chunk.startswith("source="):
            return chunk.split("=", 1)[1].strip().lower()
    return ""


def _build_physical_merced():
    """Create a compact, structurally faithful Phase 51-03 physical slice.

    Returns nothing — the seed and the tests both read it back from the DB, exactly
    as they would on the real Butler demo.
    """
    boundary = Boundary.objects.create(name="Merced Subbasin", geometry=_box(-120.5, 37.2, 1.0))

    # Three GSA management-area zones (the groundwater authority), keyed like the
    # real seed_merced_gsas output (zone_type management_area, basin 5-022.04).
    gsas = {}
    for i, gname in enumerate([
        "Merced Subbasin GSA", "Merced Irrigation-Urban GSA", "Turner Island Water District GSA",
    ]):
        gsas[gname] = Zone.objects.create(
            name=gname, boundary=boundary, geometry=_box(-120.6 + i * 0.1, 37.2, 0.3),
            zone_type="management_area", basin_code="5-022.04",
        )
    gsa_list = list(gsas.values())

    post14, _ = WaterRightType.objects.get_or_create(
        code="POST14", defaults={"name": "Post-1914 Appropriative"})

    # Two surface districts: a normal one and the curtailed El Nido junior right.
    normal = WaterRight.objects.create(
        right_id=NORMAL_RIGHT, right_type=post14, holder_name="Merced Irrigation District",
        priority_date=date(1930, 4, 10), face_value_acre_feet=Decimal("120000"),
        status="active", source_name="Merced River",
    )
    curtailed = WaterRight.objects.create(
        right_id=CURTAILED_RIGHT, right_type=post14, holder_name="Plainsburg Irrigation District",
        priority_date=date(1962, 5, 5), face_value_acre_feet=Decimal("9000"),
        status="curtailed", source_name="El Nido Canal",
    )
    pod_normal = PointOfDiversion.objects.create(
        water_right=normal, name="MER-POD-004 MID Atwater Canal Headgate",
        location=Point(-120.66, 37.34), status="active")
    pod_curtailed = PointOfDiversion.objects.create(
        water_right=curtailed, name="MER-POD-007 Plainsburg El Nido Canal Headgate",
        location=Point(-120.47, 37.20), status="active")

    ag_well, _ = WellType.objects.get_or_create(name="Agricultural")

    seq = {"p": 0, "w": 0, "x": 0.0}

    def make_parcel(source, gsa, owner):
        seq["p"] += 1
        seq["x"] += 0.02
        geom = _box(-120.7 + seq["x"], 37.1, 0.01)
        p = Parcel.objects.create(
            parcel_number=f"MER-APN-{seq['p']:03d}", owner_name=owner, geometry=geom,
            area_acres=Decimal("80.00"), status="active",
            notes=f"DWR field {seq['p']} | source={source}",
        )
        ParcelZone.objects.create(parcel=p, zone=gsa)
        return p

    def serve(pod, parcel):
        PointOfDiversionParcel.objects.create(
            point_of_diversion=pod, parcel=parcel, fraction=Decimal("1.0000"))
        WaterRightParcel.objects.create(water_right=pod.water_right, parcel=parcel)

    def solo_well(parcel):
        seq["w"] += 1
        w = Well.objects.create(
            well_registration_id=f"MER-W-{seq['w']:03d}",
            name=f"Ag well on {parcel.parcel_number}", well_type=ag_well,
            location=parcel.geometry.centroid, status="active")
        WellIrrigatedParcel.objects.create(well=w, parcel=parcel, fraction=Decimal("1.0000"))
        return w

    def shared_well(parcels):
        seq["w"] += 1
        frac = Decimal(str(round(1.0 / len(parcels), 4)))
        w = Well.objects.create(
            well_registration_id=f"MER-W-{seq['w']:03d}",
            name=f"Shared ag well — {len(parcels)} parcels", well_type=ag_well,
            location=parcels[0].geometry.centroid, status="active")
        for p in parcels:
            WellIrrigatedParcel.objects.create(well=w, parcel=p, fraction=frac)
        return w

    # Normal district: 3 surface-only + 2 conjunctive.
    for _ in range(3):
        serve(pod_normal, make_parcel("surface", gsa_list[0], "Atwater Ranch Partners"))
    for _ in range(2):
        p = make_parcel("conjunctive", gsa_list[1], "Le Grand Orchards Inc.")
        serve(pod_normal, p)
        solo_well(p)

    # Curtailed district: 2 surface-only + 2 conjunctive (the substitution growers).
    for _ in range(2):
        serve(pod_curtailed, make_parcel("surface", gsa_list[2], "Plainsburg Ag Holdings"))
    for _ in range(2):
        p = make_parcel("conjunctive", gsa_list[2], "Plainsburg Ag Holdings")
        serve(pod_curtailed, p)
        solo_well(p)

    # Groundwater-only: 1 solo + two shared groups (N=2 and N=3).
    solo_well(make_parcel("groundwater", gsa_list[0], "Merced Valley Farms LLC"))
    shared_well([
        make_parcel("groundwater", gsa_list[1], "Sandy Mush Growers") for _ in range(2)
    ])
    shared_well([
        make_parcel("groundwater", gsa_list[2], "Turner Island Farms LLC") for _ in range(3)
    ])


@pytest.fixture
def seeded():
    """Build the physical slice and run the ledger seed once."""
    _build_physical_merced()
    call_command("seed_merced_ledgers")


def _curtailed_parcels():
    pods = PointOfDiversion.objects.filter(water_right__right_id=CURTAILED_RIGHT)
    ids = PointOfDiversionParcel.objects.filter(
        point_of_diversion__in=pods).values_list("parcel_id", flat=True)
    return list(Parcel.objects.filter(id__in=ids))


def _parcel_has_metered_well(parcel):
    """Whether a parcel is served by at least one CERTIFIED-METER well (after the
    seed has set each well's measurement_method).

    Since 52.5-01, only metered wells carry synthetic seed groundwater rows —
    unmetered wells are engine-owned (their `calculated` rows land in Plan 02), so
    they write none. This oracle tells the keying tests which parcels to expect a
    seed extraction row for.
    """
    return WellIrrigatedParcel.objects.filter(
        parcel=parcel, well__measurement_method="certified_meter"
    ).exists()


# --------------------------------------------------------------------------
# Group 1 — water_source keying / two-authority separation
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_groundwater_parcel_has_no_surface_delivery(seeded):
    for p in Parcel.objects.filter(parcel_number__startswith="MER-APN-"):
        if _source_of(p) != "groundwater":
            continue
        assert not ParcelLedger.objects.filter(
            parcel=p, source_type="surface_diversion").exists(), (
            f"{p.parcel_number} is groundwater-only but has a surface delivery")
        # Seed extraction now exists ONLY for metered-well parcels (52.5-01); an
        # unmetered-well parcel is engine-owned and carries no seed extraction.
        has_extraction = ParcelLedger.objects.filter(
            parcel=p, source_type__in=GW_EXTRACTION_SOURCES).exists()
        if _parcel_has_metered_well(p):
            assert has_extraction, (
                f"{p.parcel_number} is on a metered well but has no extraction row")
        else:
            assert not has_extraction, (
                f"{p.parcel_number} is on an unmetered well but has a seed "
                "extraction row (its groundwater is engine-owned)")


@pytest.mark.django_db
def test_surface_deliveries_stored_negative(seeded):
    """Surface deliveries follow the production convention: stored NEGATIVE, so
    they round-trip through the CSV importer and read correctly in the calc
    engine (which expects negative surface_diversion). The dashboard still counts
    them as supply — see test_accounting_services.TestSurfaceWaterCountsAsSupply."""
    rows = ParcelLedger.objects.filter(source_type="surface_diversion")
    assert rows.exists(), "fixture should produce surface deliveries"
    assert all(r.amount_acre_feet < 0 for r in rows), (
        "surface_diversion rows must be stored negative (production convention)")


@pytest.mark.django_db
def test_surface_parcel_has_no_groundwater_extraction(seeded):
    for p in Parcel.objects.filter(parcel_number__startswith="MER-APN-"):
        if _source_of(p) != "surface":
            continue
        assert ParcelLedger.objects.filter(
            parcel=p, source_type="surface_diversion").exists(), (
            f"{p.parcel_number} is surface-only but has no surface delivery")
        assert not ParcelLedger.objects.filter(
            parcel=p, source_type__in=GW_EXTRACTION_SOURCES).exists(), (
            f"{p.parcel_number} is surface-only but has a groundwater extraction")


@pytest.mark.django_db
def test_conjunctive_parcel_has_both_surface_and_groundwater(seeded):
    """A conjunctive parcel always has a surface delivery; its groundwater
    extraction is seeded only when its well is metered (an unmetered conjunctive
    parcel's groundwater is engine-owned — Plan 02)."""
    seen_metered = 0
    for p in Parcel.objects.filter(parcel_number__startswith="MER-APN-"):
        if _source_of(p) != "conjunctive":
            continue
        assert ParcelLedger.objects.filter(
            parcel=p, source_type="surface_diversion").exists(), (
            f"{p.parcel_number} is conjunctive but has no surface delivery")
        has_extraction = ParcelLedger.objects.filter(
            parcel=p, source_type__in=GW_EXTRACTION_SOURCES).exists()
        if _parcel_has_metered_well(p):
            seen_metered += 1
            assert has_extraction, (
                f"{p.parcel_number} is conjunctive on a metered well but has no "
                "groundwater extraction")
        else:
            assert not has_extraction, (
                f"{p.parcel_number} is conjunctive on an unmetered well but has a "
                "seed groundwater extraction (engine-owned)")
    assert seen_metered >= 1, "fixture should contain a metered conjunctive parcel"


@pytest.mark.django_db
def test_unmetered_wells_write_no_seed_groundwater_rows(seeded):
    """52.5-01 reconciliation: an UNMETERED well's groundwater is engine-owned
    (Plan 02 `calculated` rows), so the synthetic seed writes NONE of its
    extraction — otherwise the engine would double-count. Metered wells keep
    their authoritative `meter_reading` rows; the old `et_estimate` synthetic
    source is gone entirely.
    """
    wells = list(Well.objects.filter(well_registration_id__startswith="MER-W-"))
    unmetered = [w for w in wells if w.measurement_method == "unmetered_estimate"]
    metered = [w for w in wells if w.measurement_method == "certified_meter"]
    assert unmetered and metered, "fixture should exercise both metering methods"

    # The unmetered synthetic source (et_estimate) is gone for the whole demo.
    assert not ParcelLedger.objects.filter(
        parcel__parcel_number__startswith="MER-APN-", source_type="et_estimate"
    ).exists(), "unmetered seed groundwater rows (et_estimate) must be gone"

    # Each unmetered well's parcels carry NO seed extraction row.
    for w in unmetered:
        for ln in WellIrrigatedParcel.objects.filter(well=w):
            assert not ParcelLedger.objects.filter(
                parcel_id=ln.parcel_id, source_type__in=GW_EXTRACTION_SOURCES
            ).exists(), (
                f"{w.well_registration_id} is unmetered but its parcel "
                f"{ln.parcel_id} has a seed extraction row")

    # Each metered well's parcels carry meter_reading rows (authoritative, kept).
    for w in metered:
        for ln in WellIrrigatedParcel.objects.filter(well=w):
            assert ParcelLedger.objects.filter(
                parcel_id=ln.parcel_id, source_type="meter_reading"
            ).exists(), (
                f"{w.well_registration_id} is metered but its parcel "
                f"{ln.parcel_id} has no meter_reading row")


# --------------------------------------------------------------------------
# Group 2 — budgets exist for BOTH authorities, both periods
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_both_reporting_periods_exist(seeded):
    assert ReportingPeriod.objects.filter(name=PRIOR_WY, is_finalized=True).exists()
    assert ReportingPeriod.objects.filter(name=OPEN_WY).exists()


@pytest.mark.django_db
def test_each_gsa_zone_has_a_groundwater_budget_in_both_periods(seeded):
    gw = WaterType.objects.get(code="GW")
    periods = list(ReportingPeriod.objects.filter(name__in=[PRIOR_WY, OPEN_WY]))
    gsa_zones = Zone.objects.filter(zone_type="management_area", basin_code="5-022.04")
    assert gsa_zones.count() == 3
    for zone in gsa_zones:
        for rp in periods:
            assert AllocationPlan.objects.filter(
                zone=zone, water_type=gw, reporting_period=rp).exists(), (
                f"GSA {zone.name} missing groundwater budget for {rp.name}")


@pytest.mark.django_db
def test_each_surface_district_zone_has_a_surface_budget_in_both_periods(seeded):
    sw = WaterType.objects.get(code="SW")
    periods = list(ReportingPeriod.objects.filter(name__in=[PRIOR_WY, OPEN_WY]))
    district_zones = Zone.objects.filter(
        zone_type="custom", name__startswith="MER Surface Service Area")
    # One district zone per surface right whose PODs serve parcels (here 2).
    assert district_zones.count() == 2, (
        "expected a surface-district zone per served surface right")
    for zone in district_zones:
        for rp in periods:
            assert AllocationPlan.objects.filter(
                zone=zone, water_type=sw, reporting_period=rp).exists(), (
                f"district {zone.name} missing surface budget for {rp.name}")


@pytest.mark.django_db
def test_curtailed_district_open_year_surface_budget_is_reduced(seeded):
    """The curtailed district's CURRENT-year surface budget reflects the curtailment."""
    sw = WaterType.objects.get(code="SW")
    prior = ReportingPeriod.objects.get(name=PRIOR_WY)
    open_wy = ReportingPeriod.objects.get(name=OPEN_WY)
    # The curtailed district's zone carries its right_id in the name.
    zone = Zone.objects.get(
        zone_type="custom", name__startswith="MER Surface Service Area",
        name__contains=CURTAILED_RIGHT)
    prior_budget = AllocationPlan.objects.get(zone=zone, water_type=sw, reporting_period=prior)
    open_budget = AllocationPlan.objects.get(zone=zone, water_type=sw, reporting_period=open_wy)
    assert open_budget.allocation_acre_feet < prior_budget.allocation_acre_feet, (
        "curtailed district's open-year surface budget should be reduced vs the prior year")


# --------------------------------------------------------------------------
# Group 3 — curtailment + groundwater substitution
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_curtailed_parcels_have_no_surface_delivery_after_curtailment(seeded):
    curtailed = _curtailed_parcels()
    assert curtailed, "fixture should have parcels served by the curtailed right"
    for p in curtailed:
        rows = ParcelLedger.objects.filter(parcel=p, source_type="surface_diversion")
        assert rows.filter(effective_date__lt=FIRST_CURTAILED_MONTH).exists(), (
            f"{p.parcel_number} should have pre-curtailment surface deliveries")
        assert not rows.filter(effective_date__gte=FIRST_CURTAILED_MONTH).exists(), (
            f"{p.parcel_number} has a surface delivery after curtailment")


@pytest.mark.django_db
def test_curtailed_conjunctive_parcels_substitute_groundwater(seeded):
    """Conjunctive growers under the curtailed right pump MORE groundwater in the
    dry post-curtailment months than equivalent non-curtailed conjunctive growers."""
    curtailed_ids = {p.id for p in _curtailed_parcels()}

    def post_curtailment_gw(parcels):
        total = Decimal("0")
        for p in parcels:
            for r in ParcelLedger.objects.filter(
                    parcel=p, source_type__in=GW_EXTRACTION_SOURCES):
                if r.effective_date.month in POST_CURTAILMENT_MONTHS and r.effective_date.year == 2025:
                    total += abs(r.amount_acre_feet)
        # Per acre, so unequal group acreage can't skew the comparison.
        acres = sum(Decimal(str(p.area_acres or 0)) for p in parcels) or Decimal("1")
        return total / acres

    # Only metered conjunctive parcels carry seed groundwater now (52.5-01); an
    # unmetered conjunctive parcel's substitution emerges from the engine in
    # Plan 02, not the seed. Compare like with like — metered vs metered.
    conjunctive = [
        p for p in Parcel.objects.filter(parcel_number__startswith="MER-APN-")
        if _source_of(p) == "conjunctive" and _parcel_has_metered_well(p)
    ]
    curtailed_conj = [p for p in conjunctive if p.id in curtailed_ids]
    normal_conj = [p for p in conjunctive if p.id not in curtailed_ids]
    assert curtailed_conj and normal_conj, (
        "need both curtailed and normal METERED conjunctive parcels")

    assert post_curtailment_gw(curtailed_conj) > post_curtailment_gw(normal_conj) * Decimal("1.2"), (
        "curtailed conjunctive parcels should show a clear groundwater-substitution bump")


# --------------------------------------------------------------------------
# Group 4 — shared-well apportionment
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_shared_well_extraction_splits_by_fraction_and_sums_to_total(seeded):
    # Shared groups that ALSO write seed extraction are the METERED multi-parcel
    # wells (52.5-01: unmetered wells write no seed rows, so apportionment is only
    # observable for the metered ones).
    shared = []
    for well in Well.objects.filter(
        well_registration_id__startswith="MER-W-",
        measurement_method="certified_meter",
    ):
        links = list(WellIrrigatedParcel.objects.filter(well=well))
        if len(links) > 1:
            shared.append((well, links))
    assert shared, "fixture should contain a metered shared well"

    for well, links in shared:
        # month -> {parcel_id: summed |extraction|}
        by_month = defaultdict(dict)
        frac_of = {ln.parcel_id: ln.fraction for ln in links}
        for ln in links:
            for r in ParcelLedger.objects.filter(
                    parcel_id=ln.parcel_id, source_type__in=GW_EXTRACTION_SOURCES):
                key = (r.effective_date.year, r.effective_date.month)
                by_month[key][ln.parcel_id] = (
                    by_month[key].get(ln.parcel_id, Decimal("0")) + abs(r.amount_acre_feet))
        assert by_month, f"{well.well_registration_id} produced no extraction rows"
        frac_sum = sum(frac_of.values())  # 1/N rounded to 4dp may sum to 0.9999
        for key, shares in by_month.items():
            # Every member is represented — none dropped.
            assert set(shares.keys()) == set(frac_of.keys()), (
                f"{well.well_registration_id} {key}: a member parcel was dropped")
            group_total = sum(shares.values())
            # Reconstruct the well's true monthly total from the stored fractions,
            # so the check is robust to the 1/N rounding residual (3 x 0.3333 != 1).
            implied_well_total = group_total / frac_sum
            for pid, frac in frac_of.items():
                share = shares[pid]
                expected = implied_well_total * frac
                assert abs(share - expected) <= Decimal("0.0002"), (
                    f"{well.well_registration_id} {key}: parcel {pid} got {share}, "
                    f"expected its stored fraction {frac} of the well total "
                    f"({implied_well_total:.4f}) = {expected:.4f}")
                # No single parcel double-counts the whole well.
                if len(frac_of) > 1:
                    assert share < group_total, (
                        f"{well.well_registration_id} {key}: parcel {pid} took the "
                        "whole well total")


# --------------------------------------------------------------------------
# Group 5 — idempotency
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_second_seed_run_does_not_change_counts():
    _build_physical_merced()
    call_command("seed_merced_ledgers")

    def counts():
        merced_zone_ids = list(Zone.objects.filter(
            zone_type="custom", name__startswith="MER Surface Service Area"
        ).values_list("id", flat=True)) + list(Zone.objects.filter(
            zone_type="management_area", basin_code="5-022.04"
        ).values_list("id", flat=True))
        return {
            "ledger": ParcelLedger.objects.filter(
                parcel__parcel_number__startswith="MER-APN-").count(),
            "accounts": WaterAccount.objects.filter(
                account_number__startswith="MER-ACCT-").count(),
            "budgets": AllocationPlan.objects.filter(zone_id__in=merced_zone_ids).count(),
        }

    first = counts()
    call_command("seed_merced_ledgers")
    second = counts()
    assert first == second, f"seed is not idempotent: {first} != {second}"
    assert first["ledger"] > 0 and first["accounts"] > 0 and first["budgets"] > 0


# --------------------------------------------------------------------------
# ISS-052: demand-aware surface sizing (pure helper — Django-free, no DB)
# These prove the sizing math directly; the live demand-vs-fallback behavior is
# exercised end-to-end on Butler (the fixture above carries no ET cache, so it
# correctly uses the face-value fallback path and its assertions are unchanged).
# --------------------------------------------------------------------------

from core.management.commands.seed_merced_ledgers import (  # noqa: E402
    _demand_aware_deliveries,
)

_EFF = Decimal("0.75")
_ND = {5: Decimal("12.3"), 6: Decimal("8.5"), 7: Decimal("15.0"), 8: Decimal("14.0")}


def test_demand_aware_ample_right_delivers_demand_over_efficiency():
    """A right covering full demand-supply: every month = demand/efficiency, and
    NO month exceeds it — the pre-052 over-delivery spikes are gone."""
    out = _demand_aware_deliveries(_ND, annual_envelope=Decimal("100"), efficiency=_EFF)
    for m, d in _ND.items():
        assert out[m] == d / _EFF
        assert out[m] <= d / _EFF  # the physical cap is never exceeded


def test_demand_aware_short_right_distributes_envelope_by_demand():
    """A conjunctive parcel whose right is short of full demand: the envelope is
    distributed by demand shape (sums to the envelope) and never exceeds
    demand/efficiency — the parcel pumps the shortfall as groundwater."""
    env = Decimal("30")
    out = _demand_aware_deliveries(_ND, annual_envelope=env, efficiency=_EFF)
    assert abs(sum(out.values(), Decimal("0")) - env) < Decimal("0.0001")
    for m, d in _ND.items():
        assert out[m] <= d / _EFF


def test_demand_aware_no_demand_returns_empty_for_fallback():
    """No net demand at all -> empty mapping; the seed then falls back to
    face-value seasonal sizing (local dev without an ET cache)."""
    assert _demand_aware_deliveries({}, Decimal("50"), _EFF) == {}
    assert _demand_aware_deliveries({1: Decimal("0")}, Decimal("50"), _EFF) == {}
