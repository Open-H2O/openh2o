# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 78-02 — the drinking domain's three read surfaces.

Four things here are load-bearing enough to state plainly.

**A presence/absence result must never render as a number.** 78-01 made that
unrepresentable in the database; this file asserts the same thing at the last
place it can still go wrong — the template. "Absent" must read as *Absent*, not
as 0, not as "< RL", and a non-detect must read as a bound rather than as its
reporting level.

**No verdicts.** The platform prepares submissions and does not determine
compliance, so no page here may compare a result against a RegulatoryLimit or
color a row by one. Asserted directly, because the temptation to add a red cell
is exactly the kind of "helpful" change that would slip through review.

**The quality-to-quantity join is visible.** A facility carrying a well links to
that well's detail page: one physical feature, sampled on this side and metered
on the other.

**One query per page, not one per row.** The sampling-point and result lists are
the two surfaces that grow without bound, so both are pinned with
``django_assert_num_queries``.
"""

from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking.models import SampleResult
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


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinkview{n}")
    email = factory.Sequence(lambda n: f"drinkview{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def sampled_system(db):
    """One system, one well-backed facility, one point, three kinds of result.

    The three results are the whole point: a plain numeric, a non-detect, and a
    presence/absence. Every rendering assertion below leans on all three being
    present at once, so a template that handles one kind by accident cannot pass.
    """
    well = WellFactory(name="Orchard Supply Well")
    system = WaterSystemFactory(pwsid="CA1910067", name="Cedar Grove Water District")
    facility = SystemFacilityFactory(
        system=system, facility_id="WL-001", name="Orchard Wellhead", well=well
    )
    point = SamplingPointFactory(
        ps_code="CA1910067_WL-001_001", name="Wellhead Tap", facility=facility
    )
    event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))

    nitrate = AnalyteFactory(name="Nitrate")
    arsenic = AnalyteFactory(name="Arsenic")
    coliform = AnalyteFactory(name="Total Coliforms")

    numeric = SampleResultFactory(
        event=event, analyte=nitrate, result_kind="numeric",
        result_value=Decimal("3.200000"), unit="mg/L",
        method="EPA 300.0", lab_name="Valley Analytical",
    )
    non_detect = SampleResultFactory(
        event=event, analyte=arsenic, result_kind="numeric",
        result_value=None, less_than_rl=True,
        reporting_level=Decimal("0.002000"), unit="mg/L",
    )
    presence = SampleResultFactory(
        event=event, analyte=coliform, result_kind="presence_absence",
        result_value=None, presence=False, unit="",
    )
    return {
        "well": well, "system": system, "facility": facility, "point": point,
        "event": event, "numeric": numeric, "non_detect": non_detect,
        "presence": presence,
    }


# -- Reachability ------------------------------------------------------------


class TestPagesRender:
    @pytest.mark.parametrize(
        "url_name",
        ["drinking:overview", "drinking:sampling_points", "drinking:results"],
    )
    def test_page_returns_200(self, client_in, sampled_system, url_name):
        assert client_in.get(reverse(url_name)).status_code == 200

    @pytest.mark.parametrize(
        "url_name",
        ["drinking:overview", "drinking:sampling_points", "drinking:results"],
    )
    def test_page_requires_login(self, db, url_name):
        response = Client().get(reverse(url_name))
        assert response.status_code == 302
        assert "/login" in response["Location"] or "accounts" in response["Location"]

    @pytest.mark.parametrize(
        "url_name",
        ["drinking:overview", "drinking:sampling_points", "drinking:results"],
    )
    def test_page_renders_with_no_data_at_all(self, client_in, url_name):
        """The empty path renders rather than 500-ing on a missing system."""
        response = client_in.get(reverse(url_name))
        assert response.status_code == 200
        # The onboarding copy names the two real ways in, and deliberately does
        # not link a CSV import that 78-03 has not built yet.
        text = _squash(response.content.decode())
        assert "Django admin" in text
        assert "next update" in text
        assert "infrastructure/import" not in text, (
            "The empty state links an import URL that does not exist until 78-03"
        )


# -- Honest rendering --------------------------------------------------------


class TestResultsRenderHonestly:
    """The result column says what the lab said, in the lab's own terms."""

    def test_numeric_result_shows_value_and_unit(self, client_in, sampled_system):
        """3.2, not 3.200000.

        The column stores six decimal places, so rendering the stored value raw
        would put six significant figures on screen that nobody measured.
        """
        row = _row_containing(
            client_in.get(reverse("drinking:results")).content.decode(), "Nitrate"
        )
        assert "3.2 mg/L" in row
        assert "3.200000" not in row

    def test_non_detect_shows_a_bound_not_a_value(self, client_in, sampled_system):
        # "< 0.002 mg/L" — a bound. The bare reporting level would be a claim
        # the lab never made.
        row = _row_containing(
            client_in.get(reverse("drinking:results")).content.decode(), "Arsenic"
        )
        assert "&lt; 0.002 mg/L" in row

    def test_presence_absence_shows_a_word_not_a_number(self, client_in, sampled_system):
        row = _row_containing(
            client_in.get(reverse("drinking:results")).content.decode(),
            "Total Coliforms",
        )
        assert "Absent" in row

    def test_a_round_value_never_renders_in_scientific_notation(
        self, client_in, sampled_system
    ):
        """Decimal.normalize() alone turns 100.000000 into 1E+2.

        Total coliform's MCL is stored as a percentage and values like 100 are
        ordinary here, so this is a live trap rather than a theoretical one.
        """
        sampled_system["numeric"].result_value = Decimal("100.000000")
        sampled_system["numeric"].save()
        row = _row_containing(
            client_in.get(reverse("drinking:results")).content.decode(), "Nitrate"
        )
        assert "100 mg/L" in row
        assert "E+" not in row

    def test_absent_never_renders_as_zero_or_as_a_non_detect(self, client_in, sampled_system):
        """The specific confusion result_kind exists to prevent.

        'Absent' is not '0', and it is not 'below reporting level' — those are
        three different claims. Only the arsenic row may carry a '<'.
        """
        html = client_in.get(reverse("drinking:results")).content.decode()
        row = _row_containing(html, "Total Coliforms")
        assert "Absent" in row
        assert "&lt;" not in row
        assert ">0<" not in row

    def test_present_renders_as_present(self, client_in, sampled_system):
        sampled_system["presence"].presence = True
        sampled_system["presence"].save()
        html = client_in.get(reverse("drinking:results")).content.decode()
        assert "Present" in _row_containing(html, "Total Coliforms")

    def test_unknown_presence_renders_as_a_dash(self, client_in, sampled_system):
        sampled_system["presence"].presence = None
        sampled_system["presence"].save()
        row = _row_containing(
            client_in.get(reverse("drinking:results")).content.decode(),
            "Total Coliforms",
        )
        assert "—" in row
        assert "Absent" not in row


