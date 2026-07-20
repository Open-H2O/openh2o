# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for mapping an Envirofacts payload onto the drinking models (Phase 79,
plan 02).

Every payload below is a real captured response — the fixtures 79-01 pulled from
the live service for Bakman Water Company (CA1010001), Fresno. Nothing here is
invented, including the two awkward facilities: ``DST`` (a non-numeric state
key) and ``CA1010001001`` (a facility EPA carries with a NULL state key), both
of which are genuinely in EPA's data for this system.

The mapping functions are pure — dict in, model kwargs out, no ORM and no
network — so most of this file needs no database at all. Only the commit tests
touch the DB, and what they are really guarding is idempotency: onboarding the
same system twice must not double its facilities, and must not erase an
operator's well link.
"""

import json
from pathlib import Path

import pytest
from django.db import DataError

from drinking import envirofacts_mapping as mapping
from drinking.models import SystemFacility, WaterSystem
from tests.factories import WellFactory

FIXTURES = Path(__file__).resolve().parent.parent / "drinking" / "fixtures"

PWSID = "CA1010001"


def _fixture(name):
    return json.loads((FIXTURES / f"envirofacts_{name}.json").read_text())


@pytest.fixture
def system_payload():
    return _fixture("water_system")[0]


@pytest.fixture
def facility_payloads():
    return _fixture("facilities")


@pytest.fixture
def well_10(facility_payloads):
    """WELL 10 - RAW: the facility the whole PS Code question turns on."""
    return next(f for f in facility_payloads if f["facility_id"] == "14042")


@pytest.fixture
def distribution_system(facility_payloads):
    """The facility whose state key is the non-numeric string ``DST``."""
    return next(f for f in facility_payloads if f["state_facility_id"] == "DST")


@pytest.fixture
def keyless_facility(facility_payloads):
    """The facility EPA carries with a NULL ``state_facility_id``."""
    return next(f for f in facility_payloads if f["state_facility_id"] is None)


# ── The mapping the milestone's acceptance gate depends on ──────────────────


def test_facility_id_is_the_state_id_not_epas(well_10):
    """THE critical assertion of Phase 79. Do not "simplify" this away.

    EPA returns two facility identifiers for the same physical facility, and
    DDW's real published PS Codes are built from the STATE one:

        EPA facility_id       14042
        state_facility_id     010      ← DDW's PS Code is CA1010001_010_010

    Verified against California's live SDWIS4.zip export. Mapping EPA's id here
    would make Phase 80's wizard compose CA1010001_14042_001, which matches no
    row of any genuine lab file — and the failure would only surface after both
    phases were built. See 79-RESEARCH.md § ps_code_resolution.
    """
    mapped = mapping.map_facility(well_10)

    assert mapped["facility_id"] == "010"
    assert mapped["epa_facility_id"] == "14042"


def test_non_numeric_facility_key_round_trips_unchanged(distribution_system):
    """``DST`` is real and live — it carries CA1010001_DST_900 and
    CA1010001_DST_LCR in the state export. Never coerce, pad, or sort as int."""
    mapped = mapping.map_facility(distribution_system)

    assert mapped["facility_id"] == "DST"
    assert mapped["epa_facility_id"] == "25984"


def test_null_state_id_raises_rather_than_writing_a_blank_key(keyless_facility):
    """A facility with no state key cannot participate in a PS Code, so it must
    never be written with an empty ``facility_id`` — that row would silently
    collide with the next keyless facility on the unique_together."""
    with pytest.raises(mapping.UnmappableFacility) as exc:
        mapping.map_facility(keyless_facility)

    # The message has to name EPA's id, because that is the only handle an
    # operator has for a facility that by definition has no state key.
    assert "CA1010001001" in str(exc.value)


# ── Y/N strings are not booleans ────────────────────────────────────────────


def test_n_string_maps_to_false(system_payload):
    """The one a naive implementation fails: bool("N") is True, so a direct
    assignment sets every flag on every system in the country."""
    assert system_payload["is_wholesaler_ind"] == "N"

    assert mapping.map_water_system(system_payload)["is_wholesaler"] is False


def test_y_string_maps_to_true(system_payload, well_10):
    payload = dict(system_payload, is_school_or_daycare_ind="Y")

    assert mapping.map_water_system(payload)["is_school_or_daycare"] is True
    assert mapping.map_facility(well_10)["is_source"] is True


# ── Coded fields land in the published vocabularies ─────────────────────────


def test_system_codes_land_in_published_vocabularies(system_payload):
    mapped = mapping.map_water_system(system_payload)

    assert mapped["pwsid"] == "CA1010001"
    assert mapped["name"] == "BAKMAN WATER COMPANY"
    assert mapped["pws_type"] == "CWS"
    assert mapped["owner_type"] == "P"
    assert mapped["primary_source_code"] == "GW"
    assert mapped["activity_status"] == "A"


def test_facility_codes_land_in_published_vocabularies(well_10):
    mapped = mapping.map_facility(well_10)

    assert mapped["name"] == "WELL 10 - RAW"
    assert mapped["facility_type"] == "WL"
    assert mapped["water_type"] == "GW"
    assert mapped["availability"] == "P"
    assert mapped["activity_status"] == "A"


def test_every_real_facility_maps_to_published_codes(facility_payloads):
    """The measured distribution for this system — WL x20, TP x14, CH x1, DS x1,
    activity A x25 / I x11 — is fully covered by the transcribed code lists. A
    warning here means EPA published a code the model has never seen."""
    warnings = []
    for payload in facility_payloads:
        if payload["state_facility_id"] is None:
            continue
        mapping.map_facility(payload, warnings=warnings)

    assert warnings == []


def test_unknown_code_is_reported_not_stored(well_10):
    """EPA sending something new must be surfaced to the operator, never
    written into a field whose choices the value violates."""
    payload = dict(well_10, facility_type_code="ZZ")
    warnings = []

    mapped = mapping.map_facility(payload, warnings=warnings)

    assert "facility_type" not in mapped
    assert any("ZZ" in w for w in warnings)


# ── Aggregates must not be split or guessed ─────────────────────────────────


def test_population_aggregate_is_never_split(system_payload):
    """EPA sends ONE population_served_count (17393). The model has a 3-way
    split. Putting the aggregate into the residential field would silently
    misattribute transient population as residents — exactly the quiet wrongness
    "prepare, never determine" exists to prevent."""
    assert system_payload["population_served_count"] == 17393

    mapped = mapping.map_water_system(system_payload)

    assert mapped.get("population_residential") is None
    assert mapped.get("population_non_transient") is None
    assert mapped.get("population_transient") is None


def test_connection_aggregate_is_never_split(system_payload):
    assert system_payload["service_connections_count"] == 2675

    mapped = mapping.map_water_system(system_payload)

    for field in (
        "connections_agricultural",
        "connections_combined",
        "connections_commercial",
        "connections_industrial",
        "connections_residential",
    ):
        assert mapped.get(field) is None


# ── Mailing address only ────────────────────────────────────────────────────


def test_mailing_address_is_mapped(system_payload):
    mapped = mapping.map_water_system(system_payload)

    assert mapped["mailing_address_line1"] == "P.O. BOX 8271"
    assert mapped["mailing_address_line2"] == ""
    assert mapped["mailing_city"] == "FRESNO"
    assert mapped["mailing_state"] == "CA"
    assert mapped["mailing_zip"] == "93747"


def test_personal_contact_details_are_dropped(system_payload):
    """Brent's scope call, 2026-07-19: EPA's admin block is a named
    individual's contact details. Address only; nothing else is carried."""
    assert system_payload["email_addr"]  # EPA really does send it
    assert system_payload["phone_number"]

    mapped = mapping.map_water_system(system_payload)

    banned = ("email", "phone", "fax", "admin", "org_name")
    leaked = [k for k in mapped if any(term in k.lower() for term in banned)]
    assert leaked == []


