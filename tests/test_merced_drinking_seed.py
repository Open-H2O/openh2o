# SPDX-License-Identifier: AGPL-3.0-or-later
"""seed_merced_drinking builds the drinking-water half of the Merced demo.

The command onboards the City of Merced (CA2410009) from committed federal
payloads, creates its municipal supply wells and the facility links to them,
creates the PS Codes the lab file is matched on, and imports three years of
California's own published laboratory results.

What these tests are actually protecting:

* The demonstration data stays REAL. The system, the facilities, the PS Codes
  and every result are published public record; the seed must never invent one,
  and `seed_merced_details` must never staple a fabricated registry number onto
  a real utility's well.
* The quality-to-quantity join is populated. `SystemFacility.well` is the whole
  argument for putting a drinking-water system in this particular subbasin, and
  an unlinked facility makes the demo silently pointless.
* The seed keeps going through the production write paths. If onboarding or the
  importer changes shape, this seed should fail rather than quietly drift into a
  private second implementation.
"""
import gzip
import json
import os

import pytest
from django.core.management import call_command

from drinking.models import (
    EnvirofactsCache,
    SampleResult,
    SamplingPoint,
    SystemFacility,
    WaterSystem,
)
from wells.models import Well, WellType

PWSID = "CA2410009"
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "merced", "drinking",
)


def _data(name):
    return os.path.join(DATA_DIR, name)


@pytest.fixture
def seeded(db):
    """The vocabulary prerequisites, then the seed itself."""
    call_command("seed_well_types")
    call_command("seed_drinking")
    call_command("seed_merced_drinking")
    return WaterSystem.objects.get(pwsid=PWSID)


# -- the committed data itself ------------------------------------------------


def test_committed_payload_carries_no_personal_contact_details():
    """EPA names an individual; drinking/models.py refuses to store them.

    The repository is public, so committing the raw payload would re-publish
    exactly what the schema declined to carry. This is the tripwire on that.
    """
    forbidden = {
        "admin_name", "org_name", "email_addr", "phone_number",
        "phone_ext_number", "alt_phone_number", "fax_number",
    }
    for filename in (
        "envirofacts_water_system.json",
        "envirofacts_facilities.json",
        "envirofacts_geographic_area.json",
    ):
        with open(_data(filename)) as f:
            rows = json.load(f)
        for row in rows:
            leaked = forbidden & {key.lower() for key in row}
            assert not leaked, f"{filename} re-publishes {sorted(leaked)}"


def test_lab_file_is_exactly_three_years():
    """Brent asked for three years so trends are visible; pin the window."""
    import csv
    import datetime

    with gzip.open(_data("merced_lab_results_3yr.tab.gz"), "rt") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    dates = sorted(
        datetime.datetime.strptime(r["Sample Date"].strip(), "%m-%d-%Y").date()
        for r in rows
        if r["Sample Date"].strip()
    )
    assert rows, "the committed lab file is empty"
    assert (dates[-1] - dates[0]).days >= 365 * 3 - 31, (
        f"lab file spans {dates[0]} to {dates[-1]}, less than three years"
    )
    # Every row belongs to the system this seed claims to be seeding.
    assert {r["Water System Number"].strip() for r in rows} == {PWSID}


# -- the seed -----------------------------------------------------------------


@pytest.mark.django_db
def test_seeds_the_real_city_of_merced(seeded):
    assert seeded.name == "CITY OF MERCED"
    assert seeded.pws_type == "CWS"
    assert seeded.primary_source_code == "GW"
    assert seeded.population_residential is None or seeded.population_residential > 0
    # 100% groundwater is the reason this system belongs in this subbasin.
    assert seeded.primary_source_code.startswith("GW")


@pytest.mark.django_db
def test_facilities_and_points_come_from_the_published_record(seeded):
    facilities = SystemFacility.objects.filter(system=seeded)
    assert facilities.count() > 50, "EPA publishes 61 facilities for this system"

    points = SamplingPoint.objects.filter(facility__system=seeded)
    assert points.count() == 27

    # The distribution-system points are the ones a digits-only assumption
    # would silently drop, so pin them explicitly.
    assert points.filter(ps_code=f"{PWSID}_DST_LCR").exists()
    assert points.filter(ps_code__startswith=f"{PWSID}_DST_9").count() == 4


@pytest.mark.django_db
def test_lcr_tap_is_a_tap_not_a_distribution_point(seeded):
    """A Lead and Copper Rule sample is drawn at a customer's tap.

    It hangs off the distribution system exactly like the DBPR points do, so
    facility type alone cannot tell them apart — the seed special-cases it and
    this is the pin on that.
    """
    lcr = SamplingPoint.objects.get(ps_code=f"{PWSID}_DST_LCR")
    assert lcr.point_type == "tap"
    dbpr = SamplingPoint.objects.get(ps_code=f"{PWSID}_DST_900")
    assert dbpr.point_type == "distribution"


