# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 98-01 — the drinking domain's three detail pages.

These pages exist because every row on every drinking surface used to lead
nowhere, and a 28-column lab record was showing six of its columns. Five things
are load-bearing enough to state plainly.

**A presence/absence result must never render as a number**, and now there are
two more surfaces where it could. 78-01 made it unrepresentable in the database
and ``tests/test_drinking_views.py`` pinned it at the list templates; this file
re-pins the same rule at the result detail page and at the sampling point's
embedded table. "Absent" must read as *Absent*, not 0 and not "< RL".

**No verdicts.** No page here may compare a result against a ``RegulatoryLimit``
or render one beside a value. The fixture creates a limit that would be exceeded
precisely so the assertion is real rather than vacuous — a one-record page is
where a limit beside a value looks most natural and is most wrong.

**The well link is module-guarded.** ``drinking.requires`` is ``("standards",)``,
so every one of these pages must render on a deployment carrying no ``wells``
module. An unguarded ``{% url 'wells:detail' %}`` there is a ``NoReverseMatch``
500, not a missing link — and a drinking-water-only deployment is the flavor
this module exists to serve.

**Truncation must admit it is truncation.** A sampling point in the Merced
demonstration carries roughly 800 results. Its page shows 25 and states the true
total; a partial list that reads as a complete one is the failure mode.

**Every list leads somewhere.** One assertion per list surface, checking the row
href, so a future template edit that drops a link fails here instead of on
staging.
"""

from datetime import date, time
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import modules as mod
from tests.factories import (
    AnalyteFactory,
    RegulatoryLimitFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    WellFactory,
)

# The same mechanism test_module_prose.py uses, imported rather than reinvented:
# config/urls.py composes its module routes at IMPORT time and Django imports
# ROOT_URLCONF lazily on the first request of the process, so a test that
# narrows OPENH2O_MODULES and then makes the process's first request would
# permanently compose a reduced URLconf for every later test.
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

WITHOUT_WELLS = [name for name in mod.ALL_MODULE_NAMES if name != "wells"]


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinkdetail{n}")
    email = factory.Sequence(lambda n: f"drinkdetail{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def sampled_system(db):
    """One system, a well-backed facility, two points, three kinds of result.

    The three result kinds are the whole point: a plain numeric, a non-detect,
    and a presence/absence. Every rendering assertion below leans on all three
    existing at once, so a template that handles one kind by accident cannot
    pass. The MCL is deliberately set BELOW the numeric result, so a page that
    quietly started judging would have something to flag.
    """
    well = WellFactory(name="Orchard Supply Well")
    system = WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
    facility = SystemFacilityFactory(
        system=system, facility_id="WL-001", name="Orchard Wellhead",
        facility_type="WL", well=well,
    )
    bare_facility = SystemFacilityFactory(
        system=system, facility_id="DST", name="DISTRIBUTION SYSTEM",
        facility_type="DS", well=None,
    )
    point = SamplingPointFactory(
        ps_code="CA2410009_WL-001_001", name="Wellhead Tap", facility=facility
    )
    quiet_point = SamplingPointFactory(
        ps_code="CA2410009_DST_001", name="Far End Tap", facility=bare_facility
    )
    event = SampleEventFactory(
        sampling_point=point, sample_date=date(2024, 6, 1), sample_time=time(9, 30),
        sample_type="routine", collector="J. Rivera",
        chain_of_custody_note="Sealed on site, delivered same day.",
    )

    nitrate = AnalyteFactory(name="Nitrate", ddw_code="1040")
    arsenic = AnalyteFactory(name="Arsenic")
    coliform = AnalyteFactory(name="Total Coliforms")

    numeric = SampleResultFactory(
        event=event, analyte=nitrate, result_kind="numeric",
        result_value=Decimal("3.200000"), unit="mg/L",
        method="EPA 300.0", lab_name="Valley Analytical", lab_cert_no="2809",
        analysis_date=date(2024, 6, 3),
    )
    non_detect = SampleResultFactory(
        event=event, analyte=arsenic, result_kind="numeric", result_value=None,
        less_than_rl=True, reporting_level=Decimal("0.002000"), unit="mg/L",
    )
    presence = SampleResultFactory(
        event=event, analyte=coliform, result_kind="presence_absence",
        result_value=None, presence=False, unit="",
    )
    RegulatoryLimitFactory(
        analyte=nitrate, limit_type="mcl", value=Decimal("1.000000"),
        unit="mg/L", jurisdiction="federal",
    )
    return {
        "well": well, "system": system, "facility": facility,
        "bare_facility": bare_facility, "point": point, "quiet_point": quiet_point,
        "event": event, "numeric": numeric, "non_detect": non_detect,
        "presence": presence,
    }


def _squash(html):
    """Collapse whitespace so a template's line wrapping cannot break a match."""
    return " ".join(html.split())