# ── Inactive systems map, with a surfaceable warning ────────────────────────


def test_inactive_system_maps_cleanly_and_warns(system_payload):
    """An operator may legitimately be researching a deactivated system, so this
    warns rather than blocks."""
    payload = dict(
        system_payload,
        pws_activity_code="I",
        pws_deactivation_date="2013-07-01 00:00:00",
    )
    warnings = []

    mapped = mapping.map_water_system(payload, warnings=warnings)

    assert mapped["activity_status"] == "I"
    assert any("inactive" in w.lower() for w in warnings)


# ── Geography is a hint, not a model ────────────────────────────────────────


def test_map_geography_returns_display_strings():
    payload = _fixture("geographic_area")[0]

    geo = mapping.map_geography(payload)

    assert geo["county_served"] == "Fresno"
    assert geo["city_served"] == ""
    assert geo["state_served"] == ""


def test_map_geography_tolerates_a_comma_joined_area_type():
    """``area_type_code`` can be "CN,CT", so it is not a single code and this
    function persists nothing — it feeds a review screen."""
    geo = mapping.map_geography(
        {"area_type_code": "CN,CT", "county_served": "Fresno", "city_served": "CLOVIS"}
    )

    assert geo["city_served"] == "CLOVIS"


def test_map_geography_handles_a_missing_record():
    assert mapping.map_geography(None) == {
        "county_served": "",
        "city_served": "",
        "state_served": "",
    }


