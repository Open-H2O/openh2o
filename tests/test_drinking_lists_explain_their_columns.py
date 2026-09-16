# SPDX-License-Identifier: AGPL-3.0-or-later
"""
143-08 Task 5 -- guards for the register rows this plan closes on the three
drinking lists, the facility page's crumb and well field, the overview's
records card, and the sampling-point builder.

One guard per row, each a VALUE assertion against a typed fixture, never a
re-derivation of what the template computes. Every guard here was observed
RED against the pre-change tree (commit 7c368d1, before this plan's templates
and views existed) before it went green; the RED assertion text is quoted in
143-08-EVIDENCE.md.

Rows: R-063 (the facilities list's empty cells) and ISS-135 (the facilities
filters sent `q` twice); R-067 and R-068 (the sampling-points list); R-064
and R-066 (the facility page's crumb and well field); R-062 (the overview's
records card); R-073 (the sampling-point builder as one form and one grouped
table).
"""

import re
from decimal import Decimal
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking.models import SampleResult, SamplingPoint
from tests.factories import (
    AnalyteFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    WellFactory,
)

ROOT = Path(__file__).resolve().parent.parent


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention -- every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinkcols{n}")
    email = factory.Sequence(lambda n: f"drinkcols{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _squash(html):
    """Collapse whitespace so a template's line wrapping cannot break a match."""
    return " ".join(html.split())


def _tbody(html):
    """Just the rows of the page's FIRST table."""
    assert "<tbody>" in html, "No table on the page"
    return html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


def _row_containing(html, needle):
    """The single <tr> in the first table holding `needle`."""
    rows = [r for r in _tbody(html).split("<tr") if needle in r]
    assert len(rows) == 1, f"Expected exactly one row containing {needle!r}"
    return rows[0]


# -- R-063 / ISS-135: the facilities list -------------------------------


@pytest.fixture
def facility_mix(db):
    """A source with a published water type, a treatment plant, and a well
    with no metered-well link.

    Matches what the local stack measures: every well is a source and every
    one carries a water type; no treatment plant and no distribution
    facility carries either.
    """
    system = WaterSystemFactory(pwsid="CA1010777", name="Ridge Water District")
    source = SystemFacilityFactory(
        system=system, facility_id="001", name="North Well",
        facility_type="WL", is_source=True, water_type="GW", well=None,
    )
    plant = SystemFacilityFactory(
        system=system, facility_id="002", name="Ridge Treatment Plant",
        facility_type="TP", is_source=False, water_type="", well=None,
    )
    distribution = SystemFacilityFactory(
        system=system, facility_id="003", name="DISTRIBUTION SYSTEM",
        facility_type="DS", is_source=False, water_type="", well=None,
    )
    return {
        "system": system, "source": source, "plant": plant,
        "distribution": distribution,
    }


class TestFacilitiesListNamesWhyACellIsEmpty:
    def test_a_source_facility_reads_its_published_water_type(
        self, client_in, facility_mix
    ):
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        row = _row_containing(html, "North Well")
        assert "Ground water" in row

    def test_a_treatment_plant_marks_water_type_and_well_not_applicable(
        self, client_in, facility_mix
    ):
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        row = _row_containing(html, "Ridge Treatment Plant")
        assert row.count("Not applicable") == 2, (
            "a treatment plant's Water Type and Well cells should both say "
            "the field does not apply, distinct from an unset field"
        )

    def test_a_well_with_no_link_reads_not_linked(self, client_in, facility_mix):
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        row = _row_containing(html, "North Well")
        assert "Not linked" in row
        assert "Not recorded" not in row, (
            "a well with no link is a field that applies and is unset, "
            "distinct from a field that does not apply"
        )

    def test_the_card_head_names_the_three_counts(self, client_in, facility_mix):
        text = _squash(
            client_in.get(reverse("drinking:facilities")).content.decode()
        )
        assert (
            "3 facilities: 1 sources, 1 treatment plants, 1 distribution"
        ) in text


class TestISS135FacilitiesFilterSendsQOnce:
    """The Type and Status selects each included an ``hx-include`` reading
    ``[name='q']`` -- an attribute selector that also matched the global
    nav's own ``#global-search-input``, so a filter change sent ``q`` twice,
    the second copy empty, and the search box's own value was overwritten."""

    def test_facilities_template_carries_no_name_q_hx_include(self):
        text = (ROOT / "templates/drinking/facilities.html").read_text()
        stripped = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", text, flags=re.S
        )
        assert "[name='q']" not in stripped, (
            "an hx-include by attribute selector reaches the global nav's "
            "own search input too, sending q twice"
        )