def _squash(html):
    """Collapse whitespace so a template's line wrapping cannot break a match."""
    return " ".join(html.split())


def _tbody(html):
    """Just the results table's rows.

    Assertions MUST run against this and not the whole page. The results page
    carries an analyte picker and a sampling-point picker, so every analyte name
    in the database appears on the page inside an <option> whether or not it has
    a matching row. A naive `"Nitrate" in html` therefore passes for a filter
    that returned nothing at all — which is exactly backwards.
    """
    assert "<tbody>" in html, "No results table on the page (empty state?)"
    return html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


def _row_containing(html, needle):
    """The single <tr> in the results table holding `needle`."""
    rows = [r for r in _tbody(html).split("<tr") if needle in r]
    assert len(rows) == 1, f"Expected exactly one row containing {needle!r}"
    return rows[0]


# -- Posture: prepare, never determine ---------------------------------------


class TestNoComplianceVerdict:
    def test_no_page_compares_a_result_against_a_limit(self, client_in, sampled_system):
        """A limit existing must not make any page start judging against it.

        The seeded arsenic MCL is deliberately set BELOW the nitrate result, so
        a template that quietly added a comparison would have something to flag.
        Nothing may flag it.
        """
        RegulatoryLimitFactory(
            analyte=sampled_system["numeric"].analyte,
            limit_type="mcl",
            value=Decimal("1.000000"),
            unit="mg/L",
            jurisdiction="federal",
        )
        for url_name in ("drinking:overview", "drinking:sampling_points", "drinking:results"):
            html = client_in.get(reverse(url_name)).content.decode().lower()
            for verdict in ("exceed", "violation", "out of compliance", "non-compliant",
                            "pass/fail", "in compliance"):
                assert verdict not in html, f"{url_name} renders a verdict: {verdict!r}"


