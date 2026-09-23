# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-05 Task 2 (S2): DWR's method row, Direct or Estimate, and the accuracy
band on every well.

Proven here, each RED against the unfixed tree (quotes in 146-05-EVIDENCE.md):

  1. The data migration derives `dwr_extraction_method` and
     `dwr_direct_or_estimate` once from the legacy `measurement_method` value,
     on each of its four values and on blank (23 CCR 356.2(b)(2); research
     file 05, lines 289-309, DWR's five method rows and the Direct/Estimate
     pairing).
  2. The well page's inline editor sets and clears `dwr_extraction_method`,
     `dwr_direct_or_estimate`, `accuracy_band` and `well_type` (ISS-189: "Well
     type" printed with no editor).
  3. The identity line reads "Extraction: Meters, direct, ±0-5%" when every
     part is set, and "not stated" per part when it is not.

`measurement_method` is kept (the seeds, seven test files and the Merced
audit trail read it); the data migration's `derive_dwr_fields` function is
called directly here, against the live app registry, rather than
reimplemented -- it only calls ``apps.get_model()`` and nothing else in this
migration has changed since, so the live models are the same shape the
migration ran against (the composition rule does not apply: no model here
crosses into a truly-optional module).
"""
import importlib
from urllib.parse import urlencode

import factory
import pytest
from django.apps import apps as live_apps
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings
from django.urls import reverse

from tests.factories import WellFactory, WellTypeFactory
from wells.models import Well

pytestmark = pytest.mark.django_db

#: The shape-4 module list (145-02-EVIDENCE.md's per-shape table): use areas,
#: accounts and wells, no surface water. Matches tests/test_irrigation_method.py.
_SHAPE_4 = (
    "core", "geography", "measurements", "standards", "parcels", "accounting",
    "wells", "datasync", "setup", "infrastructure", "health", "feedback",
)

_derive_dwr_method = importlib.import_module(
    "wells.migrations.0005_derive_dwr_method"
)


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"dwrmethoduser{n}")
    email = factory.Sequence(lambda n: f"dwrmethoduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(_UserFactory())
    return c


def _patch(client, well, field, value):
    """PATCH the inline editor the way the HTMX form does (urlencoded body)."""
    body = urlencode({"field": field, "value": value})
    return client.patch(
        reverse("wells:edit_field", args=[well.pk]),
        data=body,
        content_type="application/x-www-form-urlencoded",
    )


# ---------------------------------------------------------------------------
# 1. The data migration's derivation, on each of the four legacy values and
#    on blank
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy_value, expected_method, expected_type",
    [
        ("certified_meter", "meters", "direct"),
        ("power_conversion", "electrical_records", "estimate"),
        ("et_method", "land_use", "estimate"),
        ("unmetered_estimate", "other", "estimate"),
    ],
)
def test_the_migration_derives_each_legacy_value(
    legacy_value, expected_method, expected_type
):
    well = WellFactory(measurement_method=legacy_value)

    _derive_dwr_method.derive_dwr_fields(live_apps, None)

    well.refresh_from_db()
    assert well.dwr_extraction_method == expected_method
    assert well.dwr_direct_or_estimate == expected_type
    # The plan gives no band derivation from the legacy value -- never a
    # model-spread substitute for one.
    assert well.accuracy_band == ""


def test_the_migration_leaves_a_blank_measurement_method_blank():
    well = WellFactory(measurement_method="")

    _derive_dwr_method.derive_dwr_fields(live_apps, None)

    well.refresh_from_db()
    assert well.dwr_extraction_method == ""
    assert well.dwr_direct_or_estimate == ""
    assert well.accuracy_band == ""


def test_the_reverse_clears_only_what_was_derived():
    derived = WellFactory(measurement_method="certified_meter")
    untouched = WellFactory(measurement_method="")
    _derive_dwr_method.derive_dwr_fields(live_apps, None)

    _derive_dwr_method.clear_dwr_fields(live_apps, None)

    derived.refresh_from_db()
    untouched.refresh_from_db()
    assert derived.dwr_extraction_method == ""
    assert derived.dwr_direct_or_estimate == ""
    assert untouched.dwr_extraction_method == ""


# ---------------------------------------------------------------------------
# 2. The inline editor: the three new fields and well_type (ISS-189)
# ---------------------------------------------------------------------------


def test_editor_sets_dwr_extraction_method(auth_client):
    well = WellFactory()
    resp = _patch(auth_client, well, "dwr_extraction_method", "meters")
    assert resp.status_code == 200
    assert "Meters" in resp.content.decode()
    well.refresh_from_db()
    assert well.dwr_extraction_method == "meters"


def test_editor_sets_dwr_direct_or_estimate(auth_client):
    well = WellFactory()
    resp = _patch(auth_client, well, "dwr_direct_or_estimate", "estimate")
    assert resp.status_code == 200
    assert "Estimate" in resp.content.decode()
    well.refresh_from_db()
    assert well.dwr_direct_or_estimate == "estimate"


def test_editor_sets_and_clears_accuracy_band(auth_client):
    well = WellFactory()
    resp = _patch(auth_client, well, "accuracy_band", "0-5")
    assert resp.status_code == 200
    assert "0-5%" in resp.content.decode()
    well.refresh_from_db()
    assert well.accuracy_band == "0-5"

    resp = _patch(auth_client, well, "accuracy_band", "")
    assert resp.status_code == 200
    well.refresh_from_db()
    assert well.accuracy_band == ""


def test_editor_refuses_an_unknown_accuracy_band(auth_client):
    well = WellFactory()
    resp = _patch(auth_client, well, "accuracy_band", "50-60")
    assert resp.status_code == 400
    well.refresh_from_db()
    assert well.accuracy_band == ""


def test_editor_sets_well_type(auth_client):
    """ISS-189: 'Well type' printed with no editor; `well_type` was not in
    `EDITABLE_FIELDS` and answered 'Invalid field.' 400."""
    well = WellFactory(well_type=None)
    wt = WellTypeFactory(name="Irrigation")

    resp = _patch(auth_client, well, "well_type", str(wt.pk))

    assert resp.status_code == 200
    assert "Irrigation" in resp.content.decode()
    well.refresh_from_db()
    assert well.well_type == wt


def test_editor_clears_well_type(auth_client):
    wt = WellTypeFactory(name="Domestic")
    well = WellFactory(well_type=wt)

    resp = _patch(auth_client, well, "well_type", "")

    assert resp.status_code == 200
    well.refresh_from_db()
    assert well.well_type is None


def test_editor_refuses_a_well_type_that_does_not_exist(auth_client):
    well = WellFactory(well_type=None)
    resp = _patch(auth_client, well, "well_type", "999999")
    assert resp.status_code == 400
    well.refresh_from_db()
    assert well.well_type is None


def test_well_type_editor_offers_get_form_with_choices(auth_client):
    # No `name=` override: `seed_well_types` (Production, Monitoring, Injection,
    # Observation) is committed outside any test's transaction by
    # `test_merced_drinking_seed.py`'s module-scoped `_seeded_once` fixture and
    # outlives it for the rest of the suite, so any of those four names
    # collides here when the full suite runs. `WellTypeFactory`'s own
    # `factory.Sequence` default can't collide with a fixed name.
    well = WellFactory(well_type=None)
    wt = WellTypeFactory()

    resp = auth_client.get(
        reverse("wells:edit_field", args=[well.pk]), {"field": "well_type"}
    )

    assert resp.status_code == 200
    assert wt.name in resp.content.decode()


# ---------------------------------------------------------------------------
# 3. The identity line
# ---------------------------------------------------------------------------


def test_identity_line_reads_every_part_set(auth_client):
    well = WellFactory(
        dwr_extraction_method="meters",
        dwr_direct_or_estimate="direct",
        accuracy_band="0-5",
    )
    body = auth_client.get(reverse("wells:detail", args=[well.pk])).content.decode()
    assert "Extraction: Meters, direct, ±0-5%" in body


# ---------------------------------------------------------------------------
# 4. Shape 4: `wells` on, `surface` off -- these fields carry no cross-module
#    reference (choice fields on Well itself), so nothing here should be
#    gated on `surface`.
# ---------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_SHAPE_4)
def test_shape_4_well_page_shows_the_three_editors_and_well_type(auth_client):
    well = WellFactory()
    body = auth_client.get(reverse("wells:detail", args=[well.pk])).content.decode()
    assert body.count('id="field-dwr_extraction_method"') == 1
    assert body.count('id="field-dwr_direct_or_estimate"') == 1
    assert body.count('id="field-accuracy_band"') == 1
    assert body.count('id="field-well_type"') == 1


def test_identity_line_says_not_stated_per_part():
    from wells.views import _dwr_extraction_line

    well = Well(
        dwr_extraction_method="", dwr_direct_or_estimate="", accuracy_band=""
    )
    assert _dwr_extraction_line(well) == "not stated, not stated, not stated"

    well.dwr_extraction_method = "land_use"
    assert _dwr_extraction_line(well) == "Land Use, not stated, not stated"
