# SPDX-License-Identifier: AGPL-3.0-or-later
"""The identity policy and the scan that reads it, as build-failing tests.

Production served four real water-district names on invented accounting data for
three days, beneath its own honesty page promising the demonstration "names no
real water district at all", and nothing in this repository could have noticed.
`data/demo/identity_policy.json` plus `core/management/commands/scan_demo_identity.py`
are the thing that notices. These tests are what keep them honest.

**The protected half is the load-bearing one, and one test here exists only to
prove it.** `Merced Irrigation District` is banned while `Merced River`,
`Merced Subbasin` and `CITY OF MERCED` are real published record that must never
be flagged. The obvious wrong policy — ban the token `Merced` — would flag the
entire demonstration, and `test_protected_half_is_load_bearing` is the executable
form of that ruling: the same widened policy passes with the protected half and
fails without it.

**Why the drift test reads committed FILES and not the test database.** The
pytest database is empty, so "no banned name in the demo" is vacuously true here
and would ship a green gate that checks nothing. What is checkable in a unit test
is the committed fixture data the demo is seeded FROM, so that is what
`test_no_banned_value_in_committed_demo_data` reads.
"""

import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.modules import is_enabled
from tests.factories import FlowlineFactory, ParcelFactory, WellFactory

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "data" / "demo" / "identity_policy.json"

#: The committed data the demo is seeded from. Prose (`.md`) is deliberately
#: excluded: `data/merced/README.md` describes MID's real canal network as basin
#: character, which 97-02-SUMMARY.md rules as one of the eight justified
#: survivors of the Phase 97 sweep. A fixture is different — a name in a
#: `.geojson` or `.json` becomes a row somebody reads on screen.
SEEDED_DATA_SUFFIXES = {".json", ".geojson", ".csv"}


@pytest.fixture
def policy():
    return json.loads(POLICY_PATH.read_text())


def write_policy(tmp_path, data, name="policy.json"):
    """Write a fixture policy and return its path, for `--policy`."""
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return str(path)


# ---------------------------------------------------------------------------
# 1. Policy shape
# ---------------------------------------------------------------------------
def test_both_halves_are_present_and_non_empty(policy):
    """An empty half is a policy that lies.

    Without `banned` the scan checks nothing and every run is a green light.
    Without `protected` it flags the Merced River, the Merced Subbasin and the
    City of Merced's real laboratory data — and a tripwire that cries wolf is
    one people learn to ignore.
    """
    assert policy["banned"], "the banned half is empty — the scan would check nothing"
    assert policy["protected"], "the protected half is empty — the scan would flag real geography"


@pytest.mark.parametrize("half", ["banned", "protected"])
def test_every_entry_carries_a_non_empty_reason(policy, half):
    """A rule nobody can evaluate later is a rule that gets deleted.

    Every entry states why it is on the list, so the next person who trips over
    a name can decide whether it still belongs there instead of guessing.
    """
    missing = [e.get("value") for e in policy[half] if not str(e.get("reason", "")).strip()]
    assert not missing, f"{half} entries with no reason: {missing}"


@pytest.mark.parametrize("half", ["banned", "protected"])
def test_every_entry_carries_a_scope(policy, half):
    """Scope is where the propagation analysis measured the value.

    For a global banned entry it is metadata, not a filter — but an entry with
    no scope at all records nothing about where the defect was actually seen.
    """
    missing = [e.get("value") for e in policy[half] if not e.get("scope")]
    assert not missing, f"{half} entries with no scope: {missing}"


def test_an_entry_with_an_empty_reason_fails_the_scan(tmp_path):
    """The reason requirement is enforced by the command, not only by this file.

    A policy edited on a server, or by a future session that never runs pytest,
    still cannot ship a reasonless rule.
    """
    bad = {
        "banned": [{"value": "Merced Irrigation District", "reason": "", "scope": ["wells_well.notes"]}],
        "protected": [{"value": "CITY OF MERCED", "reason": "real utility", "scope": ["wells_well.owner_name"]}],
    }
    with pytest.raises(CommandError, match="has no reason"):
        call_command("scan_demo_identity", policy=write_policy(tmp_path, bad))