# -- R-067 / R-068: the sampling-points list -----------------------------


@pytest.fixture
def point_with_facility(db):
    system = WaterSystemFactory(pwsid="CA1010778", name="Ridge Water District")
    facility = SystemFacilityFactory(
        system=system, facility_id="004", name="Ridge Wellhead",
        facility_type="WL",
    )
    point = SamplingPointFactory(
        ps_code="CA1010778_004_001", name="Wellhead Tap", facility=facility,
    )
    return {"system": system, "facility": facility, "point": point}


class TestSamplingPointsListLinksItsFacility:
    def test_the_facility_cell_holds_a_link_to_the_facility_page(
        self, client_in, point_with_facility
    ):
        html = client_in.get(reverse("drinking:sampling_points")).content.decode()
        row = _row_containing(html, "Wellhead Tap")
        expected = reverse(
            "drinking:facility_detail", args=[point_with_facility["facility"].pk]
        )
        assert f'href="{expected}"' in row


class TestSamplingPointsListNamesItsCount:
    def test_a_points_result_count_renders_under_a_head_naming_it(
        self, client_in, point_with_facility
    ):
        from datetime import date

        point = point_with_facility["point"]
        event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
        analyte = AnalyteFactory()
        # bulk_create, not the factory loop: 1,234 rows through factory_boy's
        # one-INSERT-per-object path would make this guard the slowest test
        # in the file for no reason -- the fixture only needs the count to be
        # real, never a distinct analyte or event per row.
        SampleResult.objects.bulk_create(
            [
                SampleResult(
                    event=event, analyte=analyte, result_kind="numeric",
                    result_value=Decimal("1.000000"), unit="MG/L",
                )
                for _ in range(1234)
            ]
        )
        html = client_in.get(reverse("drinking:sampling_points")).content.decode()
        row = _row_containing(html, "Wellhead Tap")
        assert "1,234" in row
        assert '<span class="th-stack">Sample results</span>' in html, (
            "the count column's header was not renamed from Results"
        )


# -- R-064 / R-066: the facility page's crumb and well field -------------


@pytest.fixture
def facility_pages(db):
    well = WellFactory(name="Alpha Supply Well")
    system = WaterSystemFactory(pwsid="CA1010779", name="Ridge Water District")
    wl_facility = SystemFacilityFactory(
        system=system, facility_id="005", name="Ridge Wellhead",
        facility_type="WL", well=well,
    )
    tp_facility = SystemFacilityFactory(
        system=system, facility_id="006", name="Ridge Treatment Plant",
        facility_type="TP", is_source=False, well=None,
    )
    return {"system": system, "wl": wl_facility, "tp": tp_facility}


def _breadcrumb(html):
    """Just the <nav class="breadcrumb">...</nav> block.

    The sidebar nav links to ``drinking:facilities`` on every drinking page
    (it is one of the module's own list links), so an unscoped search for
    that href passes whether or not the CRUMB itself carries it. Only the
    breadcrumb block is what R-064 changed.
    """
    match = re.search(
        r'<nav class="breadcrumb".*?</nav>', html, re.S
    )
    assert match, "no breadcrumb nav on the page"
    return match.group(0)


class TestFacilityPageCrumbAndWellField:
    def test_the_breadcrumb_links_to_the_facilities_list(
        self, client_in, facility_pages
    ):
        html = client_in.get(
            reverse("drinking:facility_detail", args=[facility_pages["wl"].pk])
        ).content.decode()
        assert f'href="{reverse("drinking:facilities")}"' in _breadcrumb(html)

    def test_a_well_type_facility_renders_the_metered_well_field(
        self, client_in, facility_pages
    ):
        html = client_in.get(
            reverse("drinking:facility_detail", args=[facility_pages["wl"].pk])
        ).content.decode()
        assert "Metered well" in html
        assert "Alpha Supply Well" in html

    def test_a_treatment_plant_renders_no_well_field_at_all(
        self, client_in, facility_pages
    ):
        html = client_in.get(
            reverse("drinking:facility_detail", args=[facility_pages["tp"].pk])
        ).content.decode()
        assert "Metered well" not in html, (
            "the field does not apply to a treatment plant and should not print"
        )