def _tbody(html):
    """Just the rows of the page's table."""
    assert "<tbody>" in html, "No table on the page"
    return html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


def _row_containing(html, needle):
    """The single <tr> in the table holding `needle`."""
    rows = [r for r in _tbody(html).split("<tr") if needle in r]
    assert len(rows) == 1, f"Expected exactly one row containing {needle!r}"
    return rows[0]


def _urls(fixture):
    return {
        "facility": reverse("drinking:facility_detail", args=[fixture["facility"].pk]),
        "point": reverse(
            "drinking:sampling_point_detail", args=[fixture["point"].pk]
        ),
        "result": reverse("drinking:result_detail", args=[fixture["numeric"].pk]),
    }


# -- 1. Access ---------------------------------------------------------------


class TestPagesRender:
    def test_each_detail_page_returns_200(self, client_in, sampled_system):
        for name, url in _urls(sampled_system).items():
            assert client_in.get(url).status_code == 200, f"{name} did not render"

    def test_each_detail_page_requires_login(self, db, sampled_system):
        for name, url in _urls(sampled_system).items():
            response = Client().get(url)
            assert response.status_code == 302, f"{name} served an anonymous visitor"
            assert (
                "/login" in response["Location"] or "accounts" in response["Location"]
            )

    @pytest.mark.parametrize(
        "url_name",
        [
            "drinking:facility_detail",
            "drinking:sampling_point_detail",
            "drinking:result_detail",
        ],
    )
    def test_a_nonexistent_record_is_404_not_500(self, client_in, db, url_name):
        assert client_in.get(reverse(url_name, args=[9_999_999])).status_code == 404

    def test_a_page_with_nothing_on_it_still_renders(self, client_in, sampled_system):
        """A facility with no points and a point with no results are ordinary."""
        for url in (
            reverse(
                "drinking:facility_detail", args=[sampled_system["bare_facility"].pk]
            ),
            reverse(
                "drinking:sampling_point_detail",
                args=[sampled_system["quiet_point"].pk],
            ),
        ):
            assert client_in.get(url).status_code == 200

    def test_no_template_syntax_leaks_into_the_page(self, client_in, sampled_system):
        """A developer comment must never reach the reader.

        Django's `{# ... #}` comments only to the END OF ITS LINE, so a
        multi-line note written that way renders its second line onward as page
        text — in a plausible-looking spot, which a passing suite and a quick
        glance both miss. It shipped into the Facilities table once already.
        """
        for name, url in _urls(sampled_system).items():
            html = client_in.get(url).content.decode()
            for leak in ("{#", "#}", "{% comment", "endcomment", "{{", "{%"):
                assert leak not in html, f"{name} leaked template syntax {leak!r}"


# -- 2 & 4. Honest rendering -------------------------------------------------