def test_the_two_deliberate_exclusions_are_documented_not_silent(policy):
    """`Diversion Canal Growers` and `Bottomlands Cattle Co.` are NOT banned.

    97-01-NAMES.md rules both as non-defects: the first is a generic invented
    name merely aligned to the seed (and banning it would collide with the
    protected real `Diversion Canal`), the second was simply stale. Omitting
    them silently would read as an oversight to the next person auditing the
    list against the artifact.
    """
    banned_values = {e["value"] for e in policy["banned"]}
    notes = " ".join(policy.get("notes", []))
    for name in ("Diversion Canal Growers", "Bottomlands Cattle Co."):
        assert name not in banned_values, f"{name} is a documented exclusion, not a banned value"
        assert name in notes, f"{name} is excluded but not documented in notes"


# ---------------------------------------------------------------------------
# 2. The scan catches a planted name
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not is_enabled("surface"), reason="surface module is not enabled")
def test_scan_catches_a_real_district_on_an_invented_water_right():
    """This is the defect that shipped: a real district holding an invented right.

    The failure must name the table, the column, the primary key and the value —
    the three facts an operator needs to fix it without a second query.
    """
    from tests.factories import WaterRightFactory

    right = WaterRightFactory(holder_name="Merced Irrigation District")

    with pytest.raises(CommandError) as exc:
        call_command("scan_demo_identity")

    message = str(exc.value)
    assert "surface_waterright" in message
    assert "holder_name" in message
    assert f"pk={right.pk}" in message
    assert "Merced Irrigation District" in message


def test_clean_database_passes(capsys):
    """No findings means exit 0 and a one-line all-clear, not silence."""
    call_command("scan_demo_identity")
    assert "Identity scan PASSED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 3. The protected half suppresses what it must
# ---------------------------------------------------------------------------
def test_real_geography_and_the_real_utility_are_never_flagged():
    """The Merced River and CITY OF MERCED are real published record.

    The river is USGS geography every point of diversion is placed on, and the
    utility carries genuine EPA and State Water Board laboratory results under
    its own name. If the committed policy ever starts flagging either, the
    03:15 tripwire fires on the demonstration working correctly.
    """
    FlowlineFactory(name="Merced River")
    WellFactory(owner_name="CITY OF MERCED")

    call_command("scan_demo_identity")  # no CommandError == zero violations


def test_protected_half_is_load_bearing(tmp_path):
    """Delete the protected half and the same policy starts flagging the river.

    This is the test that would have caught a policy banning the token `Merced`
    outright. It runs one widened policy twice — with the protected half and
    without it — so the only variable is the half under test.
    """
    FlowlineFactory(name="Merced River")
    WellFactory(owner_name="CITY OF MERCED")

    widened_banned = [
        {
            "value": "Merced",
            "reason": "deliberately over-broad, to prove the protected half suppresses it",
            "scope": ["surface_waterright.holder_name"],
        }
    ]
    protected = [
        {
            "value": "Merced River",
            "reason": "real river, real published USGS geography",
            "scope": ["geography_flowline.name"],
        },
        {
            "value": "CITY OF MERCED",
            "reason": "real utility, real published laboratory results",
            "scope": ["wells_well.owner_name"],
        },
    ]

    with_protection = write_policy(
        tmp_path, {"banned": widened_banned, "protected": protected}, "with.json"
    )
    call_command("scan_demo_identity", policy=with_protection)  # passes

    without_protection = write_policy(
        tmp_path,
        {
            "banned": widened_banned,
            "protected": [
                {
                    "value": "Something Else Entirely",
                    "reason": "a non-empty protected half that covers nothing here",
                    "scope": ["parcels_parcel.notes"],
                }
            ],
        },
        "without.json",
    )
    with pytest.raises(CommandError) as exc:
        call_command("scan_demo_identity", policy=without_protection)

    message = str(exc.value)
    assert "geography_flowline" in message
    assert "wells_well" in message