# ── Purity ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_mapping_functions_touch_no_database(
    system_payload, well_10, django_assert_num_queries
):
    with django_assert_num_queries(0):
        mapping.map_water_system(system_payload)
        mapping.map_facility(well_10)
        mapping.map_geography(None)


# ── Idempotent commit ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_commit_creates_the_system_and_its_facilities(
    system_payload, facility_payloads
):
    result = mapping.commit_system(system_payload, facility_payloads)

    assert WaterSystem.objects.count() == 1
    # 36 in the payload, 1 of which EPA carries with no state key.
    assert SystemFacility.objects.count() == 35
    assert result.created is True
    assert result.facilities_created == 35
    assert len(result.skipped) == 1


@pytest.mark.django_db
def test_commit_reports_the_facility_it_skipped(system_payload, facility_payloads):
    result = mapping.commit_system(system_payload, facility_payloads)

    assert "CA1010001001" in " ".join(result.skipped)


@pytest.mark.django_db
def test_re_running_creates_no_duplicates(system_payload, facility_payloads):
    mapping.commit_system(system_payload, facility_payloads)
    result = mapping.commit_system(system_payload, facility_payloads)

    assert WaterSystem.objects.count() == 1
    assert SystemFacility.objects.count() == 35
    assert result.created is False
    assert result.facilities_created == 0
    assert result.facilities_updated == 35


@pytest.mark.django_db
def test_re_running_updates_a_changed_name_in_place(
    system_payload, facility_payloads, well_10
):
    mapping.commit_system(system_payload, facility_payloads)
    original_pk = SystemFacility.objects.get(facility_id="010").pk

    renamed = [
        dict(f, facility_name="WELL 10 - REHABILITATED")
        if f["facility_id"] == "14042"
        else f
        for f in facility_payloads
    ]
    mapping.commit_system(system_payload, renamed)

    facility = SystemFacility.objects.get(facility_id="010")
    assert facility.pk == original_pk
    assert facility.name == "WELL 10 - REHABILITATED"
    assert SystemFacility.objects.count() == 35


@pytest.mark.django_db
def test_an_operator_well_link_survives_a_re_run(system_payload, facility_payloads):
    """Guards ROADMAP.md:56. ``SystemFacility.well`` is the quality<->quantity
    join and linking one is a deliberate operator act — a federal refresh must
    never write, infer, or clear it. If ``well`` ever appears in the commit's
    ``defaults``, this test is the only thing standing between a re-run and
    silently erasing that operator's work.
    """
    mapping.commit_system(system_payload, facility_payloads)
    facility = SystemFacility.objects.get(facility_id="010")

    well = WellFactory(name="Bakman Well 10")
    facility.well = well
    facility.save(update_fields=["well"])

    mapping.commit_system(system_payload, facility_payloads)

    facility.refresh_from_db()
    assert facility.well_id == well.pk


@pytest.mark.django_db
def test_commit_is_atomic_across_system_and_facilities(system_payload):
    """A facility payload that blows up must not leave a half-onboarded system
    behind for the operator to clean up by hand.

    An over-long state key is a real failure rather than a contrived one: the
    column is varchar(30), so Postgres rejects the write outright — this is not
    the "no state key" case, which is skipped and reported instead of raised.
    """
    oversized = {"facility_id": "1", "state_facility_id": "X" * 40}

    with pytest.raises(DataError):
        mapping.commit_system(system_payload, [oversized])

    assert WaterSystem.objects.count() == 0
