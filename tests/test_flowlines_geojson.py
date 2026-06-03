# SPDX-License-Identifier: AGPL-3.0-or-later
"""
flowlines_geojson endpoint (Phase 50-01).

The hydrography rendering path: model -> endpoint -> map layer. This locks the
endpoint contract the map layer depends on:
  - it is login-gated like every other GeoJSON endpoint (ISS-039);
  - it returns a FeatureCollection of MultiLineString features carrying the
    name / feature_type / stream_order the river/canal layers filter and label on;
  - it serializes exactly the geometry-bearing flowlines.

Note on the "no geometry is excluded" case: Flowline.geometry is a non-nullable
MultiLineStringField, so a geometry-less row cannot be persisted. The endpoint
keeps the defensive `geometry__isnull=False` filter for parity with
boundaries_geojson / zones_geojson; this test locks the observable contract
(feature count == geometry-bearing queryset count) rather than constructing an
impossible row.
"""

import json

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from geography.models import Flowline
from tests.factories import FlowlineFactory


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"flow{n}")
    email = factory.Sequence(lambda n: f"flow{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.mark.django_db
def test_flowlines_geojson_anonymous_redirects(client):
    FlowlineFactory()
    resp = client.get(reverse("geography:flowlines_geojson"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_flowlines_geojson_returns_multilinestring_features(auth_client):
    FlowlineFactory(name="Test Creek", feature_type="Stream/River", stream_order=4)
    resp = auth_client.get(reverse("geography:flowlines_geojson"))
    assert resp.status_code == 200

    data = json.loads(resp.content.decode())
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1

    feature = data["features"][0]
    assert feature["geometry"]["type"] == "MultiLineString"
    props = feature["properties"]
    assert props["name"] == "Test Creek"
    assert props["feature_type"] == "Stream/River"
    assert props["stream_order"] == 4


@pytest.mark.django_db
def test_flowlines_geojson_renders_named_and_canals_skips_unnamed_capillaries(auth_client):
    """Scale guard (50-02): the map serves significant flowlines only —
    every canal + every named natural waterway — while unnamed first-order
    capillaries (the bulk of the real 3DHP upper-watershed data) are dropped
    so the 30 MB full payload doesn't sink the map."""
    FlowlineFactory(name="Merced River", feature_type="Channel Line")   # named river -> rendered
    FlowlineFactory(name="", feature_type="Canal")                       # unnamed canal -> rendered
    FlowlineFactory(name="", feature_type="Channel Line")                # unnamed capillary -> dropped
    resp = auth_client.get(reverse("geography:flowlines_geojson"))
    assert resp.status_code == 200

    data = json.loads(resp.content.decode())
    # 2 of the 3 are significant; the unnamed natural capillary is excluded.
    assert len(data["features"]) == 2
    types = sorted(f["properties"]["feature_type"] for f in data["features"])
    assert types == ["Canal", "Channel Line"]
    names = {f["properties"]["name"] for f in data["features"]}
    assert "Merced River" in names