class TestResultsRenderHonestly:
    """The same rule Phase 78 pinned at the lists, re-pinned at two new surfaces."""

    def test_presence_absence_reads_as_a_word_on_the_result_page(
        self, client_in, sampled_system
    ):
        html = client_in.get(
            reverse("drinking:result_detail", args=[sampled_system["presence"].pk])
        ).content.decode()
        assert "Absent" in html
        assert ">0<" not in html, "an absent result rendered as a bare 0"
        assert "&lt; RL" not in html, "an absent result rendered as a non-detect"

    def test_presence_absence_reads_as_a_word_in_the_points_table(
        self, client_in, sampled_system
    ):
        html = client_in.get(
            reverse("drinking:sampling_point_detail", args=[sampled_system["point"].pk])
        ).content.decode()
        row = _row_containing(html, "Total Coliforms")
        assert "Absent" in row
        assert ">0<" not in row, "an absent result rendered as a bare 0"
        assert "&lt;" not in row, "an absent result rendered as a non-detect"

    def test_non_detect_reads_as_a_bound_not_as_its_reporting_level(
        self, client_in, sampled_system
    ):
        """"< 0.002 mg/L" is a bound. The bare reporting level would be a claim
        the laboratory never made, and 0 would be a different one again."""
        html = client_in.get(
            reverse("drinking:result_detail", args=[sampled_system["non_detect"].pk])
        ).content.decode()
        assert "&lt; 0.002 mg/L" in html
        text = _squash(html)
        assert "non-detect" in text
        assert "different claim from zero" in text, (
            "the page shows a bound but never says it is one"
        )

    def test_a_stored_decimal_never_shows_precision_nobody_measured(
        self, client_in, sampled_system
    ):
        """The column stores six decimal places; 3.2 mg/L must not read 3.200000."""
        html = client_in.get(
            reverse("drinking:result_detail", args=[sampled_system["numeric"].pk])
        ).content.decode()
        assert "3.2 mg/L" in html
        assert "3.200000" not in html

    def test_the_whole_lab_record_is_on_the_page(self, client_in, sampled_system):
        """The columns the log hides — the reason this page exists."""
        html = client_in.get(
            reverse("drinking:result_detail", args=[sampled_system["numeric"].pk])
        ).content.decode()
        for field in (
            "EPA 300.0", "Valley Analytical", "2809", "2024-06-03",
            "J. Rivera", "Sealed on site", "CA2410009_WL-001_001", "1040",
        ):
            assert field in html, f"the result page is missing {field!r}"
        assert "ELAP" in html, "a bare certification number with no scheme named"


# -- 3. Posture: prepare, never determine ------------------------------------


class TestNoComplianceVerdict:
    """A limit exists in the fixture, so this is a real assertion, not a vacuous one."""

    @pytest.mark.parametrize("page", ["result", "point"])
    def test_no_detail_page_renders_a_verdict(self, client_in, sampled_system, page):
        url = _urls(sampled_system)[page]
        html = client_in.get(url).content.decode().lower()
        for verdict in (
            "exceed", "violation", "out of compliance", "non-compliant",
            "pass/fail", "in compliance", "compliant",
        ):
            assert verdict not in html, f"{page} detail renders a verdict: {verdict!r}"

    @pytest.mark.parametrize("page", ["result", "point"])
    def test_no_detail_page_renders_the_limit_itself(
        self, client_in, sampled_system, page
    ):
        """Showing the limit beside the value is the verdict, whatever the wording."""
        url = _urls(sampled_system)[page]
        html = client_in.get(url).content.decode()
        assert "Maximum Contaminant Level" not in html
        assert "1.000000" not in html
        assert "Regulatory limit" not in html


# -- 5. The module guard -----------------------------------------------------