# ---------------------------------------------------------------------------
# 4. A scoped entry stays in its scope
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not is_enabled("surface"), reason="surface module is not enabled")
def test_scoped_entry_fires_inside_its_scope():
    """`MID ` is Merced Irrigation District's abbreviation on a diversion name.

    It produced `MID Atwater Canal Headgate`, and 55 parcel-ledger descriptions
    were composed from that string — so this one prefix is worth its own rule.
    """
    from tests.factories import PointOfDiversionFactory

    pod = PointOfDiversionFactory(name="MID Atwater Canal Headgate")

    with pytest.raises(CommandError) as exc:
        call_command("scan_demo_identity")

    message = str(exc.value)
    assert "surface_pointofdiversion" in message
    assert f"pk={pod.pk}" in message


def test_scoped_entry_does_not_fire_on_unrelated_prose():
    """A bare three-letter token matched globally would fire on ordinary prose.

    That is the whole reason `MID ` is `"match": "scoped"`. A well note reading
    "MID range service interval" contains the string and is not a defect; a
    tripwire that goes red on it is one people learn to ignore.
    """
    WellFactory(notes="Serviced at the MID range interval, no issues found.")

    call_command("scan_demo_identity")  # no CommandError == not flagged


# ---------------------------------------------------------------------------
# 5. An out-of-scope global hit is still reported
# ---------------------------------------------------------------------------
def test_out_of_scope_global_hit_is_reported_and_flagged():
    """Scope is metadata for a global entry, never a filter.

    A real district name is wrong in ANY column. If scope filtered, moving the
    name one column sideways would hide it — so a hit outside the recorded scope
    is reported LOUDER, marked out-of-scope, not quieter.
    """
    well = WellFactory(notes="Operated under agreement with Merced Irrigation District.")

    with pytest.raises(CommandError) as exc:
        call_command("scan_demo_identity")

    message = str(exc.value)
    assert "wells_well" in message
    assert "notes" in message
    assert f"pk={well.pk}" in message
    assert "OUT OF SCOPE" in message


def test_findings_are_machine_readable(capsys):
    """102-02 builds its alert body from --json, so the findings must survive there.

    `--json` still exits non-zero: the JSON on stdout is the payload and the
    exit status is the signal, so a shell hook can decide whether to alert
    without parsing anything.
    """
    ParcelFactory(owner_name="Turner Island Farms LLC")

    with pytest.raises(CommandError):
        call_command("scan_demo_identity", as_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload["violations"] == 1
    finding = payload["findings"][0]
    assert finding["table"] == "parcels_parcel"
    assert finding["column"] == "owner_name"
    assert finding["matched"] == "Turner Island Farms LLC"
    assert finding["out_of_scope"] is False
    assert finding["reason"]


# ---------------------------------------------------------------------------
# 6. The policy and the seed must not drift apart
# ---------------------------------------------------------------------------
def test_no_banned_value_in_committed_demo_data(policy):
    """A banned name in the committed fixtures becomes a row somebody reads.

    The harmless direction of drift is a banned entry naming something the demo
    no longer contains. The defect is the reverse, and this is what catches it
    on the commit that introduces it rather than on the night the tripwire fires.
    """
    banned = [e["value"] for e in policy["banned"]]
    offenders = []
    for path in sorted((REPO_ROOT / "data").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SEEDED_DATA_SUFFIXES:
            continue
        if path == POLICY_PATH:
            continue
        text = path.read_text(errors="ignore").lower()
        for value in banned:
            if value.lower() in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {value!r}")

    assert not offenders, "banned names in committed demo data:\n  " + "\n  ".join(offenders)


def test_scan_reads_the_committed_policy_by_default(capsys):
    """The default path is the committed policy, not whatever a caller passes.

    102-02 wires this command into the 03:15 reset and into CI with no
    `--policy` argument, so the default is the thing both tripwires actually use.
    """
    call_command("scan_demo_identity")
    out = capsys.readouterr().out
    assert f"{len(json.loads(POLICY_PATH.read_text())['banned'])} banned" in out
