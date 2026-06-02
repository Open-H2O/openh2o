# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Unauthenticated-exposure regression (ISS-039).

Two GeoJSON endpoints shipped without @login_required while every peer had it —
a curl pulled full district boundary + management-zone geometry with no account.
And the health endpoints returned free-text messages naming internal subsystems
and failure reasons to anyone. This locks: geometry endpoints require auth, and
the anonymous health response is a creds-free liveness ping with no detail.
"""

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from health.models import HealthCheckResult
from tests.factories import BoundaryFactory, ZoneFactory

SECRET_MESSAGE = "INTERNAL-SUBSYSTEM-postgres-replica-lag-4200ms"


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"exposure{n}")
    email = factory.Sequence(lambda n: f"exposure{n}@example.com")
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


# ---------------------------------------------------------------------------
# GeoJSON endpoints now require auth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGeoJsonRequiresAuth:
    def test_boundaries_geojson_anonymous_redirects(self, client):
        BoundaryFactory()
        resp = client.get(reverse("geography:boundaries_geojson"))
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    def test_zones_geojson_anonymous_redirects(self, client):
        ZoneFactory()
        resp = client.get(reverse("geography:zones_geojson"))
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    def test_boundaries_geojson_authenticated_returns_geometry(self, auth_client):
        BoundaryFactory()
        resp = auth_client.get(reverse("geography:boundaries_geojson"))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "FeatureCollection" in body

    def test_zones_geojson_authenticated_returns_geometry(self, auth_client):
        ZoneFactory()
        resp = auth_client.get(reverse("geography:zones_geojson"))
        assert resp.status_code == 200
        assert "FeatureCollection" in resp.content.decode()


# ---------------------------------------------------------------------------
# Health: creds-free liveness ping, no internal detail to anonymous callers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealthDetailGated:
    def _seed(self):
        HealthCheckResult.objects.create(
            category="database", status="green", message=SECRET_MESSAGE
        )

    def test_anonymous_api_is_liveness_only(self, client):
        self._seed()
        resp = client.get(reverse("health:api"))
        assert resp.status_code == 200
        data = resp.json()
        # Liveness status present...
        assert data["status"] == "healthy"
        # ...but no subsystem names, messages, or per-check array.
        assert "checks" not in data
        assert SECRET_MESSAGE not in resp.content.decode()

    def test_authenticated_api_returns_full_detail(self, auth_client):
        self._seed()
        resp = auth_client.get(reverse("health:api"))
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert any(c["message"] == SECRET_MESSAGE for c in data["checks"])

    def test_anonymous_dashboard_hides_subsystem_messages(self, client):
        self._seed()
        resp = client.get(reverse("health:dashboard"))
        assert resp.status_code == 200  # still a public liveness page
        assert SECRET_MESSAGE not in resp.content.decode()

    def test_authenticated_dashboard_shows_detail(self, auth_client):
        self._seed()
        resp = auth_client.get(reverse("health:dashboard"))
        assert resp.status_code == 200
        assert SECRET_MESSAGE in resp.content.decode()
