# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.2: the ``add_water_system`` command, and the functions it shares with the page.

All data here is INVENTED or recorded: the water system is the recorded EPA
response for Bakman Water Company (CA1010001) in ``drinking/fixtures``, served by
monkeypatching the three ``drinking.envirofacts`` fetches exactly as
``tests/test_drinking_onboard.py`` does. Nothing reaches the network. The two
"another system" cases use invented systems (CA0000043).

Every sentence a person reads is one named constant per row of
``.planning/phases/152-proven-by-strangers/152-03.2-ROWS.md`` (the Fixed
column), so a re-read row changes one line here.
"""

import json
from io import StringIO
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from drinking import envirofacts
from drinking.models import SystemFacility, WaterSystem
from tests.factories import WaterSystemFactory

FIXTURES = Path(__file__).resolve().parent.parent / "drinking" / "fixtures"
PWSID = "CA1010001"

# -- the rows (Fixed column) -------------------------------------------------
ROW_1 = (
    "Add a water system and its facilities from EPA's Envirofacts records by the "
    "system's PWSID. The Add a water system page saves the same records. When the "
    "PWSID is already on the site, the command updates the system and its "
    "facilities from EPA's record."
)
ROW_2 = "The water system's PWSID, such as CA1234567."
ROW_3 = (
    "Show EPA's record and what the command would save. The command does not save "
    "any record during a dry run."
)
ROW_14 = "[DRY RUN] The command does not save any record."
ROW_15 = "EPA's record for {pwsid}:"
ROW_16_LABELS = (
    "Name", "Status", "System type", "Owner type", "Primary source", "County served",
)
ROW_17 = "Facility {facility_id}: {name}"
ROW_18 = "Left out: {reason}"
ROW_19 = "Note: {note}"
ROW_20 = (
    "OpenH2O would create the water system {pwsid}. OpenH2O would save {n} of the "
    "{total} {facilities} EPA sent."
)
ROW_21 = (
    "OpenH2O would update {pwsid} from EPA's record. OpenH2O would save {n} of the "
    "{total} {facilities} EPA sent."
)
ROW_22 = "OpenH2O added {name} ({pwsid})."
ROW_23 = "OpenH2O updated {name} ({pwsid}) from EPA's record."
ROW_24 = (
    "Of the {total} {facilities} EPA sent, OpenH2O created {c}, updated {u} and "
    "left out {m}."
)
ROW_25 = (
    "Next: add a sampling point with add_sampling_point for each PS Code in your "
    "lab file."
)
ROW_27 = (
    "This site keeps the records of one water system, {name} ({pwsid}). OpenH2O "
    "did not look up {other} or save anything."
)
ROW_28 = (
    "EPA's Envirofacts does not list a water system with the PWSID {pwsid}. Check "
    "the PWSID against the regulator's listing and try again."
)
ROW_29 = (
    "OpenH2O could not get the record for {pwsid} from EPA's Envirofacts service. "
    "Your PWSID may still be correct; try again in a few minutes."
)
ROW_30 = (
    "EPA's Envirofacts service sent an answer OpenH2O cannot read. Your PWSID may "
    "still be correct. Details:"
)


def _fixture(name):
    return json.loads((FIXTURES / f"envirofacts_{name}.json").read_text())


def _flat(text):
    return " ".join(text.split())


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"addsys{n}")
    email = factory.Sequence(lambda n: f"addsys{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def epa(monkeypatch):
    calls = {"system": 0, "facilities": 0, "geography": 0}

    def fake_system(pwsid, refresh=False):
        calls["system"] += 1
        return _fixture("water_system")[0]

    def fake_facilities(pwsid, refresh=False):
        calls["facilities"] += 1
        return _fixture("facilities")

    def fake_geography(pwsid, refresh=False):
        calls["geography"] += 1
        return _fixture("geographic_area")[0]

    monkeypatch.setattr(envirofacts, "fetch_water_system", fake_system)
    monkeypatch.setattr(envirofacts, "fetch_facilities", fake_facilities)
    monkeypatch.setattr(envirofacts, "fetch_geographic_area", fake_geography)
    return calls


def run(*args):
    """Run the command; return its stdout as a list of lines, and the raw text."""
    out = StringIO()
    call_command("add_water_system", *args, stdout=out, stderr=StringIO())
    text = out.getvalue()
    return text, [line.strip() for line in text.splitlines() if line.strip()]


SYSTEM_FIELDS = (
    "name", "activity_status", "pws_type", "owner_type", "primary_source_code",
    "is_wholesaler", "is_school_or_daycare", "population_served_total",
    "service_connections_total", "mailing_address_line1", "mailing_address_line2",
    "mailing_city", "mailing_state", "mailing_zip",
)


def snapshot():
    system = WaterSystem.objects.get(pwsid=PWSID)
    return (
        {f: getattr(system, f) for f in SYSTEM_FIELDS},
        sorted(
            (
                f.facility_id, f.epa_facility_id, f.name, f.facility_type,
                f.activity_status, f.is_source, f.water_type, f.availability,
            )
            for f in system.facilities.all()
        ),
    )


def page_lookup(client):
    return client.post(reverse("drinking:onboard_lookup"), {"pwsid": PWSID})


def page_commit(client):
    page_lookup(client)
    return client.post(reverse("drinking:onboard_commit"))


# -- help lines --------------------------------------------------------------


def test_help_lines_are_the_rows():
    command = load_command_class("drinking", "add_water_system")
    text = _flat(command.create_parser("manage.py", "add_water_system").format_help())
    assert ROW_1 in text  # row 1
    assert ROW_2 in text  # row 2
    assert ROW_3 in text  # row 3


# -- the command and the page write the same rows -----------------------------


def test_the_command_and_the_page_write_the_same_rows(client_in, epa):
    page_commit(client_in)
    from_page = snapshot()
    assert len(from_page[1]) == 35
    WaterSystem.objects.all().delete()
    assert SystemFacility.objects.count() == 0

    run(PWSID)

    assert snapshot() == from_page


# -- dry run -----------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_prints_the_review(client_in, epa):
    ctx = page_lookup(client_in).context
    text, lines = run(PWSID, "--dry-run")

    assert WaterSystem.objects.count() == 0
    assert SystemFacility.objects.count() == 0

    assert lines[0] == ROW_14  # row 14
    i15 = lines.index(ROW_15.format(pwsid=PWSID))  # row 15
    assert i15 > 0
    values = {
        "Name": ctx["name"],
        "Status": ctx["activity_status"],
        "System type": ctx["pws_type"],
        "Owner type": ctx["owner_type"],
        "Primary source": ctx["primary_source"],
        "County served": ctx["geography"]["county_served"],
    }
    for label in ROW_16_LABELS:  # row 16
        line = f"{label}: {values[label]}"
        assert line in lines, line
        assert lines.index(line) > i15

    facility_lines = [line for line in lines if line.startswith("Facility ")]
    assert len(facility_lines) == 35  # row 17
    first = ctx["facilities"][0]
    assert ROW_17.format(facility_id=first["facility_id"], name=first["name"]) in lines

    reason = ctx["skipped"][0]
    assert ROW_18.format(reason=reason) in lines  # row 18
    assert len([line for line in lines if line.startswith("Left out: ")]) == 1

    for note in ctx["warnings"]:  # row 19
        assert ROW_19.format(note=note) in lines

    expected = ROW_20.format(pwsid=PWSID, n=35, total=36, facilities="facilities")
    assert _flat(text).endswith(expected)  # row 20


def test_a_dry_run_on_a_system_on_the_site_says_update(client_in, epa):
    page_commit(client_in)
    before = snapshot()
    text, lines = run(PWSID, "--dry-run")
    expected = ROW_21.format(pwsid=PWSID, n=35, total=36, facilities="facilities")
    assert _flat(text).endswith(expected)  # row 21
    assert snapshot() == before


# -- a run -------------------------------------------------------------------


def test_a_run_on_a_new_system_prints_rows_22_24_and_25_last(epa, db):
    text, lines = run(PWSID)
    name = WaterSystem.objects.get(pwsid=PWSID).name

    r22 = ROW_22.format(name=name, pwsid=PWSID)
    r24 = ROW_24.format(total=36, facilities="facilities", c=35, u=0, m=1)
    assert r22 in lines
    assert r24 in lines
    assert lines.index(r22) < lines.index(r24)
    assert lines[-1] == ROW_25  # row 25
    assert lines.index(r24) < len(lines) - 1


def test_a_second_run_prints_row_23(epa, db):
    run(PWSID)
    name = WaterSystem.objects.get(pwsid=PWSID).name
    text, lines = run(PWSID)
    assert ROW_23.format(name=name, pwsid=PWSID) in lines
    assert (
        ROW_24.format(total=36, facilities="facilities", c=0, u=35, m=1) in lines
    )
    assert lines[-1] == ROW_25
    assert WaterSystem.objects.count() == 1


def test_one_facility_reads_in_the_singular(epa, monkeypatch, db):
    one = [_fixture("facilities")[0]]
    monkeypatch.setattr(envirofacts, "fetch_facilities", lambda pwsid, refresh=False: one)

    text, _ = run(PWSID, "--dry-run")
    assert _flat(text).endswith(
        ROW_20.format(pwsid=PWSID, n=1, total=1, facilities="facility")
    )  # row 26
    _, lines = run(PWSID)
    assert (
        ROW_24.format(total=1, facilities="facility", c=1, u=0, m=0) in lines
    )  # row 26


# -- refusals ----------------------------------------------------------------


def test_another_pwsid_on_a_site_with_a_system_is_refused(epa, db):
    kept = WaterSystemFactory(pwsid="CA0000043", name="Demonstration Water District")
    with pytest.raises(CommandError) as raised:
        run(PWSID)
    assert str(raised.value) == ROW_27.format(
        name=kept.name, pwsid=kept.pwsid, other=PWSID
    )  # row 27
    assert WaterSystem.objects.count() == 1
    assert SystemFacility.objects.count() == 0
    assert epa == {"system": 0, "facilities": 0, "geography": 0}


def test_epa_lists_no_such_system(epa, monkeypatch, db):
    def missing(pwsid, refresh=False):
        raise envirofacts.PwsidNotFound(pwsid)

    monkeypatch.setattr(envirofacts, "fetch_water_system", missing)
    with pytest.raises(CommandError) as raised:
        run(PWSID)
    assert str(raised.value) == ROW_28.format(pwsid=PWSID)  # row 28
    assert WaterSystem.objects.count() == 0


def test_epa_did_not_answer(epa, monkeypatch, db):
    def down(pwsid, refresh=False):
        raise envirofacts.EnvirofactsUnavailable("timed out")

    monkeypatch.setattr(envirofacts, "fetch_water_system", down)
    with pytest.raises(CommandError) as raised:
        run(PWSID)
    assert str(raised.value) == ROW_29.format(pwsid=PWSID)  # row 29
    assert WaterSystem.objects.count() == 0


def test_epa_sent_an_answer_nobody_can_read(epa, monkeypatch, db):
    def garbled(pwsid, refresh=False):
        raise envirofacts.EnvirofactsError("not JSON")

    monkeypatch.setattr(envirofacts, "fetch_water_system", garbled)
    with pytest.raises(CommandError) as raised:
        run(PWSID)
    assert str(raised.value) == f"{ROW_30} not JSON"  # row 30
    assert WaterSystem.objects.count() == 0


# -- the functions moved out of the page's module -----------------------------


def test_system_the_site_keeps_instead_moved_to_onboarding(db):
    from drinking import onboarding

    assert onboarding.system_the_site_keeps_instead(PWSID) is None
    kept = WaterSystemFactory(pwsid="CA0000043")
    assert onboarding.system_the_site_keeps_instead(PWSID) == kept
    assert onboarding.system_the_site_keeps_instead("CA0000043") is None


def test_collect_federal_record_moved_to_onboarding(epa):
    from drinking import onboarding

    collected = onboarding.collect_federal_record(PWSID)
    assert collected["pwsid"] == PWSID
    assert len(collected["facilities"]) == 35
    assert len(collected["skipped"]) == 1
    assert len(collected["facility_rows"]) == 36
    assert {"system_row", "mapped_system", "geography", "warnings"} <= set(collected)
