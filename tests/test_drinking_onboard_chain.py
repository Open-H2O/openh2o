# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 80-03 — the flow runs end to end without a dead end.

Each screen of this flow was built in a different plan, and each was tested
against its own surface. This file tests the *seams*: that the result screen
hands off to the builder, that the builder hands off to the importer, and that
the importer's most likely failure hands back to the builder.

Those seams are exactly what unit tests of each screen cannot catch. 80-02 had
to leave a placeholder here because the builder's route did not exist yet, and a
{% url %} to a route that does not exist raises NoReverseMatch — a dead link in
this flow is a 500, not a cosmetic flaw.
"""

from pathlib import Path

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking.models import SamplingPoint, SystemFacility, WaterSystem

PWSID = "CA1010001"
FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "drinking_sdwis4_slice.tab"
)


@pytest.fixture
def client_logged_in(db, django_user_model):
    user = django_user_model.objects.create(
        username="chain-operator",
        email="chain@example.gov",
        password=make_password("pw"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def system(db):
    system = WaterSystem.objects.create(pwsid=PWSID, name="BAKMAN WATER COMPANY")
    SystemFacility.objects.create(
        system=system, facility_id="010", name="WELL 10", facility_type="WL"
    )
    SystemFacility.objects.create(
        system=system, facility_id="DST", name="DISTRIBUTION SYSTEM",
        facility_type="DS",
    )
    return system


class TestNoPlaceholdersRemain:
    def test_drinking_templates_carry_no_placeholder_markers(self):
        """80-02 left one deliberately; 80-03 is where it gets resolved."""
        templates = Path(__file__).resolve().parent.parent / "templates" / "drinking"
        offenders = [
            str(path.relative_to(templates))
            for path in templates.rglob("*.html")
            if "PLACEHOLDER" in path.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"placeholder text still in: {offenders}"


class TestOnboardHandsOffToTheBuilder:
    def test_result_screen_links_to_the_builder_for_that_system(self, system):
        """Rendered from the committed system, not from a guessed URL.

        Rendering the partial directly rather than driving a commit: the seam
        under test is the template's {% url %} against `result.system`, and a
        full commit would put an Envirofacts round-trip between the test and
        the thing it is asserting.
        """
        from django.template.loader import render_to_string

        html = render_to_string(
            "drinking/partials/_onboard_result.html",
            {
                "result": {
                    "system": system,
                    "created": True,
                    "facilities_created": 35,
                    "facilities_updated": 0,
                    "skipped": ["CA1010001001 has no state facility id"],
                    "warnings": [],
                },
                "pwsid": PWSID,
                "epa_facility_count": 36,
            },
        )
        assert reverse("drinking:onboard_points", args=[PWSID]) in html
        assert "not built yet" not in html

    def test_builder_route_reverses(self, system):
        # The exact failure 80-02 was protecting against: this reverse existing
        # is what allows the placeholder to become a real link.
        assert reverse("drinking:onboard_points", args=[PWSID]) == (
            f"/drinking/onboard/{PWSID}/points/"
        )


class TestBuilderHandsOffToTheImporter:
    def test_builder_page_links_to_the_import_flow(self, client_logged_in, system):
        response = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        )
        assert reverse("drinking:import").encode() in response.content


class TestImporterHandsBackToTheBuilder:
    def _upload(self, client, content):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return client.post(
            reverse("drinking:import_preview"),
            {"file": SimpleUploadedFile("slice.tab", content, "text/tab-separated-values")},
        )

    def test_unknown_ps_code_points_at_the_builder(self, client_logged_in, system):
        """The partially-walked system: the file names a point nobody added."""
        response = self._upload(
            client_logged_in, FIXTURE.read_bytes()
        )
        assert response.status_code == 200
        body = response.content.decode()

        # No sampling points exist, so every code in the file is unknown...
        assert "not carried here" in body
        # ...and each one routes back to the builder for its own system.
        assert reverse("drinking:onboard_points", args=[PWSID]) in body

    def test_known_ps_code_produces_no_such_callout(self, client_logged_in, system):
        """Once the point exists the callout is gone — it is not decoration."""
        dst = system.facilities.get(facility_id="DST")
        well = system.facilities.get(facility_id="010")
        # Every code the fixture names, so nothing is left unmatched.
        for facility, number in (
            (dst, "900"), (dst, "901"), (dst, "902"), (dst, "903"), (dst, "LCR"),
        ):
            SamplingPoint.objects.create(
                ps_code=f"{PWSID}_{facility.facility_id}_{number}",
                facility=facility,
            )
        for number in (
            "005", "006", "007", "008", "009", "010", "011", "012",
            "014", "020", "022", "026", "034",
        ):
            SamplingPoint.objects.create(
                ps_code=f"{PWSID}_{number}_{number}", facility=well
            )

        response = self._upload(client_logged_in, FIXTURE.read_bytes())
        body = response.content.decode()
        assert "not carried here" not in body

    def test_unknown_system_says_onboard_first(self, client_logged_in, db):
        """A code whose PWSID is not carried at all routes to the wizard."""
        WaterSystem.objects.all().delete()
        response = self._upload(client_logged_in, FIXTURE.read_bytes())
        body = response.content.decode()
        assert "is not onboarded yet" in body