# -- R-062: the overview's records card -----------------------------------


@pytest.fixture
def one_system(db):
    return WaterSystemFactory(pwsid="CA1010780", name="Ridge Water District")


class TestOverviewNamesItsRecordsCard:
    def test_the_three_tiles_sit_under_a_head_naming_them(
        self, client_in, one_system
    ):
        html = client_in.get(reverse("drinking:overview")).content.decode()
        assert (
            '<h2 class="section-header mt-lg">Records for this system</h2>'
        ) in html
        for url_name in (
            "drinking:facilities", "drinking:sampling_points", "drinking:results",
        ):
            assert reverse(url_name) in html, (
                f"the tile linking to {url_name} did not survive the head's "
                "own card"
            )


# -- R-073: the builder as one form and one grouped table ----------------


@pytest.fixture
def builder_system(db):
    system = WaterSystemFactory(pwsid="CA1010781", name="Ridge Water District")
    with_points = SystemFacilityFactory(
        system=system, facility_id="007", name="Sampled Well",
        facility_type="WL", is_source=True,
    )
    without_points = SystemFacilityFactory(
        system=system, facility_id="008", name="Unsampled Plant",
        facility_type="TP", is_source=False,
    )
    point = SamplingPointFactory(
        ps_code="CA1010781_007_001", name="Tap 1", facility=with_points,
    )
    return {
        "system": system, "with_points": with_points,
        "without_points": without_points, "point": point,
    }


class TestBuilderIsOneFormOneTable:
    def test_one_form_posts_to_the_add_endpoint(self, client_in, builder_system):
        html = client_in.get(
            reverse("drinking:onboard_points", args=[builder_system["system"].pwsid])
        ).content.decode()
        add_url = reverse(
            "drinking:onboard_points_add", args=[builder_system["system"].pwsid]
        )
        assert html.count(f'hx-post="{add_url}"') == 1, (
            "expected exactly one add form on the page"
        )

    def test_the_select_carries_one_option_per_facility_sources_first(
        self, client_in, builder_system
    ):
        html = client_in.get(
            reverse("drinking:onboard_points", args=[builder_system["system"].pwsid])
        ).content.decode()
        select = re.search(
            r'<select id="point-facility".*?</select>', html, re.S
        ).group(0)
        options = re.findall(r'<option value="(\d+)"', select)
        assert options == [
            str(builder_system["with_points"].pk),
            str(builder_system["without_points"].pk),
        ], "the source facility should list before the non-source one"

    def test_a_post_adds_a_row_under_its_facilitys_group(
        self, client_in, builder_system
    ):
        add_url = reverse(
            "drinking:onboard_points_add", args=[builder_system["system"].pwsid]
        )
        response = client_in.post(
            add_url,
            {
                "facility": builder_system["without_points"].pk,
                "point_number": "900", "name": "New Tap",
            },
        )
        assert response.status_code == 200
        assert SamplingPoint.objects.filter(ps_code="CA1010781_008_900").exists()

        html = response.content.decode()
        tbody = _tbody(html)
        assert tbody.count('<tr class="row-group">') == 2, (
            "the whole table should regenerate with both facilities' groups, "
            "not one row spliced into the old one"
        )
        assert tbody.index("Unsampled Plant") < tbody.index("New Tap"), (
            "the new point's row should sit under ITS OWN facility's group"
        )

    def test_a_duplicate_post_returns_already_listed_and_the_table(
        self, client_in, builder_system
    ):
        add_url = reverse(
            "drinking:onboard_points_add", args=[builder_system["system"].pwsid]
        )
        client_in.post(
            add_url,
            {
                "facility": builder_system["without_points"].pk,
                "point_number": "900", "name": "First",
            },
        )
        response = client_in.post(
            add_url,
            {
                "facility": builder_system["without_points"].pk,
                "point_number": "900", "name": "Second",
            },
        )
        assert response.status_code == 200
        assert b"already listed" in response.content
        assert b'id="points-listed"' in response.content
