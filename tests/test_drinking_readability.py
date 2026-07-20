# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The onboarding screens must read to a non-specialist.

Written 2026-07-20 after review. The screens were correct and unreadable: they
showed ``DST``, ``LCR`` and ``WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3`` and
assumed the reader knew the vocabulary. The reviewer's verdict was "it's just a
bunch of random letters and acronyms — it doesn't read to a human at all."

These tests exist because that class of defect is invisible to every other test
in the suite. A page can render, return 200, carry correct data, and still be
useless to the person who has to act on it. Correctness tests cannot catch that;
these assert the explanations are actually present.

They are deliberately assertions about *plain language being present*, not about
exact wording — the copy should be free to improve without breaking the suite.
"""

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking import glossary
from drinking.models import SamplingPoint, SystemFacility, WaterSystem

PWSID = "CA1010001"


@pytest.fixture
def client_logged_in(db, django_user_model):
    user = django_user_model.objects.create(
        username="reader", email="reader@example.gov",
        password=make_password("pw"), is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def system(db):
    """Bakman's real shape: a sampled well, a sampled distribution system, and
    a pile of facilities that are never sampled."""
    system = WaterSystem.objects.create(pwsid=PWSID, name="BAKMAN WATER COMPANY")
    well = SystemFacility.objects.create(
        system=system, facility_id="010", name="WELL 10 - RAW",
        facility_type="WL", is_source=True,
    )
    dst = SystemFacility.objects.create(
        system=system, facility_id="DST", name="DISTRIBUTION SYSTEM",
        facility_type="DS",
    )
    SamplingPoint.objects.create(
        ps_code="CA1010001_010_010", facility=well, name="WELL 10 - RAW",
        point_type="source",
    )
    SamplingPoint.objects.create(
        ps_code="CA1010001_DST_LCR", facility=dst, name="LCR Tap Sample",
        point_type="tap",
    )
    # Never-sampled facilities — the 21 that used to be rendered as empty forms.
    for i in range(5):
        SystemFacility.objects.create(
            system=system, facility_id=f"9{i:02d}",
            name=f"WELL 0{i} - GAC EFFLUENT", facility_type="TP",
        )
    return system


class TestGlossary:
    def test_distribution_system_is_explained_as_pipes(self):
        text = glossary.facility_type_plain("DS")
        assert "pipes" in text.lower()

    def test_every_facility_type_choice_has_a_plain_description(self):
        """A code with no translation is the defect this module exists to fix."""
        from drinking.models import FACILITY_TYPE_CHOICES

        missing = [
            code for code, _ in FACILITY_TYPE_CHOICES
            if not glossary.facility_type_plain(code)
        ]
        assert missing == [], f"facility types with no plain description: {missing}"

    def test_shorthand_returns_only_terms_actually_present(self):
        """A full glossary on every page is just another wall."""
        found = dict(glossary.shorthand_in_use(["WELL 10 - RAW"]))
        assert "RAW" in found
        assert "GAC" not in found

    def test_shorthand_splits_epas_compound_names(self):
        """EPA runs terms together with underscores, hyphens and ampersands."""
        found = dict(
            glossary.shorthand_in_use(["WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3"])
        )
        for term in ("GAC", "IX", "NO3"):
            assert term in found, f"{term} not extracted from a real EPA name"


class TestBuilderReadsToAHuman:
    def test_page_says_what_it_is_for(self, client_logged_in, system):
        """The reviewer could not tell what the screen was for."""
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "What this page is for" in body
        assert "laborator" in body.lower()

    def test_distribution_system_is_explained_not_just_abbreviated(
        self, client_logged_in, system
    ):
        """"What does DST stand for?" must be answerable from the page."""
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "pipes that carry treated water" in body

    def test_abbreviations_appearing_on_the_page_are_defined(
        self, client_logged_in, system
    ):
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "What the abbreviations mean" in body
        # LCR and RAW both appear in this fixture's names.
        assert "Lead and Copper Rule" in body
        assert "Untreated water" in body

    def test_unsampled_facilities_are_collapsed_not_listed_flat(
        self, client_logged_in, system
    ):
        """21 identical empty forms buried the ones that mattered."""
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "Facilities that have sampling places (2)" in body
        assert "Facilities with no sampling places yet (5)" in body
        # Behind a disclosure control, still reachable.
        assert "<details" in body

    def test_context_separates_sampled_from_unsampled(self, client_logged_in, system):
        response = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        )
        assert len(response.context["facilities_with_points"]) == 2
        assert len(response.context["facilities_without_points"]) == 5


class TestReviewScreenSaysNothingIsSaved:
    def _render(self, skipped):
        from django.template.loader import render_to_string

        return render_to_string(
            "drinking/partials/_onboard_review.html",
            {
                "pwsid": PWSID, "name": "BAKMAN WATER COMPANY",
                "facilities": [], "facility_count": 35,
                "epa_facility_count": 36, "skipped": skipped,
                "warnings": [], "already_onboarded": False,
                "existing_facility_count": 0, "mailing": {},
                "geography": {},
            },
        )

    def test_leads_with_nothing_saved(self):
        """A lookup fetches real records, so it feels like something happened."""
        body = self._render([])
        assert "Nothing has been saved yet" in body
        assert body.index("Nothing has been saved yet") < body.index("PWSID")

    def test_skip_is_a_headline_not_a_buried_row(self):
        body = self._render(['EPA facility CA1010001001 ("WELL 01") has no state id.'])
        # Stated as a sentence with both numbers, not left to arithmetic.
        assert "will be left out" in body
        assert "35 will be" in body or "35 will not" in body or "36 facilities" in body

    def test_skip_section_is_not_duplicated(self):
        body = self._render(['EPA facility CA1010001001 has no state id.'])
        assert body.count("EPA facility CA1010001001 has no state id.") == 1
