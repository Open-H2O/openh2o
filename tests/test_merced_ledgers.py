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
from core.models import SiteConfig
from geography.models import Boundary, ParcelZone, Zone
from parcels.models import Parcel, ParcelLedger
from surface.models import (
    DiversionRecord,
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
# the proven engine path (Oct 2024 – Sep 2025).
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
    as they would on the real demo.
    """
    boundary = Boundary.objects.create(name="Merced Subbasin", geometry=_box(-120.5, 37.2, 1.0))

    # Three GSA management-area zones (the groundwater authority), keyed like the
    # real seed_merced_gsas output (zone_type management_area, basin 5-022.04).
    gsas = {}
    for i, gname in enumerate([
        "Halvern Valley GSA", "Halvern Irrigation-Urban GSA", "Verdano Island Water District GSA",
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
        right_id=NORMAL_RIGHT, right_type=post14, holder_name="Halvern Irrigation District",
        priority_date=date(1930, 4, 10), face_value_acre_feet=Decimal("120000"),
        status="active", source_name="Merced River",
    )
    curtailed = WaterRight.objects.create(
        right_id=CURTAILED_RIGHT, right_type=post14, holder_name="Saddlebow Irrigation District",
        priority_date=date(1962, 5, 5), face_value_acre_feet=Decimal("9000"),
        status="curtailed", source_name="El Nido Canal",
    )
    pod_normal = PointOfDiversion.objects.create(
        water_right=normal, name="MER-POD-004 Atwater Canal Headgate",
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
        serve(pod_normal, make_parcel("surface", gsa_list[0], "Tulepine Ranch Partners"))
    for _ in range(2):
        p = make_parcel("conjunctive", gsa_list[1], "Ashvale Orchards Inc.")
        serve(pod_normal, p)
        solo_well(p)

    # Curtailed district: 2 surface-only + 2 conjunctive (the substitution growers).
    for _ in range(2):
        serve(pod_curtailed, make_parcel("surface", gsa_list[2], "Saddlebow Ag Holdings"))
    for _ in range(2):
        p = make_parcel("conjunctive", gsa_list[2], "Saddlebow Ag Holdings")
        serve(pod_curtailed, p)
        solo_well(p)

    # Groundwater-only: 1 solo + two shared groups (N=2 and N=3).
    solo_well(make_parcel("groundwater", gsa_list[0], "Halvern Valley Farms LLC"))
    shared_well([
        make_parcel("groundwater", gsa_list[1], "Muddy Bar Growers") for _ in range(2)
    ])
    shared_well([
        make_parcel("groundwater", gsa_list[2], "Verdano Island Farms LLC") for _ in range(3)
    ])

    # Normalize each POD's parcel fractions to sum to ~1.0 (1/N), exactly as the
    # real seed_merced_operations / parcels_from_selection do. The 55-03 seed splits
    # a recorded district total across served parcels; with no ET cache here the
    # platform service uses the static fraction fallback, which only sums to the
    # district total when the fractions sum to 1 — so the fixture must mirror the
    # real per-POD normalization rather than leaving every link at 1.0.
    for pod in PointOfDiversion.objects.all():
        links = list(PointOfDiversionParcel.objects.filter(point_of_diversion=pod))
        if not links:
            continue
        frac = Decimal(str(round(1.0 / len(links), 4)))
        for ln in links:
            ln.fraction = frac
            ln.save(update_fields=["fraction"])


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
# Group 6 — surface deliveries are produced by the PLATFORM allocation service
#
# Phase 55-03 retired the seed's private surface-sizing helpers
# (_demand_aware_deliveries / _net_demand_af) and wired the seed to
# surface.services.allocate_district_delivery. The unit tests for the deleted
# helpers are gone; the kernel's own math is covered by tests/test_allocation_math.py
# and the service by tests/test_surface_allocation.py. These tests prove the SEED
# now calls the service: it records a district total per POD/month and the
# service splits that total across served parcels (demand-weighted in a deployment;
# static-fraction fallback here, where the fixture carries no ET cache), summing
# back to the recorded diversions.
# --------------------------------------------------------------------------
@pytest.mark.django_db
def test_seed_records_a_diversion_per_served_pod(seeded):
    """The seed synthesizes DiversionRecords — the recorded district total the
    service splits — for each MER POD that serves parcels."""
    pods_with_parcels = PointOfDiversion.objects.filter(
        water_right__right_id__startswith="MER-WR-",
        pod_parcels__isnull=False,
    ).distinct()
    assert pods_with_parcels.exists(), "fixture should have PODs serving parcels"
    for pod in pods_with_parcels:
        assert DiversionRecord.objects.filter(point_of_diversion=pod).exists(), (
            f"{pod.name} serves parcels but has no recorded diversion")


@pytest.mark.django_db
def test_seed_sets_agency_irrigation_efficiency_on_siteconfig(seeded):
    """The seed installs the demo's agency-wide efficiency (0.750) on the
    SiteConfig singleton, which the allocation service reads."""
    config = SiteConfig.objects.get()
    assert config.default_irrigation_efficiency == Decimal("0.750")


@pytest.mark.django_db
def test_seed_surface_rows_sum_to_recorded_diversions_per_pod(seeded):
    """The per-parcel surface_diversion magnitudes the service wrote sum (per POD,
    per month) to the recorded DiversionRecord total — the demand-weighted /
    fraction-split allocation conserves the metered district delivery."""
    pods = PointOfDiversion.objects.filter(
        water_right__right_id__startswith="MER-WR-",
        pod_parcels__isnull=False,
    ).distinct()
    checked = 0
    for pod in pods:
        served_ids = list(
            PointOfDiversionParcel.objects.filter(point_of_diversion=pod)
            .values_list("parcel_id", flat=True)
        )
        for rec in DiversionRecord.objects.filter(point_of_diversion=pod):
            delivered = ParcelLedger.objects.filter(
                parcel_id__in=served_ids,
                source_type="surface_diversion",
                effective_date=rec.month,
            )
            # surface_diversion is stored NEGATIVE; magnitude = recorded total.
            total = sum((abs(r.amount_acre_feet) for r in delivered), Decimal("0"))
            assert abs(total - rec.volume_acre_feet) <= Decimal("0.001"), (
                f"{pod.name} {rec.month}: split sums to {total}, "
                f"recorded {rec.volume_acre_feet}")
            checked += 1
    assert checked > 0, "expected at least one POD-month to verify"


@pytest.mark.django_db
def test_seed_surface_split_is_demand_weighted_when_calculations_exist(seeded):
    """With per-parcel ET demand present (CalculationRun rows), the service splits a
    short delivery by demand weight — the thirstier parcel gets the larger share.

    Proves the seed routes through the demand-weighted path, not just the fallback:
    we add CalculationRun demand for two parcels on one POD, re-run the seed, and
    assert the higher-demand parcel received more of that month's delivery."""
    from django.db.models import Sum

    from accounting.models import CalculationRun

    pod = PointOfDiversion.objects.filter(
        water_right__right_id=NORMAL_RIGHT, pod_parcels__isnull=False
    ).distinct().first()
    assert pod is not None
    served = list(
        PointOfDiversionParcel.objects.filter(point_of_diversion=pod)
        .select_related("parcel").order_by("id")
    )
    assert len(served) >= 2, "need at least two served parcels to compare shares"
    thirsty, modest = served[0].parcel, served[1].parcel

    # A June 2025 (prior WY) month with sharply different demand. The recorded
    # district total is fixed; a SHORT delivery (demand-supply exceeds it) forces
    # the demand-weighted branch so the larger-demand parcel wins.
    month = "2025-06"
    CalculationRun.objects.create(
        parcel=thirsty, period=month,
        gross_et_af=Decimal("90"), net_consumptive_use_af=Decimal("90"),
        final_af=Decimal("0"))
    CalculationRun.objects.create(
        parcel=modest, period=month,
        gross_et_af=Decimal("10"), net_consumptive_use_af=Decimal("10"),
        final_af=Decimal("0"))

    call_command("seed_merced_ledgers")

    jun = date(2025, 6, 15)

    def delivered(parcel):
        return abs(
            ParcelLedger.objects.filter(
                parcel=parcel, source_type="surface_diversion", effective_date=jun
            ).aggregate(s=Sum("amount_acre_feet"))["s"] or Decimal("0")
        )

    assert delivered(thirsty) > delivered(modest), (
        "demand-weighted split should give the thirstier parcel the larger share")


# --------------------------------------------------------------------------
# Group 8 — the second water year carries a supply side (133-02)
#
# Before 133-02 `_month_schedule()` hardcoded WY 2024-2025's twelve months and
# every one of its four callers built that year and nothing else, so the open
# water year had a full demand side (133-01) and no water at all.
# --------------------------------------------------------------------------
def _schedule_for(period_name, start, end):
    """The seed command's month schedule for a period with these dates."""
    from core.management.commands.seed_merced_ledgers import Command

    period = ReportingPeriod(name=period_name, start_date=start, end_date=end)
    return Command()._month_schedule(period)


def test_month_schedule_walks_the_open_water_year():
    """WY 2025-2026 yields 2025-10 through 2026-09 — twelve months, in order.

    No database: the schedule is a pure function of the period's own dates, which
    is the whole point of the 133-02 change.
    """
    schedule = _schedule_for(OPEN_WY, date(2025, 10, 1), date(2026, 9, 30))

    assert len(schedule) == 12
    assert [(d.year, d.month) for d, _ in schedule] == [
        (2025, 10), (2025, 11), (2025, 12),
        (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6),
        (2026, 7), (2026, 8), (2026, 9),
    ]
    assert all(d.day == 15 for d, _ in schedule), "mid-month convention"
    assert all(mn == d.month for d, mn in schedule)


def test_month_schedule_still_walks_the_prior_water_year():
    """The committed year is unchanged — same twelve dates the literals produced."""
    schedule = _schedule_for(PRIOR_WY, date(2024, 10, 1), date(2025, 9, 30))

    assert [(d.year, d.month) for d, _ in schedule] == [
        (2024, 10), (2024, 11), (2024, 12),
        (2025, 1), (2025, 2), (2025, 3), (2025, 4), (2025, 5), (2025, 6),
        (2025, 7), (2025, 8), (2025, 9),
    ]


@pytest.mark.django_db
def test_both_periods_carry_supply_on_the_same_parcels(seeded):
    """Every parcel with supply in the prior year has supply in the open year too.

    Checked per source and per parcel rather than in aggregate: a basin total can
    be non-zero while a whole class of parcel is empty, and an empty parcel detail
    panel is exactly the blank screen this milestone exists to close.
    """
    prior = ReportingPeriod.objects.get(name=PRIOR_WY)
    open_wy = ReportingPeriod.objects.get(name=OPEN_WY)

    for source_type in ("surface_diversion", "meter_reading"):
        def parcels_with(period):
            return set(
                ParcelLedger.objects.filter(
                    reporting_period=period, source_type=source_type
                ).values_list("parcel_id", flat=True)
            )

        prior_parcels = parcels_with(prior)
        open_parcels = parcels_with(open_wy)
        assert prior_parcels, f"fixture should produce {source_type} rows"

        # The curtailed right records no diversion in the open year at all — that
        # is the ruling in CURTAILMENT_LAST_DELIVERY's comment block, not a gap.
        expected = prior_parcels
        if source_type == "surface_diversion":
            expected = prior_parcels - {p.id for p in _curtailed_parcels()}

        assert expected <= open_parcels, (
            f"{source_type}: parcels {sorted(expected - open_parcels)} have supply "
            f"in {PRIOR_WY} but none in {OPEN_WY}"
        )


@pytest.mark.django_db
def test_seed_is_deterministic_across_both_water_years(seeded):
    """A second seed reproduces the first, row for row, in both periods.

    The seed self-flushes, so this exercises a full delete-and-rebuild rather than
    an upsert. No `random` anywhere in the supply path is what makes it hold.
    """
    def payload():
        return sorted(
            ParcelLedger.objects.values_list(
                "parcel_id", "effective_date", "source_type",
                "amount_acre_feet", "reporting_period__name",
            )
        )

    first = payload()
    assert first, "fixture should produce ledger rows"

    call_command("seed_merced_ledgers")
    second = payload()

    assert first == second, "a re-run changed the ledger"


@pytest.mark.django_db
def test_curtailed_district_delivers_nothing_in_the_open_year(seeded):
    """The El Nido cut carries across the whole open year, and the paper trail says so.

    Three facts together, because any one alone is ambiguous: the district
    delivered water in the prior year, it delivers none in the open year, and its
    open-year allocation is still a positive tenth of face value. The gap between
    a live 10% budget and zero deliveries is the curtailment order doing its job —
    not a seeding hole.
    """
    from django.db.models import Sum

    curtailed_ids = [p.id for p in _curtailed_parcels()]
    assert curtailed_ids, "fixture should have parcels under the curtailed right"

    def delivered(period_name):
        return abs(
            ParcelLedger.objects.filter(
                parcel_id__in=curtailed_ids,
                source_type="surface_diversion",
                reporting_period__name=period_name,
            ).aggregate(s=Sum("amount_acre_feet"))["s"] or Decimal("0")
        )

    assert delivered(PRIOR_WY) > 0, "the curtailed district delivered before the cut"
    assert delivered(OPEN_WY) == 0, (
        "MER-CURT-001 is effective 2025-07-01 and never rescinded, so every month "
        "of the open year sits after CURTAILMENT_LAST_DELIVERY"
    )

    open_wy = ReportingPeriod.objects.get(name=OPEN_WY)
    open_budget = AllocationPlan.objects.filter(
        reporting_period=open_wy,
        zone__name__startswith="MER Surface Service Area",
        notes__startswith="Surface allocation reduced",
    ).aggregate(s=Sum("allocation_acre_feet"))["s"] or Decimal("0")
    assert open_budget > 0, (
        "the collapsed open-year allocation should still be a positive tenth of "
        "face value — the contrast with zero deliveries is the story"
    )


@pytest.mark.django_db
def test_diversion_records_are_stamped_with_their_own_period(seeded):
    """No DiversionRecord carries a period whose span excludes its month.

    `surface.services._records_for_period` matches a record on its reporting_period
    FK **OR** on its month falling inside the period span. A second year's records
    left stamped with the first year's FK would therefore be allocated against BOTH
    periods and double-count the supply.
    """
    mismatched = [
        (r.point_of_diversion_id, r.month, r.reporting_period.name)
        for r in DiversionRecord.objects.select_related("reporting_period")
        if r.reporting_period is not None
        and not (r.reporting_period.start_date <= r.month <= r.reporting_period.end_date)
    ]
    assert not mismatched, f"records stamped outside their period: {mismatched}"


# ---------------------------------------------------------------------------
# 134-01: the storm the recharge intake exists for
# ---------------------------------------------------------------------------
# `MER-BPOD-001 El Nido Canal Recharge Intake` says on its own page that it is
# "operated during high-flow/storm events to divert water for managed aquifer
# recharge", and said "No diversion records yet." directly beneath it. These lock
# the to-storage records that fill that gap — and lock the two ways the storm
# could reach somewhere it must not: a parcel's ledger, or a second copy of
# itself on the next re-run.

# The two intakes the fixture builds, mirroring the real demo's shape: the El Nido
# canal intake carries NO water right (so `_flush`'s MER-WR- filter cannot see it
# and the name-prefix flush is the only thing stopping it accumulating), and the
# Flood-MAR take hangs off an ordinary MER-WR- right.
BASIN_INTAKE_POD = "MER-BPOD-001 El Nido Canal Recharge Intake"
FLOOD_MAR_POD = "MER-POD-009-DEMO Bottomlands Riparian Take"


def _build_recharge_basins():
    """Two feeding intakes and the four basins they fill.

    Shape, not scale: what matters is one intake with a water right and one
    without, because those two take different paths through `_flush`.
    """
    from recharge.models import RechargeSite, RechargeSitePOD

    right = WaterRight.objects.get(right_id=NORMAL_RIGHT)
    intake = PointOfDiversion.objects.create(
        water_right=None, name=BASIN_INTAKE_POD,
        location=Point(-120.49, 37.22), status="active",
    )
    flood_mar = PointOfDiversion.objects.create(
        water_right=right, name=FLOOD_MAR_POD,
        location=Point(-120.52, 37.26), status="active",
    )
    caps = {
        intake: [("El Nido Recharge Basin 1", "637.1"), ("El Nido Recharge Basin 2", "1281.1")],
        flood_mar: [
            ("Merced River Ag Parcel 1 (Flood-MAR)", "159.6"),
            ("Merced River Ag Parcel 2 (Flood-MAR)", "266.5"),
        ],
    }
    for pod, basins in caps.items():
        for name, cap in basins:
            site = RechargeSite.objects.create(
                name=name, location=pod.location, site_type="spreading_basin",
                operator="Halvern Irrigation District",
                capacity_acre_feet=Decimal(cap), status="active",
            )
            RechargeSitePOD.objects.create(recharge_site=site, point_of_diversion=pod)
    return intake, flood_mar


@pytest.fixture
def seeded_with_basins():
    """The physical slice PLUS recharge basins, then the ledger seed.

    Kept separate from `seeded` on purpose: adding basins changes the diversion
    record count, and the tests above assert against a slice without them.
    """
    _build_physical_merced()
    pods = _build_recharge_basins()
    call_command("seed_merced_ledgers")
    return pods


def _to_storage():
    return DiversionRecord.objects.filter(diversion_type="to_storage")


@pytest.mark.django_db
def test_every_managed_fill_has_a_to_storage_diversion_behind_it(seeded_with_basins):
    """Six fill dates x two feeding intakes = twelve records, 8 wet + 4 dry.

    The wet year spreads four storms, the dry year two (RECHARGE_SEASONS), so the
    split is not symmetric and a test that only counted twelve would pass on a
    seed that wrote both years into one.
    """
    by_period = defaultdict(int)
    for rec in _to_storage().select_related("reporting_period"):
        by_period[rec.reporting_period.name] += 1

    assert _to_storage().count() == 12, "expected one record per fill date per intake"
    assert by_period["WY 2024-2025"] == 8, "four wet-year storms across two intakes"
    assert by_period["WY 2025-2026"] == 4, "two dry-year storms across two intakes"


@pytest.mark.django_db
def test_each_storm_record_carries_a_period_and_a_peak_rate(seeded_with_basins):
    """The two fields a CalWATRS To Storage filing cannot be produced without.

    A NULL `reporting_period` makes the record invisible to every period-scoped
    filing (133-02: `_records_for_period` matches FK **or** month span, so it also
    double-allocates). A NULL `max_flow_rate_cfs` leaves the worksheet's
    "Max rate (CFS)" column blank, which is where all 161 prior records left it.
    """
    for rec in _to_storage().select_related("reporting_period"):
        assert rec.reporting_period is not None, f"{rec} carries no reporting period"
        assert rec.max_flow_rate_cfs is not None, f"{rec} carries no peak flow rate"
        assert rec.max_flow_rate_cfs > 0, f"{rec} records a peak rate of {rec.max_flow_rate_cfs}"
        assert rec.reporting_period.start_date <= rec.month <= rec.reporting_period.end_date


@pytest.mark.django_db
def test_the_diverted_volume_equals_the_fills_it_paid_for(seeded_with_basins):
    """The paper and the water agree, derived from the same schedule.

    Each record's volume is the sum of the basin fills its intake fed on that
    date. Computed here from the events seed's own schedule and the basins'
    capacities — the same two inputs the ledger seed reads — so a drift in either
    breaks this rather than passing quietly.
    """
    from core.management.commands.seed_merced_recharge_events import RECHARGE_SEASONS
    from recharge.models import RechargeSitePOD

    expected = defaultdict(Decimal)
    for link in RechargeSitePOD.objects.select_related(
        "recharge_site", "point_of_diversion"
    ):
        cap = link.recharge_site.capacity_acre_feet or Decimal("0")
        for season in RECHARGE_SEASONS.values():
            for fill_date, fraction in season:
                key = (link.point_of_diversion_id, fill_date)
                expected[key] += (cap * fraction).quantize(Decimal("0.0001"))

    for rec in _to_storage():
        key = (rec.point_of_diversion_id, rec.month)
        assert key in expected, f"{rec} matches no scheduled fill"
        assert rec.volume_acre_feet == expected[key].quantize(Decimal("0.0001")), (
            f"{rec.point_of_diversion} {rec.month}: recorded "
            f"{rec.volume_acre_feet} AF against {expected[key]} AF of fills"
        )
        assert rec.volume_acre_feet > 0, "the 161 existing records are positive; match them"
        assert rec.returned_af == Decimal("0"), (
            "water spread in a recharge basin percolates; none returns to the stream"
        )


@pytest.mark.django_db
def test_the_storm_never_reaches_a_parcels_account():
    """Adding the storm must not move one acre-foot of anybody's delivery.

    The recharge credit already reaches the basin pool through
    `create_recharge_ledger_entries`. If a to-storage record were ever allocated
    across parcels the same water would be counted twice, and the demonstration's
    surface-delivered total would drift.

    This is measured, not reasoned: seed the same slice with and without recharge
    basins and compare the surface-delivered total. The comparison catches the
    real coupling rather than a symptom — `surface.services._records_for_period`
    does NOT filter on `diversion_type`, so `allocate_district_delivery` would
    split a to-storage record across the ten parcels MER-POD-009-DEMO serves if
    one existed when it ran. The seed writes them after the last allocator call in
    the build for exactly that reason.
    """
    from django.db.models import Sum

    def _surface_total():
        return ParcelLedger.objects.filter(
            source_type="surface_diversion"
        ).aggregate(s=Sum("amount_acre_feet"))["s"] or Decimal("0")

    _build_physical_merced()
    call_command("seed_merced_ledgers")
    without_basins = _surface_total()
    assert without_basins != 0, "the fixture delivered no surface water at all"

    _build_recharge_basins()
    call_command("seed_merced_ledgers")
    with_basins = _surface_total()

    assert _to_storage().count() == 12, "the storm records were not written"
    assert with_basins == without_basins, (
        f"surface delivered moved from {without_basins} AF to {with_basins} AF "
        f"when the storm was added — a to-storage record reached a parcel"
    )


@pytest.mark.django_db
def test_the_storm_does_not_accumulate_on_a_re_run(seeded_with_basins):
    """The flush must reach the intake that has no water right.

    `_flush` deletes diversion records by `water_right__right_id__startswith=
    "MER-WR-"`. MER-BPOD-001 carries no right at all, so before 134-01 extended
    the flush by name prefix, a second run would have left the El Nido records
    behind and written them again. `refresh_merced_accounting`'s pass 2 re-runs
    this command on every build, so this is the ordinary path, not an edge case.
    """
    first = {
        (r.point_of_diversion_id, r.month, str(r.volume_acre_feet))
        for r in _to_storage()
    }
    call_command("seed_merced_ledgers")
    second = {
        (r.point_of_diversion_id, r.month, str(r.volume_acre_feet))
        for r in _to_storage()
    }

    assert _to_storage().count() == 12, "a re-run duplicated the storm records"
    assert first == second, "a re-run changed the storm records"


@pytest.mark.django_db
def test_the_to_storage_report_can_be_produced_in_both_years(seeded_with_basins):
    """The CalWATRS layout that could not be produced from the demo at all.

    All 161 seeded records were `direct_use`, so `validate_report(period,
    "calwatrs_a2")` errored in BOTH water years — "No to storage diversion records
    for this period". A basin fill IS a to-storage diversion, so writing the
    records above fixes the report as a consequence rather than as extra work.
    """
    from reporting.validators import validate_report

    for period in ReportingPeriod.objects.all():
        errors = [
            w for w in validate_report(period, "calwatrs_a2") if w["level"] == "error"
        ]
        assert not errors, f"{period.name} calwatrs_a2 errors: {errors}"