# -- The quality-to-quantity join --------------------------------------------


class TestFacilityWellLink:
    def test_facility_links_to_its_well(self, client_in, sampled_system):
        html = client_in.get(reverse("drinking:overview")).content.decode()
        expected = reverse("wells:detail", args=[sampled_system["well"].pk])
        assert f'href="{expected}"' in html
        assert "Orchard Supply Well" in html

    def test_facility_without_a_well_renders_a_dash_not_a_broken_link(
        self, client_in, sampled_system
    ):
        SystemFacilityFactory(
            system=sampled_system["system"], facility_id="DS-001",
            name="Distribution System", facility_type="DS", well=None,
        )
        html = client_in.get(reverse("drinking:overview")).content.decode()
        assert "Distribution System" in html
        assert "/wells/None/" not in html


# -- Query counts ------------------------------------------------------------


class TestNoNPlusOne:
    """Both growing lists stay flat as rows are added.

    Asserted as "the count does not change between a small and a larger
    dataset", which is what actually matters, rather than pinning a brittle
    absolute number that any unrelated middleware change would break.
    """

    def _count(self, client_in, django_assert_num_queries, url):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            assert client_in.get(url).status_code == 200
        return len(ctx.captured_queries)

    def test_result_list_query_count_is_flat(
        self, client_in, sampled_system, django_assert_num_queries
    ):
        url = reverse("drinking:results")
        before = self._count(client_in, django_assert_num_queries, url)

        point = SamplingPointFactory(facility=sampled_system["facility"])
        for day in range(2, 12):
            event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, day))
            SampleResultFactory(event=event, analyte=AnalyteFactory())

        after = self._count(client_in, django_assert_num_queries, url)
        assert after == before, (
            f"Result list went from {before} to {after} queries after adding 10 "
            f"results — a select_related is missing."
        )

    def test_sampling_point_list_query_count_is_flat(
        self, client_in, sampled_system, django_assert_num_queries
    ):
        url = reverse("drinking:sampling_points")
        before = self._count(client_in, django_assert_num_queries, url)

        for _ in range(10):
            SamplingPointFactory(facility=sampled_system["facility"])

        after = self._count(client_in, django_assert_num_queries, url)
        assert after == before, (
            f"Sampling point list went from {before} to {after} queries after "
            f"adding 10 points — a select_related or annotate is missing."
        )

    def test_annotations_are_not_inflated_by_the_join(self, client_in, sampled_system):
        """Counting results through events must not multiply by the event count.

        The point carries ONE event with THREE results. A second join arriving
        later (a filter added with `qs.filter(a) | qs.filter(b)`, say) would
        silently turn that 3 into a 6, and the number would still look plausible.
        """
        html = client_in.get(reverse("drinking:sampling_points")).content.decode()
        row = _row_containing(html, "CA1910067_WL-001_001")
        assert ">3</a>" in row, f"Expected a result count of 3 in: {row}"

    def test_search_filter_does_not_inflate_annotations(self, client_in, sampled_system):
        """Same count with the Q-based search filter applied."""
        html = client_in.get(
            reverse("drinking:sampling_points"), {"q": "WL-001"}
        ).content.decode()
        row = _row_containing(html, "CA1910067_WL-001_001")
        assert ">3</a>" in row


# -- Filters -----------------------------------------------------------------


