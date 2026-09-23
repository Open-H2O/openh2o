# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-05 checkpoint, Brent's ruling 2 (2026-09-23): one editor for how a well is
measured.

The well page showed `measurement_method` with its own pencil beside the DWR
fields it was derived from once by migration 0005 (146-05 Task 2) and
independent of ever since, so the two could disagree on the same card. This
makes `measurement_method` READ-ONLY on the well page:

  1. The inline editor (`wells:edit_field`) refuses the field, GET and PATCH
     alike, exactly as it refuses a field it has never heard of -- it is
     simply absent from `EDITABLE_FIELDS` now (wells/views.py).
  2. The well page renders the field's value with no pencil.
  3. The Add Infrastructure well form no longer offers it, so a new well
     cannot be created with it and the three DWR fields already disagreeing.

`measurement_method` itself is untouched on the model: the seeds, seven test
files and the Merced audit trail still read it.
"""
from urllib.parse import urlencode

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import WellFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"readonlymethoduser{n}")
    email = factory.Sequence(lambda n: f"readonlymethoduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(_UserFactory())
    return c


def _patch(client, well, field, value):
    body = urlencode({"field": field, "value": value})
    return client.patch(
        reverse("wells:edit_field", args=[well.pk]),
        data=body,
        content_type="application/x-www-form-urlencoded",
    )


# ---------------------------------------------------------------------------
# 1. The endpoint refuses the field
# ---------------------------------------------------------------------------


def test_patch_refuses_measurement_method(auth_client):
    well = WellFactory(measurement_method="certified_meter")

    resp = _patch(auth_client, well, "measurement_method", "et_method")

    assert resp.status_code == 400
    well.refresh_from_db()
    assert well.measurement_method == "certified_meter"


def test_get_refuses_measurement_method(auth_client):
    well = WellFactory(measurement_method="certified_meter")

    resp = auth_client.get(
        reverse("wells:edit_field", args=[well.pk]), {"field": "measurement_method"}
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 2. The page renders no editor for it
# ---------------------------------------------------------------------------


def test_page_shows_the_value_with_no_pencil(auth_client):
    well = WellFactory(measurement_method="certified_meter")

    body = auth_client.get(reverse("wells:detail", args=[well.pk])).content.decode()

    assert "Certified Meter" in body
    # No editor was ever built for this field -- no GET/PATCH url references it.
    assert "?field=measurement_method" not in body
    # The pencil pattern every OTHER editable field on this page carries
    # (`_editable_field.html`) gives its field a `id="field-<name>"` wrapper
    # that the edit button's hx-target points at; that id must not exist for
    # this one now that it renders through the static block instead.
    assert 'id="field-measurement_method"' not in body


def test_page_reads_not_stated_when_blank(auth_client):
    well = WellFactory(measurement_method="")

    body = auth_client.get(reverse("wells:detail", args=[well.pk])).content.decode()

    assert "Measurement method" in body
    from wells.views import _measurement_method_display

    assert _measurement_method_display(well) == "Not stated"


# ---------------------------------------------------------------------------
# 3. The Add Infrastructure well form no longer offers it
# ---------------------------------------------------------------------------


def test_add_well_form_does_not_offer_measurement_method(auth_client):
    resp = auth_client.get(reverse("infrastructure:add"), {"type": "well"})

    body = resp.content.decode()
    assert 'name="measurement_method"' not in body


def test_add_well_form_still_offers_the_three_dwr_fields(auth_client):
    resp = auth_client.get(reverse("infrastructure:add"), {"type": "well"})

    body = resp.content.decode()
    assert 'name="dwr_extraction_method"' in body
    assert 'name="dwr_direct_or_estimate"' in body
    assert 'name="accuracy_band"' in body


def test_posting_the_add_well_form_never_sets_measurement_method(auth_client):
    """A new well created through this form starts blank on the legacy field --
    it cannot be created with it and the DWR fields already disagreeing,
    because the form no longer asks for it at all."""
    resp = auth_client.post(
        reverse("infrastructure:add"),
        {
            "infra_type": "well",
            "name": "Readonly Method Well",
            "status": "active",
            "geometry_json": '{"type": "Point", "coordinates": [-119.5, 36.5]}',
            "dwr_extraction_method": "meters",
            "dwr_direct_or_estimate": "direct",
        },
    )

    assert resp.status_code in (302, 200)
    from wells.models import Well

    well = Well.objects.get(name="Readonly Method Well")
    assert well.measurement_method == ""
    assert well.dwr_extraction_method == "meters"
