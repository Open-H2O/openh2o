# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-095: `seed_merced` could not complete on any DEBUG=False deployment.

The bug had two halves and needed two fixes, because they fail in different
situations and either one alone leaves a documented path broken.

**The passthrough.** `seed_merced` runs eleven sub-commands, and step 4
(`seed_merced_operations`) refuses to run when `DEBUG=False` unless given
`--allow-prod-clobber` — it deletes and regenerates parcel and well geometry.
`seed_merced` defined no `add_arguments` at all, so the flag had nowhere to
enter. `make fresh` therefore died at step 3 of 10 *after* destroying the
volumes, leaving a database holding only the boundary, the GSA zones and the
reference data.

**The emptiness escape.** The guard exists to protect hand-adjusted QGIS
geometry. On a first-time install there is none, and DEPLOY.md §9 and
docs/AI-OPERATOR-GUIDE.md Phase 3 both tell a production operator to run
`seed_merced` verbatim — the platform's whole "point an AI at a $15/mo VPS"
premise. A guard that fires over an empty database blocks that path while
protecting nothing.

The tests below pin both halves, plus the tripwire that keeps
`ACCEPTS_PROD_CLOBBER` honest.

`_check_base_layer` and the seeding methods are patched out in the guard tests
on purpose. The subject here is the refusal decision, not the seed: running the
real thing would need the full boundary + flowline base layer, and a test that
hauls that in to observe one `if` would fail for reasons that have nothing to do
with what it claims to prove.
"""
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands import seed_merced as seed_merced_module
from core.management.commands import seed_merced_operations as operations_module

pytestmark = pytest.mark.django_db

OPERATIONS = "seed_merced_operations"


def _run_operations(**options):
    """Run the operations command with everything but the guard patched out."""
    out = StringIO()
    with mock.patch.object(
        operations_module.Command, "_check_base_layer", return_value=mock.sentinel.lower
    ), mock.patch.object(
        operations_module.Command, "_seed"
    ) as seed, mock.patch.object(
        operations_module.Command, "_flush"
    ) as flush:
        call_command(OPERATIONS, stdout=out, **options)
    return out.getvalue(), seed, flush


# ---------------------------------------------------------------------------
# The emptiness escape — a first-time production seed is not a clobber.
# ---------------------------------------------------------------------------

def test_first_time_production_seed_is_allowed_because_there_is_nothing_to_clobber(
    settings,
):
    settings.DEBUG = False

    output, seed, _flush = _run_operations()

    seed.assert_called_once()
    assert "nothing to clobber" in output


def test_production_guard_still_fires_once_merced_parcels_exist(settings):
    """One MER- parcel is enough. The guard protects rows, not an empty schema."""
    from tests import factories

    settings.DEBUG = False
    factories.ParcelFactory(parcel_number="MER-APN-000001")

    with pytest.raises(CommandError) as exc:
        _run_operations()

    message = str(exc.value)
    assert "Refusing to run the full Merced operations seed" in message
    assert "--allow-prod-clobber" in message
    # The refusal says how much is at stake, so an operator can tell a real demo
    # from a stray row before deciding to override it.
    assert "1 MER- demo rows" in message


def test_production_guard_also_counts_merced_water_rights(settings):
    """
    A water right alone trips it, and that is what makes the message TRUE.

    `_flush` deletes `MER-WR-` rights and every POD hanging off them, and `_seed`
    rewrites them through `update_or_create` even without `--flush`. Counting
    only parcels and wells would let the command announce there was nothing at
    stake and then rebuild a right anyway — the precise silent loss the guard
    exists to prevent.
    """
    from surface.models import WaterRight, WaterRightType

    settings.DEBUG = False
    right_type = WaterRightType.objects.create(
        code="POST14", name="Post-1914 Appropriative"
    )
    WaterRight.objects.create(
        right_id="MER-WR-999-DEMO",
        right_type=right_type,
        holder_name="Guard Test Holder",
        status="active",
    )

    with pytest.raises(CommandError) as exc:
        _run_operations()

    assert "1 MER- demo rows" in str(exc.value)


def test_production_guard_also_counts_merced_wells(settings):
    """A well alone trips it too — `_flush` deletes MER-W- rows just as happily."""
    from tests import factories

    settings.DEBUG = False
    well_type = factories.WellTypeFactory(name="Guard Well Type")
    factories.WellFactory(well_registration_id="MER-W-0001", well_type=well_type)

    with pytest.raises(CommandError):
        _run_operations()


def test_an_agencys_own_parcels_do_not_trip_the_guard(settings):
    """
    The count is scoped to the rows the destructive path actually touches.

    A deployment carrying an agency's real parcels under their own numbering has
    no MER- rows, and the Merced seed neither deletes nor rewrites theirs — so
    running the demo seed there is safe, and refusing would be a false positive.
    """
    from tests import factories

    settings.DEBUG = False
    factories.ParcelFactory(parcel_number="APN-042-110-007")

    _output, seed, _flush = _run_operations()

    seed.assert_called_once()


def test_the_override_still_works_over_existing_rows(settings):
    from tests import factories

    settings.DEBUG = False
    factories.ParcelFactory(parcel_number="MER-APN-000001")

    _output, seed, _flush = _run_operations(allow_prod_clobber=True)

    seed.assert_called_once()


def test_debug_deployments_are_untouched_by_any_of_this(settings):
    from tests import factories

    settings.DEBUG = True
    factories.ParcelFactory(parcel_number="MER-APN-000001")

    output, seed, _flush = _run_operations()

    seed.assert_called_once()
    # The "nothing to clobber" line belongs to the production branch only; on a
    # development instance the guard was never consulted, and saying otherwise
    # would teach an operator the wrong thing about where the protection lives.
    assert "nothing to clobber" not in output


def test_journey_only_returns_before_the_guard_is_ever_consulted(settings):
    """
    Pre-existing behaviour, pinned because the guard moved.

    `--journey-only` touches no parcels, so it is safe on a live demo and must
    stay reachable on production without the override.
    """
    settings.DEBUG = False
    with mock.patch.object(
        operations_module.Command, "_check_base_layer", return_value=mock.sentinel.lower
    ), mock.patch.object(
        operations_module.Command, "_seed_diversion_journey"
    ) as journey:
        call_command(OPERATIONS, stdout=StringIO(), journey_only=True)

    journey.assert_called_once()


# ---------------------------------------------------------------------------
# The passthrough — seed_merced can now carry the flag to step 4.
# ---------------------------------------------------------------------------

def test_seed_merced_forwards_the_flag_only_to_the_command_that_accepts_it():
    calls = []

    def record(name, *args, **kwargs):
        kwargs.pop("stdout", None)
        calls.append((name, kwargs))

    with mock.patch.object(seed_merced_module, "call_command", side_effect=record):
        call_command("seed_merced", stdout=StringIO(), allow_prod_clobber=True)

    forwarded = [name for name, kwargs in calls if kwargs.get("allow_prod_clobber")]
    assert forwarded == list(seed_merced_module.ACCEPTS_PROD_CLOBBER)

    # Every step still runs, in the declared order — forwarding a flag must not
    # quietly reshape the sequence.
    assert [name for name, _ in calls] == [cmd for cmd, _ in seed_merced_module.SEQUENCE]


def test_seed_merced_forwards_nothing_when_the_flag_is_absent():
    calls = []

    def record(name, *args, **kwargs):
        kwargs.pop("stdout", None)
        calls.append((name, kwargs))

    with mock.patch.object(seed_merced_module, "call_command", side_effect=record):
        call_command("seed_merced", stdout=StringIO())

    assert not any(kwargs.get("allow_prod_clobber") for _name, kwargs in calls)


def test_forwarding_does_not_mutate_the_declared_sequence():
    """
    The kwargs dicts in SEQUENCE are module-level literals.

    Updating one in place instead of copying it would make the first
    `--allow-prod-clobber` run poison every later `seed_merced` in the same
    process — the flag would silently stay on for the rest of the process's life,
    including a later plain run that must not carry it.

    Stated as an absolute rather than as a before/after comparison, on purpose:
    a before/after snapshot passes vacuously when an EARLIER test in the same
    process already did the poisoning, since both sides then read the mutated
    dict. Measured — that is exactly how this test behaved when the mutation was
    injected, and the defect was caught by a different test instead.
    """
    with mock.patch.object(seed_merced_module, "call_command"):
        call_command("seed_merced", stdout=StringIO(), allow_prod_clobber=True)

    assert not any(
        "allow_prod_clobber" in kwargs for _cmd, kwargs in seed_merced_module.SEQUENCE
    )


# ---------------------------------------------------------------------------
# The tripwire — the declared forwarding list must match the real parsers.
# ---------------------------------------------------------------------------

def test_accepts_prod_clobber_describes_the_real_sub_command_parsers():
    """
    A second list is a second thing to drift.

    Forwarding the flag to a command that does not define it is a `TypeError`
    raised mid-sequence, after earlier steps have already written rows. So the
    declared tuple is checked against what each sub-command's parser actually
    offers, in both directions: a guarded command missing from the tuple would
    silently reinstate ISS-095, and a listed command that dropped its flag would
    break the rebuild it exists to enable.
    """
    from django.core.management import get_commands, load_command_class

    # Resolve each name through the registry rather than assuming `core` owns it:
    # `auto_populate` lives in a different app, and a hardcoded app label would
    # make this tripwire fail for a reason that is not the one it tests.
    registry = get_commands()

    def defines_the_flag(name):
        command = load_command_class(registry[name], name)
        parser = command.create_parser("manage.py", name)
        return any(
            "--allow-prod-clobber" in action.option_strings
            for action in parser._actions
        )

    actual = tuple(
        cmd for cmd, _kwargs in seed_merced_module.SEQUENCE if defines_the_flag(cmd)
    )
    assert actual == seed_merced_module.ACCEPTS_PROD_CLOBBER


def test_every_forwarded_command_is_actually_in_the_sequence():
    """A name that has fallen out of SEQUENCE would forward to nothing at all."""
    sequence_names = {cmd for cmd, _kwargs in seed_merced_module.SEQUENCE}
    assert set(seed_merced_module.ACCEPTS_PROD_CLOBBER) <= sequence_names


# ---------------------------------------------------------------------------
# --skip-auto-populate — the offline run, and the guard that refuses up front.
#
# These live beside the clobber tests because both are about `seed_merced`'s own
# arguments: what the top command accepts, what it forwards, and what it reshapes
# in SEQUENCE. A flag that quietly dropped the wrong step, or that let an offline
# run start with no base layer, would fail deep inside a sub-command with an error
# naming neither the flag nor the fixture.
# ---------------------------------------------------------------------------

LOWER_BOUNDARY = "Merced Subbasin"
CANAL = "Canal"
RIVER = "Channel Line"


def _seed_offline_base_layer(canals=1, rivers=1):
    """The minimum `--skip-auto-populate` is allowed to proceed on."""
    from tests import factories

    boundary = factories.BoundaryFactory(name=LOWER_BOUNDARY)
    for _ in range(canals):
        factories.FlowlineFactory(boundary=boundary, feature_type=CANAL)
    for _ in range(rivers):
        factories.FlowlineFactory(boundary=boundary, feature_type=RIVER)
    return boundary


def _record_sequence(**options):
    """Run seed_merced with every sub-command stubbed; return the names called."""
    calls = []

    def record(name, *args, **kwargs):
        calls.append(name)

    with mock.patch.object(seed_merced_module, "call_command", side_effect=record):
        call_command("seed_merced", stdout=StringIO(), **options)
    return calls


def test_skip_auto_populate_omits_exactly_the_networked_step():
    _seed_offline_base_layer()

    calls = _record_sequence(skip_auto_populate=True)

    assert seed_merced_module.AUTO_POPULATE not in calls
    # Everything else still runs, in the declared order. Skipping one step must
    # not reshape the sequence around it.
    assert calls == [
        cmd
        for cmd, _kwargs in seed_merced_module.SEQUENCE
        if cmd != seed_merced_module.AUTO_POPULATE
    ]


def test_auto_populate_still_runs_when_the_flag_is_absent():
    calls = _record_sequence()

    assert seed_merced_module.AUTO_POPULATE in calls
    assert calls == [cmd for cmd, _kwargs in seed_merced_module.SEQUENCE]


def test_offline_run_refuses_when_the_boundary_does_not_exist_yet():
    with pytest.raises(CommandError) as exc:
        _record_sequence(skip_auto_populate=True)

    message = str(exc.value)
    assert seed_merced_module.FLOWLINES_FIXTURE in message
    assert "--skip-auto-populate" in message


def test_offline_run_refuses_before_writing_a_single_row():
    """
    The point of guarding up front rather than letting step 4 fail.

    Without this the command writes the boundary and the GSA zones, THEN dies —
    leaving a half-seeded database and an error that names neither the flag nor
    the fixture.
    """
    called = []

    def record(name, *args, **kwargs):
        called.append(name)

    with mock.patch.object(seed_merced_module, "call_command", side_effect=record):
        with pytest.raises(CommandError):
            call_command("seed_merced", stdout=StringIO(), skip_auto_populate=True)

    assert called == []


def test_offline_run_refuses_when_the_river_type_is_missing():
    """
    Canals alone are not enough, and this is the case a row COUNT would miss.

    `seed_merced_operations` guards on both a "Canal" and a "Channel Line"
    flowline separately, so a fixture carrying only canals passes any
    "are there flowlines?" check and still fails three steps later.
    """
    _seed_offline_base_layer(canals=3, rivers=0)

    with pytest.raises(CommandError) as exc:
        _record_sequence(skip_auto_populate=True)

    assert seed_merced_module.FLOWLINES_FIXTURE in str(exc.value)


def test_offline_run_refuses_when_the_canal_type_is_missing():
    _seed_offline_base_layer(canals=0, rivers=3)

    with pytest.raises(CommandError) as exc:
        _record_sequence(skip_auto_populate=True)

    assert seed_merced_module.FLOWLINES_FIXTURE in str(exc.value)


def test_flowlines_on_a_different_boundary_do_not_satisfy_the_guard():
    """
    The guard is scoped to the Merced Subbasin, not to the flowline table.

    A deployment carrying another agency's hydrography would otherwise pass the
    check with zero Merced flowlines loaded — the guard would be measuring the
    wrong basin.
    """
    from tests import factories

    other = factories.BoundaryFactory(name="Some Other Basin")
    factories.FlowlineFactory(boundary=other, feature_type=CANAL)
    factories.FlowlineFactory(boundary=other, feature_type=RIVER)

    with pytest.raises(CommandError) as exc:
        _record_sequence(skip_auto_populate=True)

    assert seed_merced_module.FLOWLINES_FIXTURE in str(exc.value)


def test_the_committed_fixture_actually_satisfies_the_guard():
    """
    The fixture and the guard must describe each other, or CI breaks on a push
    that touched neither.

    Read from the committed file rather than from a factory: a factory proves
    the guard's logic, and this proves the artifact CI actually loads carries
    what the guard demands. `memory/feedback_verify_manifest_matches_disk.md` is
    the reason — a missing entry is silent unless something checks.
    """
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    rows = json.loads((repo_root / seed_merced_module.FLOWLINES_FIXTURE).read_text())

    types = {r["fields"]["feature_type"] for r in rows}
    assert CANAL in types
    assert RIVER in types
    # The boundary is referenced by natural key, never by pk: it is pk 1 on
    # staging and pk 6 on production, so a pk would attach these rows to a
    # different boundary on every deployment.
    assert {tuple(r["fields"]["boundary"]) for r in rows} == {(LOWER_BOUNDARY,)}
