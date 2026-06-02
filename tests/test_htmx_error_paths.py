# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTMX error-render paths that previously lost data or grafted a page-in-a-page
(ISS-034).

1. diversion_record_create: an invalid submit must re-render the BOUND form with
   the user's values + visible errors, not a fresh blank form (silent data loss).
2. csv_upload: an invalid HTMX submit must return the small results PARTIAL with
   the error, not the full csv_upload.html document (nested form / duplicate IDs).
"""
import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.models import DiversionRecord
from tests.factories import PointOfDiversionFactory

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"htmxuser{n}")
    email = factory.Sequence(lambda n: f"htmxuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------------------
# Diversion record create — bound-form re-render
# ---------------------------------------------------------------------------


class TestDiversionErrorPath:
    def test_invalid_submit_shows_errors_and_keeps_values_without_saving(self, auth_client):
        pod = PointOfDiversionFactory()
        url = reverse("surface:diversion_record_create", args=[pod.pk])

        resp = auth_client.post(
            url,
            {
                "month": "2024-01-01",
                "volume_acre_feet": "abc",  # non-numeric → form invalid
                "diversion_type": "direct_use",
            },
            HTTP_HX_REQUEST="true",
        )

        assert resp.status_code == 200
        body = resp.content.decode()
        # Visible error (not a silent blank reset)...
        assert "Enter a number" in body
        # ...and the user's typed month survives on the re-rendered bound form.
        assert "2024-01-01" in body
        # No phantom record was written.
        assert DiversionRecord.objects.count() == 0

    def test_valid_submit_saves_and_returns_blank_form(self, auth_client):
        pod = PointOfDiversionFactory()
        url = reverse("surface:diversion_record_create", args=[pod.pk])

        resp = auth_client.post(
            url,
            {
                "month": "2024-01-01",
                "volume_acre_feet": "42.5",
                "diversion_type": "direct_use",
            },
            HTTP_HX_REQUEST="true",
        )

        assert resp.status_code == 200
        assert DiversionRecord.objects.count() == 1
        record = DiversionRecord.objects.get()
        assert str(record.volume_acre_feet) == "42.5000"


# ---------------------------------------------------------------------------
# CSV upload — partial-only error render
# ---------------------------------------------------------------------------


class TestCsvUploadErrorPath:
    def test_invalid_htmx_upload_returns_partial_not_full_page(self, auth_client):
        url = reverse("accounting:csv_upload")

        # No file → CsvUploadForm invalid. HTMX request targets #upload-results.
        resp = auth_client.post(url, {}, HTTP_HX_REQUEST="true")

        assert resp.status_code == 200
        body = resp.content.decode()
        # The error is shown...
        assert "required" in body.lower()
        # ...but as a fragment, NOT the full document grafted into the results div.
        assert "<!doctype" not in body.lower()
        assert "<html" not in body.lower()
        assert "csv-upload-form" not in body  # the full page's upload <form> id
