# SPDX-License-Identifier: AGPL-3.0-or-later
"""
143-08 Task 5 -- guards for the lab-result share of R-055: the finding leads
the page at the only large size, with the reporting level and the previous
finding as its two peers.

Every guard here was observed RED against the pre-change tree (commit
7c368d1, before the sixteen-field grid became the account-grid panel) before
it went green; the RED assertion text is quoted in 143-08-EVIDENCE.md.

The ISS-140 fixture pattern (a real ``RegulatoryLimit`` on the analyte, so an
absent "Regulatory limit" string is a genuine assertion) is extended here
rather than weakened: this file's own fixture carries a limit too.
"""

import re
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    AnalyteFactory,
    RegulatoryLimitFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention -- every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinklab{n}")
    email = factory.Sequence(lambda n: f"drinklab{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _squash(html):
    return " ".join(html.split())


def _result_segment(html):
    """The one ``.budget-seg--result`` block on the page."""
    segments = re.findall(
        r'<div class="budget-seg budget-seg--result">.*?</div>\s*</div>',
        html, re.S,
    )
    assert len(segments) == 1, (
        f"expected exactly one .budget-seg--result, found {len(segments)}"
    )
    return segments[0]


@pytest.fixture
def lab_result_with_history(db):
    """One analyte, two findings at the same point: an earlier 6.9 and a
    later 7.4 with a reporting level, plus a real regulatory limit on the
    analyte (the ISS-140 pattern, extended rather than weakened).
    """
    system = WaterSystemFactory(pwsid="CA1010793", name="Ridge Water District")
    facility = SystemFacilityFactory(
        system=system, facility_id="001", facility_type="WL"
    )
    point = SamplingPointFactory(ps_code="CA1010793_001_001", facility=facility)
    nitrate = AnalyteFactory(name="Nitrate", ddw_code="1040")

    earlier_event = SampleEventFactory(
        sampling_point=point, sample_date=date(2024, 5, 1)
    )
    earlier = SampleResultFactory(
        event=earlier_event, analyte=nitrate, result_kind="numeric",
        result_value=Decimal("6.900000"), unit="MG/L",
    )
    later_event = SampleEventFactory(
        sampling_point=point, sample_date=date(2024, 6, 1)
    )
    later = SampleResultFactory(
        event=later_event, analyte=nitrate, result_kind="numeric",
        result_value=Decimal("7.400000"), unit="MG/L",
        reporting_level=Decimal("0.500000"),
    )
    RegulatoryLimitFactory(
        analyte=nitrate, limit_type="mcl", value=Decimal("10.000000"),
        unit="MG/L", jurisdiction="federal",
    )
    return {
        "system": system, "point": point, "earlier": earlier, "later": later,
        "analyte": nitrate,
    }


class TestLabResultLeadsWithTheFinding:
    def test_the_result_segment_holds_the_number_and_the_unit(
        self, client_in, lab_result_with_history
    ):
        html = client_in.get(
            reverse("drinking:result_detail", args=[lab_result_with_history["later"].pk])
        ).content.decode()
        segment = _result_segment(html)
        assert "7.4" in segment
        assert "MG/L" in segment

    def test_the_reporting_level_peer_shows_the_least_the_method_reports(
        self, client_in, lab_result_with_history
    ):
        html = client_in.get(
            reverse("drinking:result_detail", args=[lab_result_with_history["later"].pk])
        ).content.decode()
        text = _squash(html)
        assert "0.5" in text
        assert "the least this method reports" in text

    def test_the_previous_finding_peer_shows_the_earlier_result_and_its_date(
        self, client_in, lab_result_with_history
    ):
        html = client_in.get(
            reverse("drinking:result_detail", args=[lab_result_with_history["later"].pk])
        ).content.decode()
        text = _squash(html)
        assert "6.9" in text
        assert "2024-05-01" in text
        assert "the same analyte at this point" in text

    def test_no_earlier_result_reads_no_earlier_finding(
        self, client_in, lab_result_with_history
    ):
        html = client_in.get(
            reverse("drinking:result_detail", args=[lab_result_with_history["earlier"].pk])
        ).content.decode()
        text = _squash(html)
        assert "no earlier finding of this analyte at this point" in text

    def test_a_non_detect_renders_its_bound_and_caption(self, client_in, db):
        system = WaterSystemFactory(pwsid="CA1010794", name="Ridge Water District")
        facility = SystemFacilityFactory(
            system=system, facility_id="001", facility_type="WL"
        )
        point = SamplingPointFactory(ps_code="CA1010794_001_001", facility=facility)
        event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
        non_detect = SampleResultFactory(
            event=event, analyte=AnalyteFactory(name="Arsenic"),
            result_kind="numeric", result_value=None, less_than_rl=True,
            reporting_level=Decimal("0.500000"), unit="MG/L",
        )
        html = client_in.get(
            reverse("drinking:result_detail", args=[non_detect.pk])
        ).content.decode()
        segment = _result_segment(html)
        assert "&lt; 0.5" in segment
        assert (
            "reported below the laboratory's reporting level, "
            "not a measured quantity"
        ) in _squash(segment)

    def test_regulatory_limit_never_appears_even_with_a_limit_on_the_analyte(
        self, client_in, lab_result_with_history
    ):
        """A real RegulatoryLimit exists on this analyte (the fixture above),
        so an absent "Regulatory limit" string is a genuine assertion, not a
        vacuous one."""
        html = client_in.get(
            reverse("drinking:result_detail", args=[lab_result_with_history["later"].pk])
        ).content.decode()
        assert "Regulatory limit" not in html
        assert "10.000000" not in html

    def test_no_field_label_reads_unit(self, client_in, lab_result_with_history):
        html = client_in.get(
            reverse("drinking:result_detail", args=[lab_result_with_history["later"].pk])
        ).content.decode()
        assert '<div class="field-label">Unit</div>' not in html
