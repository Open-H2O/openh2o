# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Stored-XSS regression for the detail-page GeoJSON blocks (ISS-036).

Every detail page used to emit ``var geojson = {{ ...|safe }};`` inside an
inline ``<script>``. Because ``json.dumps``/``serialize("geojson")`` does NOT
escape ``</script>``, an operator-editable free-text field (a well/parcel/zone
name) holding ``</script><script>alert(1)</script>`` would break out of the
script tag and execute in every admin browser — stored, session-riding XSS.

The fix routes each blob through Django's ``json_script`` filter, which
HTML-escapes ``<``/``>``/``&`` as ``\\u003C``/``\\u003E``/``\\u0026`` (valid
JSON, parses back to the original on ``JSON.parse``). These tests assert the
breakout sequence never appears unescaped in the rendered page.
"""

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import ParcelFactory, WellFactory, ZoneFactory

# The script-breakout payload an attacker would store in a name field.
PAYLOAD = "</script><script>alert(1)</script>"
# The exact unescaped breakout we must never see in the response body.
BREAKOUT = "</script><script>alert(1)"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"xssuser{n}")
    email = factory.Sequence(lambda n: f"xssuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


def _assert_escaped(response, payload_present_via):
    """A detail page is safe when the breakout is gone and json_script escaped it."""
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # The raw breakout (closing the real <script> then opening a new one) must
    # not survive into the output.
    assert BREAKOUT not in body, (
        f"Unescaped XSS breakout leaked into the {payload_present_via} page"
    )
    # And json_script must have actually encoded the angle brackets — proves the
    # payload reached the GeoJSON blob and was neutralized, not merely dropped.
    assert "\\u003c" in body.lower(), (
        f"json_script escaping not present on the {payload_present_via} page"
    )


@pytest.mark.django_db
def test_well_detail_escapes_name_xss(auth_client):
    well = WellFactory(name=PAYLOAD)
    response = auth_client.get(reverse("wells:detail", kwargs={"pk": well.pk}))
    _assert_escaped(response, "well")


@pytest.mark.django_db
def test_parcel_detail_escapes_owner_xss(auth_client):
    # owner_name is serialized into the parcel GeoJSON properties.
    parcel = ParcelFactory(owner_name=PAYLOAD)
    response = auth_client.get(reverse("parcels:detail", kwargs={"pk": parcel.pk}))
    _assert_escaped(response, "parcel")


@pytest.mark.django_db
def test_zone_detail_escapes_name_xss(auth_client):
    zone = ZoneFactory(name=PAYLOAD)
    response = auth_client.get(
        reverse("geography:zone_detail", kwargs={"pk": zone.pk})
    )
    _assert_escaped(response, "zone")
