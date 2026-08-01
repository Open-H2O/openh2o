# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for data/demo/expected_shape.json — the written-down shape of the
demonstration that gate 2 of `scripts/verify-candidate.sh` compares a rebuilt
candidate against.

**The point of these tests is that a shape gate can fail silently.** Gate 2
compares model labels as strings. A typo'd label describes a model that does not
exist, so the gate checks nothing for it and still reports PASS — a gate that
has only ever been green and is in fact blind. Resolving every label through
Django's live app registry is the only thing that catches that, and it is the
same discipline `scan_demo_identity` and `demo_row_counts` already use: derive
from the registry, never from a hand-kept list and never from grep.

The reason field is load-bearing for the same purpose the identity policy's is:
a number nobody can evaluate later is a number the next person deletes or
"fixes" when the build fails, rather than asking why it moved.
"""

import json
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings

SHAPE_PATH = Path(settings.BASE_DIR) / "data" / "demo" / "expected_shape.json"


@pytest.fixture(scope="module")
def shape():
    assert SHAPE_PATH.exists(), f"expected shape file missing: {SHAPE_PATH}"
    return json.loads(SHAPE_PATH.read_text())


@pytest.fixture(scope="module")
def entries(shape):
    return shape["models"]


def test_file_parses_and_has_models(shape):
    """A malformed file would make gate 2 refuse; catch it here instead."""
    assert isinstance(shape.get("models"), dict)
    assert shape["models"], "the shape file describes no models at all"


def test_unlisted_model_policy_is_fail(shape):
    """A model in the candidate that nobody wrote down is drift.

    Letting it pass silently is how a whole new domain ships unverified — which
    is exactly how the drinking-water module reached production empty and
    nothing in this repository could tell.
    """
    assert shape.get("unlisted_model") == "fail"


def test_every_label_resolves_through_the_app_registry(entries):
    """A typo'd label is a gate that silently checks nothing.

    This is the test that matters most in this file.
    """
    unresolvable = []
    for label in entries:
        try:
            apps.get_model(label)
        except (LookupError, ValueError) as exc:
            unresolvable.append(f"{label}: {exc}")
    assert not unresolvable, (
        "shape file names models that do not exist — gate 2 checks NOTHING for "
        "these and still reports PASS:\n  " + "\n  ".join(unresolvable)
    )


def test_every_entry_has_expected_tolerance_and_reason(entries):
    problems = []
    for label, spec in entries.items():
        if not isinstance(spec.get("expected"), int) or spec["expected"] < 0:
            problems.append(f"{label}: 'expected' must be a non-negative int")
        if not isinstance(spec.get("tolerance"), int) or spec["tolerance"] < 0:
            problems.append(f"{label}: 'tolerance' must be a non-negative int")
        if not str(spec.get("reason", "")).strip():
            problems.append(f"{label}: no reason")
    assert not problems, "\n  ".join(problems)


def test_non_zero_tolerances_carry_a_real_reason(entries):
    """Zero is the default and should be the answer for almost everything.

    The rebuild has no randomness and makes no network calls, so a count that
    moves is a change somebody made. A tolerance that lets a number drift has to
    justify itself in a sentence, not a token — the failure mode is a future
    author widening a band to make a red build go green.
    """
    thin = [
        f"{label}: tolerance {spec['tolerance']} with reason {spec['reason']!r}"
        for label, spec in entries.items()
        if spec["tolerance"] != 0 and len(str(spec["reason"]).split()) < 8
    ]
    assert not thin, (
        "a non-zero tolerance must name what varies and why:\n  " + "\n  ".join(thin)
    )


def test_reasons_are_sentences_not_placeholders(entries):
    """Guard against the entry that exists only to make the gate pass."""
    placeholder = [
        label
        for label, spec in entries.items()
        if len(str(spec["reason"]).split()) < 4
    ]
    assert not placeholder, (
        "these entries have a reason too short to evaluate later:\n  "
        + "\n  ".join(placeholder)
    )


def test_core_user_is_pinned_to_zero(entries):
    """The one entry whose value is the whole point of the milestone.

    A golden carrying a deployment's admin account is the exact mechanism by
    which staging admin rows once reached production. If a future edit ever
    relaxes this, the build should fail here first.
    """
    spec = entries["core.User"]
    assert spec["expected"] == 0 and spec["tolerance"] == 0, (
        "core.User must be pinned to exactly 0. A rebuilt candidate that carries "
        "user rows has captured a deployment's accounts into an artifact that "
        "ships to production."
    )


def test_every_first_party_model_is_described(entries):
    """Coverage runs both ways: the file must not fall behind the codebase.

    Gate 2 catches an unlisted model at verification time, but that is a
    production-adjacent moment on a server. Catching it in the test suite is
    where a person can still do something cheap about it.
    """
    live = set()
    for model in apps.get_models():
        if model._meta.proxy:
            continue
        package = model._meta.app_config.name
        if package.startswith("django.") or package.startswith("allauth"):
            continue
        live.add(model._meta.label)

    undescribed = sorted(live - set(entries))
    assert not undescribed, (
        "these first-party models exist but are not in the shape file. Add each "
        "with an expected count and a reason saying what determines it:\n  "
        + "\n  ".join(undescribed)
    )