class TestResultFilters:
    def test_filter_by_analyte(self, client_in, sampled_system):
        analyte = sampled_system["numeric"].analyte
        rows = _tbody(client_in.get(
            reverse("drinking:results"), {"analyte": analyte.pk}
        ).content.decode())
        assert "Nitrate" in rows
        assert "Total Coliforms" not in rows

    def test_filter_by_sampling_point(self, client_in, sampled_system):
        other = SamplingPointFactory(ps_code="CA1910067_DS-001_001")
        event = SampleEventFactory(sampling_point=other, sample_date=date(2024, 7, 1))
        SampleResultFactory(event=event, analyte=AnalyteFactory(name="Lead"))

        rows = _tbody(client_in.get(
            reverse("drinking:results"),
            {"sampling_point": sampled_system["point"].pk},
        ).content.decode())
        assert "Nitrate" in rows
        assert "Lead" not in rows

    def test_filter_by_date_range(self, client_in, sampled_system):
        later = SampleEventFactory(
            sampling_point=sampled_system["point"], sample_date=date(2025, 1, 15)
        )
        SampleResultFactory(event=later, analyte=AnalyteFactory(name="Uranium"))

        rows = _tbody(client_in.get(
            reverse("drinking:results"), {"date_from": "2025-01-01"}
        ).content.decode())
        assert "Uranium" in rows
        assert "Nitrate" not in rows

    def test_unparseable_date_degrades_to_unfiltered_rather_than_500(
        self, client_in, sampled_system
    ):
        """A hand-edited or truncated URL must not be an error page.

        An unparseable value reaching the ORM raises ValidationError -> 500, so
        the view parses first and drops what it cannot read.
        """
        response = client_in.get(
            reverse("drinking:results"), {"date_from": "not-a-date", "date_to": "2025"}
        )
        assert response.status_code == 200
        assert "Nitrate" in _tbody(response.content.decode())

    def test_non_numeric_id_filters_are_ignored(self, client_in, sampled_system):
        response = client_in.get(
            reverse("drinking:results"), {"analyte": "abc", "sampling_point": "'; --"}
        )
        assert response.status_code == 200
        assert "Nitrate" in _tbody(response.content.decode())

    def test_filters_that_match_nothing_say_so_without_onboarding_copy(
        self, client_in, sampled_system
    ):
        """A filtered-to-empty list is not an onboarding moment.

        The operator plainly has data; sending them to "enter records in the
        admin" would be a non-sequitur.
        """
        html = client_in.get(
            reverse("drinking:results"), {"date_from": "2099-01-01"}
        ).content.decode()
        assert "No sample results match these filters." in html
        assert "next update" not in html


class TestSamplingPointFilters:
    def test_search_matches_ps_code_and_name(self, client_in, sampled_system):
        SamplingPointFactory(ps_code="CA1910067_DS-001_001", name="Far End Tap")

        by_code = client_in.get(
            reverse("drinking:sampling_points"), {"q": "WL-001"}
        ).content.decode()
        assert "Wellhead Tap" in by_code
        assert "Far End Tap" not in by_code

        by_name = client_in.get(
            reverse("drinking:sampling_points"), {"q": "Far End"}
        ).content.decode()
        assert "Far End Tap" in by_name
        assert "Wellhead Tap" not in by_name

    def test_filter_by_point_type(self, client_in, sampled_system):
        SamplingPointFactory(
            ps_code="CA1910067_DS-001_001", name="Distribution Tap", point_type="tap"
        )
        html = client_in.get(
            reverse("drinking:sampling_points"), {"point_type": "tap"}
        ).content.decode()
        assert "Distribution Tap" in html
        assert "Wellhead Tap" not in html

    def test_latest_sample_date_is_the_most_recent(self, client_in, sampled_system):
        SampleEventFactory(
            sampling_point=sampled_system["point"], sample_date=date(2025, 3, 9)
        )
        row = _row_containing(
            client_in.get(reverse("drinking:sampling_points")).content.decode(),
            "CA1910067_WL-001_001",
        )
        assert "2025-03-09" in row


# -- Droppability ------------------------------------------------------------


class TestDroppability:
    def test_dropping_drinking_registers_no_routes(self):
        """With the module omitted, its paths simply do not exist.

        Asserted on the resolver rather than a live re-import: Django's URL conf
        is built once at startup, so a dropped module's 404 cannot be observed
        by a test client in the same process.
        """
        from core import modules as mod

        kept = [n for n in mod.ALL_MODULE_NAMES if n != "drinking"]
        specs = mod.url_specs_for(mod.enabled_modules(kept))
        assert ("drinking/", "drinking.urls") not in specs

    def test_dropping_drinking_contributes_no_nav(self):
        from core import modules as mod

        kept = [n for n in mod.ALL_MODULE_NAMES if n != "drinking"]
        sections = mod.nav_sections_for(mod.enabled_modules(kept))
        names = {e.url_name for s in sections for e in s.entries}
        assert not any(n.startswith("drinking:") for n in names)