class TestWellLinkIsModuleGuarded:
    """`drinking.requires` is ("standards",) — these pages run without `wells`."""

    @pytest.fixture(autouse=True)
    def _wells_is_off(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_WELLS

    def test_facility_detail_renders_the_well_as_plain_text(
        self, client_in, sampled_system
    ):
        response = client_in.get(
            reverse("drinking:facility_detail", args=[sampled_system["facility"].pk])
        )
        assert response.status_code == 200, (
            "the facility page 500s on a drinking-water-only deployment"
        )
        html = response.content.decode()
        assert "Orchard Supply Well" in html, "the well vanished instead of degrading"
        assert "/wells/" not in html, "an unguarded wells link survived"

    def test_sampling_point_detail_renders_the_well_as_plain_text(
        self, client_in, sampled_system
    ):
        response = client_in.get(
            reverse("drinking:sampling_point_detail", args=[sampled_system["point"].pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert "Orchard Supply Well" in html
        assert "/wells/" not in html


# -- 6. Every list leads somewhere -------------------------------------------


class TestListsLinkToTheDetailPages:
    def test_the_overview_facility_rows_link_to_the_facility_page(
        self, client_in, sampled_system
    ):
        html = client_in.get(reverse("drinking:overview")).content.decode()
        expected = reverse(
            "drinking:facility_detail", args=[sampled_system["facility"].pk]
        )
        assert f'href="{expected}"' in html

    def test_the_sampling_point_rows_link_to_the_point_page(
        self, client_in, sampled_system
    ):
        html = client_in.get(reverse("drinking:sampling_points")).content.decode()
        expected = reverse(
            "drinking:sampling_point_detail", args=[sampled_system["point"].pk]
        )
        assert f'href="{expected}"' in html

    def test_the_result_rows_link_to_the_result_page(self, client_in, sampled_system):
        html = client_in.get(reverse("drinking:results")).content.decode()
        expected = reverse(
            "drinking:result_detail", args=[sampled_system["numeric"].pk]
        )
        assert f'href="{expected}"' in html


# -- 7. Truncation is honest -------------------------------------------------


class TestTruncationAdmitsItself:
    def test_thirty_results_render_as_twenty_five_rows_under_a_heading_naming_thirty(
        self, client_in, sampled_system
    ):
        point = sampled_system["point"]
        # The fixture already carries 3; add 27 to reach 30.
        for day in range(2, 29):
            event = SampleEventFactory(
                sampling_point=point, sample_date=date(2024, 5, day)
            )
            SampleResultFactory(event=event, analyte=AnalyteFactory())

        html = client_in.get(
            reverse("drinking:sampling_point_detail", args=[point.pk])
        ).content.decode()
        assert _tbody(html).count("<tr") == 25, "the page did not cap its table at 25"
        text = _squash(html)
        assert "The 25 most recent of 30 results" in text, (
            "the heading does not state the true total"
        )
        assert "See all 30 results for this point" in text, (
            "no way out to the unfiltered log"
        )
        assert f"?sampling_point={point.pk}" in html

    def test_a_short_history_is_not_dressed_up_as_a_truncated_one(
        self, client_in, sampled_system
    ):
        html = client_in.get(
            reverse("drinking:sampling_point_detail", args=[sampled_system["point"].pk])
        ).content.decode()
        assert "most recent of" not in _squash(html)
        assert _tbody(html).count("<tr") == 3


# -- 8. The CCR link is California-scoped ------------------------------------


class TestConsumerConfidenceReportLink:
    """A State Water Board service. A non-CA PWSID would compose a 404 that looks
    authoritative, which is worse than offering nothing."""

    def test_the_link_is_present_for_a_california_system(
        self, client_in, sampled_system
    ):
        html = client_in.get(
            reverse("drinking:result_detail", args=[sampled_system["numeric"].pk])
        ).content.decode()
        assert "ear.waterboards.ca.gov" in html
        assert "PwsID=CA2410009&amp;Year=2024" in html, (
            "the link does not carry this system and this sample's year"
        )
        assert 'rel="noopener"' in html

    def test_the_link_is_worded_as_the_annual_report_not_this_samples_lab_sheet(
        self, client_in, sampled_system
    ):
        text = _squash(
            client_in.get(
                reverse("drinking:result_detail", args=[sampled_system["numeric"].pk])
            ).content.decode()
        )
        assert "Consumer Confidence Report" in text
        assert "not this sample's own laboratory sheet" in text

    def test_the_link_is_absent_for_a_non_california_system(
        self, client_in, sampled_system
    ):
        system = sampled_system["system"]
        system.pwsid = "NM3510009"
        system.save()
        html = client_in.get(
            reverse("drinking:result_detail", args=[sampled_system["numeric"].pk])
        ).content.decode()
        assert "ear.waterboards.ca.gov" not in html, (
            "a California-only viewer was offered for a New Mexico system"
        )


# -- 9. Query counts ---------------------------------------------------------


class TestNoNPlusOne:
    """The two pages that embed a table stay flat as that table grows.

    Pinned as "the count measured on a small dataset still holds on a larger
    one" rather than as a bare literal, which any unrelated middleware change
    would break. The fixture supplies the number; the assertion is that adding
    rows does not move it.
    """

    def _count(self, client_in, url):
        with CaptureQueriesContext(connection) as ctx:
            assert client_in.get(url).status_code == 200
        return len(ctx.captured_queries)

    def test_facility_detail_does_not_query_per_sampling_point(
        self, client_in, sampled_system, django_assert_num_queries
    ):
        url = reverse(
            "drinking:facility_detail", args=[sampled_system["facility"].pk]
        )
        baseline = self._count(client_in, url)

        for _ in range(10):
            SamplingPointFactory(facility=sampled_system["facility"])

        with django_assert_num_queries(baseline):
            assert client_in.get(url).status_code == 200

    def test_sampling_point_detail_does_not_query_per_result(
        self, client_in, sampled_system, django_assert_num_queries
    ):
        url = reverse(
            "drinking:sampling_point_detail", args=[sampled_system["point"].pk]
        )
        baseline = self._count(client_in, url)

        for day in range(2, 12):
            event = SampleEventFactory(
                sampling_point=sampled_system["point"], sample_date=date(2024, 5, day)
            )
            SampleResultFactory(event=event, analyte=AnalyteFactory())

        with django_assert_num_queries(baseline):
            assert client_in.get(url).status_code == 200