@pytest.mark.django_db
def test_quality_to_quantity_join_is_populated(seeded):
    """The join the whole demonstration exists to show."""
    linked = SystemFacility.objects.filter(
        system=seeded, well__isnull=False
    )
    assert linked.count() == 21, "all 21 sampled source wells should be linked"

    facility = linked.first()
    assert facility.well.well_registration_id.startswith("MER-PWS-")
    assert facility.well.owner_name == "CITY OF MERCED"
    assert facility.well.well_type == WellType.objects.get(name="Production")
    assert facility.well.location is not None


@pytest.mark.django_db
def test_municipal_wells_carry_only_what_is_published(seeded):
    """No invented construction data on a real utility's wells.

    GAMA publishes no usable depth for these, and a plausible-looking screen
    interval for only three of them. A blank field here is a deliberate "not
    published", and `seed_merced_details` is required to leave it that way.
    """
    wells = Well.objects.filter(well_registration_id__startswith="MER-PWS-")
    assert wells.count() == 21
    assert all(w.depth_ft is None for w in wells)
    assert wells.filter(screen_top_ft__isnull=False).count() == 3

    call_command("seed_merced_details")

    for well in Well.objects.filter(well_registration_id__startswith="MER-PWS-"):
        assert well.depth_ft is None, "details invented a depth"
        assert not well.wcr_number, "details invented a DWR completion report no."
        assert not well.state_well_number, "details invented a State Well Number"
        assert not well.pump_type, "details invented a pump type"


@pytest.mark.django_db
def test_imports_three_years_of_real_results(seeded):
    results = SampleResult.objects.filter(
        event__sampling_point__facility__system=seeded
    )
    assert results.count() > 20000

    # Most drinking-water monitoring proves absence. If this ratio inverts,
    # something has started reading non-detects as measurements.
    non_detects = results.filter(less_than_rl=True).count()
    assert non_detects > results.count() * 0.9

    # A non-detect binds its floor in reporting_level and stores no value —
    # the distinction `less_than_rl` exists to draw.
    sample = results.filter(less_than_rl=True).first()
    assert sample.result_value is None
    assert sample.reporting_level is not None


@pytest.mark.django_db
def test_nitrate_trend_is_visible(seeded):
    """Three years was asked for so a trend can be seen; prove one is there."""
    nitrate = SampleResult.objects.filter(
        event__sampling_point__facility__system=seeded,
        analyte__name__iexact="nitrate",
        less_than_rl=False,
    )
    assert nitrate.count() > 50
    years = {r.event.sample_date.year for r in nitrate}
    assert len(years) >= 3, f"nitrate detections only span {sorted(years)}"


@pytest.mark.django_db
def test_envirofacts_cache_lets_the_wizard_work_offline(seeded):
    """The onboarding wizard stays usable in the demo with no outbound net."""
    cached = EnvirofactsCache.objects.filter(pwsid=PWSID)
    assert cached.count() == 3
    assert set(cached.values_list("table_name", flat=True)) == {
        "WATER_SYSTEM", "WATER_SYSTEM_FACILITY", "GEOGRAPHIC_AREA",
    }


@pytest.mark.django_db
def test_rerunning_is_a_no_op(seeded):
    """Idempotent: the nightly demo rebuild must not multiply the data."""
    before = (
        SampleResult.objects.count(),
        SamplingPoint.objects.count(),
        SystemFacility.objects.count(),
        Well.objects.filter(well_registration_id__startswith="MER-PWS-").count(),
    )
    call_command("seed_merced_drinking")
    after = (
        SampleResult.objects.count(),
        SamplingPoint.objects.count(),
        SystemFacility.objects.count(),
        Well.objects.filter(well_registration_id__startswith="MER-PWS-").count(),
    )
    assert before == after


@pytest.mark.django_db
def test_flush_removes_the_system_but_keeps_the_vocabulary(seeded):
    """Analytes are shared reference data owned by seed_drinking, not demo rows."""
    from drinking.models import Analyte

    analytes_before = Analyte.objects.count()
    assert analytes_before > 0

    call_command("seed_merced_drinking", flush=True)

    assert not WaterSystem.objects.filter(pwsid=PWSID).exists()
    assert not SampleResult.objects.exists()
    assert not Well.objects.filter(
        well_registration_id__startswith="MER-PWS-"
    ).exists()
    assert Analyte.objects.count() == analytes_before
