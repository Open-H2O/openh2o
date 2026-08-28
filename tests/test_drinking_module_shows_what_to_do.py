# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 123: the drinking module says what to DO, not only what a system IS.

Before this phase the module described an inventory and routed three counts to
three lists. It never named a next step, `/drinking/facilities/` had no map at
all, and two empty states sent an operator to the Django admin — a screen that
is not the answer and that most operators cannot reach.

Every assertion here was proved to fail against the pre-change tree before it
was accepted. That is the standard this file exists to hold, and it is not
ceremony: 123-01 found four of the previous plan's own verification figures
wrong while the build itself was right, because each of the four was a check
that could only pass.

**A test here may never mandate a domain description** (BLOCKING, ISS-129).
Everything below asserts on structure, links, computed counts and the absence of
forbidden literals. Not one of them requires a sentence explaining what a
facility, a sample or a source IS — three tests that did exactly that reverted
every hand correction on the next run.
"""
import html as html_module
from html.parser import HTMLParser

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)

#: Somewhere in Merced, so a coordinate that survives into the page reads as a
#: real place rather than the (0, 0) default. Same constant, same reason, as
#: tests/test_drinking_map.py.
MERCED = (-120.4829, 37.3022)

#: The demonstration's own coverage figures. If any of these ever appears in a
#: rendered page, someone typed a number into a template that is true on exactly
#: one deployment. The 21/21 pair is a coincidence of the pinned data and
#: nothing holds it.
FORBIDDEN_LITERALS = ("21 of 61", "21 of 27", "21 of the 61")


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"whattodo{n}")
    email = factory.Sequence(lambda n: f"whattodo{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _point(offset=0.0):
    from django.contrib.gis.geos import Point

    return Point(MERCED[0] + offset, MERCED[1] + offset, srid=4326)


def _squash(html):
    """Collapse whitespace so a template's line wrapping cannot break a match."""
    return " ".join(html.split())


def _get_htmx(client, route, **params):
    """The partial the page's own controls actually fetch.

    Load-bearing, and it is the check that was missing. Four controls on
    `/drinking/facilities/` are `hx-target="#results"`, so typing in the search
    box re-renders ONLY `_facility_results.html`. The Django test client sends
    no `HX-Request` header, so every assertion written with a plain
    `client.get(url, {"q": ...})` exercises the URL path and never the
    interactive one — which is how UAT-001 survived a full guard suite, a
    browser pass and a human checkpoint. Anything the operator must still be
    able to read after a keystroke has to be asserted through HERE.
    """
    response = client.get(reverse(route), params, headers={"hx-request": "true"})
    return html_module.unescape(_squash(response.content.decode()))


def _get(client, route, **params):
    """Squashed AND entity-decoded page source.

    The unescape is load-bearing for the step eyebrows: the templates write
    `&middot;` and `&mdash;`, so an assertion on the characters an operator
    actually reads would otherwise fail against markup that is perfectly
    correct. Decoding here keeps every assertion in this file written the way
    the page reads.
    """
    return html_module.unescape(
        _squash(client.get(reverse(route), params).content.decode())
    )


@pytest.fixture
def mapped_system(db):
    """One system, three facilities (two located), four sampling points.

    Deliberately none of the demonstration's counts: 3 / 4 / 0 against Merced's
    61 / 27 / 22,367. A numeral typed into a template passes on staging and
    fails here, which is the entire point of the fixture.
    """
    system = WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
    well_a = SystemFacilityFactory(
        system=system, facility_id="010", name="Well 08",
        facility_type="WL", location=_point(),
    )
    well_b = SystemFacilityFactory(
        system=system, facility_id="020", name="Well 12",
        facility_type="WL", location=_point(0.01),
    )
    unlocated = SystemFacilityFactory(
        system=system, facility_id="DST", name="DISTRIBUTION SYSTEM",
        facility_type="DS", location=None,
    )
    points = [
        SamplingPointFactory(ps_code="CA2410009_010_001", facility=well_a),
        SamplingPointFactory(ps_code="CA2410009_010_002", facility=well_a),
        SamplingPointFactory(ps_code="CA2410009_020_001", facility=well_b),
        SamplingPointFactory(ps_code="CA2410009_DST_LCR", facility=unlocated),
    ]
    return {
        "system": system, "well_a": well_a, "well_b": well_b,
        "unlocated": unlocated, "points": points,
    }


# -- The anchor parser -------------------------------------------------------


class _AnchorAudit(HTMLParser):
    """Records every `<a>`'s attributes, its nesting depth, and stat-card tags.

    Written against the stdlib parser on purpose: this suite has no BeautifulSoup
    and a regex cannot see nesting, which is the one thing group 1 has to check.

    `<a>` is declared non-void in HTML, so the parser reports open and close
    honestly; the depth counter is what catches an anchor inside an anchor.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.nested = []
        self.anchors = []
        #: (href, {classes}) for every anchor, so an assertion can be scoped to
        #: the element it is actually about. This is load-bearing: the sidebar
        #: registers an "Onboard System" nav entry (core/modules.py:856), so a
        #: bare `reverse("drinking:onboard") in html` is satisfied by the NAV on
        #: every drinking page and proves nothing about an empty state. Three
        #: assertions here passed against the pre-change tree for exactly that
        #: reason before being scoped.
        self.by_class = []
        #: (tag_name, href_or_None, style_attr) for every `stat-card` element.
        self.stat_cards = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if "stat-card" in classes:
            self.stat_cards.append((tag, attrs.get("href"), attrs.get("style") or ""))
        if tag == "a":
            if self.depth > 0:
                self.nested.append(attrs.get("href"))
            self.depth += 1
            self.anchors.append(attrs.get("href"))
            self.by_class.append((attrs.get("href"), set(classes)))

    def handle_endtag(self, tag):
        if tag == "a" and self.depth > 0:
            self.depth -= 1


def _audit(client, route, **params):
    parser = _AnchorAudit()
    parser.feed(client.get(reverse(route), params).content.decode())
    return parser


def _hrefs_with_class(client, route, css_class, **params):
    """Every anchor destination carrying `css_class`, and nothing else.

    The scoping the sidebar makes necessary — see `_AnchorAudit.by_class`.
    """
    return {
        href
        for href, classes in _audit(client, route, **params).by_class
        if css_class in classes
    }


# -- 1. The whole stat tile is the anchor ------------------------------------


class TestTheStatTileIsTheTarget:
    """The page always advertised the affordance and honoured 40% of it.

    `.card-raised:hover` lights the entire tile; only the digits navigated. These
    two assertions are what stops the next edit quietly shrinking the target
    back, which would look identical on a screenshot.
    """

    def test_every_stat_card_is_itself_an_anchor(self, client_in, mapped_system):
        audit = _audit(client_in, "drinking:overview")
        assert len(audit.stat_cards) == 3, (
            f"expected three stat tiles, parsed {len(audit.stat_cards)}"
        )
        for tag, href, _ in audit.stat_cards:
            assert tag == "a", (
                f"a stat tile is a <{tag}>, so only part of it navigates"
            )
            assert href, "a stat tile is an anchor with no destination"

    def test_the_three_tiles_route_to_the_three_lists(self, client_in, mapped_system):
        hrefs = {
            href for _, href, _ in _audit(client_in, "drinking:overview").stat_cards
        }
        assert hrefs == {
            reverse("drinking:facilities"),
            reverse("drinking:sampling_points"),
            reverse("drinking:results"),
        }

    def test_the_tile_anchor_does_not_underline_its_label(
        self, client_in, mapped_system
    ):
        """Found on staging at 1440x900, after the change was already built.

        An `<a>` underlines by default and paints that decoration through its
        in-flow descendants, so wrapping the tile underlined "Facilities",
        "Sampling points" and "Sample results" — labels that have never carried
        one. The mock-up measurement in the plan reported the tile change
        pixel-identical and did not show this.

        Asserted on the attribute, because a Django test renders markup and
        cannot read a computed style. That is the honest limit of this check:
        it catches the property being deleted, not a new rule elsewhere
        re-introducing an underline.
        """
        for tag, _, style in _audit(client_in, "drinking:overview").stat_cards:
            assert "text-decoration" in style.replace(" ", "") or "none" in style, (
                f"a <{tag}> stat tile lost its text-decoration reset, so its "
                "label underlines"
            )
            assert "none" in style.split("text-decoration")[-1]

    def test_no_anchor_is_nested_inside_another(self, client_in, mapped_system):
        """Invalid HTML, and it fails INVISIBLY.

        A browser reparents the inner anchor out of the outer one, so the
        tile-wide target silently collapses to the digits again with nothing
        wrong to look at.
        """
        audit = _audit(client_in, "drinking:overview")
        assert audit.nested == [], (
            f"anchors nested inside anchors: {audit.nested}"
        )


# -- 2. The facilities map ---------------------------------------------------


class TestTheFacilitiesMapExists:
    def test_the_host_is_the_facilities_id(self, client_in, mapped_system):
        html = _get(client_in, "drinking:facilities")
        assert 'id="drinking-facilities-map"' in html

    def test_the_sampling_point_map_id_is_not_reused(self, client_in, mapped_system):
        """`drinking-overview-map` belongs to the OTHER page, and a pair of

        existing assertions in tests/test_drinking_map.py depends on it: one
        requires it absent from a page, one requires it present. Reusing the id
        here breaks that pair in opposite directions.
        """
        html = _get(client_in, "drinking:facilities")
        assert 'id="drinking-overview-map"' not in html

    def test_the_map_host_sits_outside_the_results_container(
        self, client_in, mapped_system
    ):
        """Four controls swap `#results` wholesale, including search keyup.

        A map inside it is torn down and rebuilt on every keystroke. Position in
        the source is the observable form of that rule.
        """
        html = _get(client_in, "drinking:facilities")
        host = html.index('id="drinking-facilities-map"')
        results = html.index('id="results"')
        assert host < results, (
            "the map host is inside #results, so typing in the search box "
            "destroys it"
        )

    def test_the_page_loads_the_map_library(self, client_in, mapped_system):
        """This page shipped no map library at all before Phase 123."""
        html = _get(client_in, "drinking:facilities")
        assert "maplibre-gl.js" in html
        # Prefix only, no extension: WhiteNoise's manifest storage is active
        # under test settings and serves `js/map-core.<hash>.js`, so matching
        # the literal filename would fail on a correct page.
        assert "js/map-core" in html
        assert "css/map-engine" in html


class TestTheCoverageSentenceIsComputed:
    def test_it_counts_what_is_actually_located(self, client_in, mapped_system):
        """Add a location; the page must say a different number."""
        html = _get(client_in, "drinking:facilities")
        assert "2 of the 3" in html, (
            "the page does not state the facility coverage it actually has"
        )

        mapped_system["unlocated"].location = _point(0.02)
        mapped_system["unlocated"].save(update_fields=["location"])

        html = _get(client_in, "drinking:facilities")
        assert "3 of the 3" in html, "the coverage sentence is a hardcoded literal"

    def test_it_says_why_the_rest_are_missing(self, client_in, mapped_system):
        """The gap is a fact about the public record, not a defect here.

        "Groundwater sources", never "source wells": the droppability vocabulary
        gate fails a kept page that says "wells" on a deployment without the
        Wells module, and it is right to — it cannot tell this module's WL
        facility type from that module's section.
        """
        html = _get(client_in, "drinking:facilities").lower()
        assert "groundwater sources" in html
        assert "gama" in html

    def test_no_hardcoded_demonstration_numbers(self, client_in, mapped_system):
        html = _get(client_in, "drinking:facilities")
        for literal in FORBIDDEN_LITERALS:
            assert literal not in html


class TestTheUnmappedPageIsASentence:
    """An Envirofacts-onboarded system has NO coordinates at all.

    So zero-mapped is the common case for a new operator, and a 380px empty grey
    rectangle is worse than an honest sentence.
    """

    @pytest.fixture
    def unmapped_system(self, db):
        system = WaterSystemFactory(pwsid="CA0000001", name="Newly Onboarded Water")
        SystemFacilityFactory(
            system=system, facility_id="010", facility_type="WL", location=None
        )
        return system

    def test_no_map_host_is_rendered(self, client_in, unmapped_system):
        html = _get(client_in, "drinking:facilities")
        assert 'id="drinking-facilities-map"' not in html, (
            "an empty grey rectangle was rendered instead of an explanation"
        )

    def test_it_says_so_and_names_the_publisher(self, client_in, unmapped_system):
        html = _get(client_in, "drinking:facilities").lower()
        assert "no facility in this inventory has a published location" in html
        assert "groundwater sources" in html
        assert "envirofacts" in html


# -- 3. The sentence names the divergence, and only when there is one ---------


class TestTheMapIsUnfilteredAndSaysSo:
    """Two assertions pointing opposite ways.

    A clause that is ALWAYS present fails just as loudly as one that never is —
    which matters, because "always present" is what a careless edit produces and
    it reads perfectly well on the one page anybody looks at.
    """

    def test_the_divergence_clause_appears_under_a_filter(
        self, client_in, mapped_system
    ):
        html = _get(client_in, "drinking:facilities", q="Well 08")
        assert "It is not filtered" in html
        assert "still drawing every located facility" in html

    def test_the_divergence_clause_is_absent_with_no_filter(
        self, client_in, mapped_system
    ):
        html = _get(client_in, "drinking:facilities")
        assert "It is not filtered" not in html, (
            "the divergence clause renders when nothing diverges"
        )

    def test_the_clause_names_the_count_the_list_is_showing(
        self, client_in, mapped_system
    ):
        """Two of three facilities match; the clause must say two, not three."""
        html = _get(client_in, "drinking:facilities", q="Well")
        assert "showing 2 facilities" in html

    def test_a_type_filter_alone_raises_the_clause(self, client_in, mapped_system):
        """Not just `q` — all three filters diverge from the map the same way."""
        html = _get(client_in, "drinking:facilities", facility_type="DS")
        assert "It is not filtered" in html

    def test_the_clause_reaches_the_htmx_partial_too(self, client_in, mapped_system):
        """UAT-001. The sentence must survive the path an operator actually uses.

        Typing in the search box swaps `#results` alone. Before this, the
        sentence lived outside that container and never re-rendered: the table
        dropped to 6 rows while it still said "21 of the 61" and the map still
        drew 21 dots, with nothing naming the mismatch — the exact confusion
        the clause exists to prevent, invisible on a full `?q=` load.
        """
        partial = _get_htmx(client_in, "drinking:facilities", q="Well")
        assert "It is not filtered" in partial, (
            "the divergence clause does not reach the htmx partial, so it never "
            "appears when an operator types in the search box"
        )
        assert "showing 2 facilities" in partial

    def test_the_htmx_partial_states_the_coverage_and_no_clause_unfiltered(
        self, client_in, mapped_system
    ):
        """The other direction, through the same path."""
        partial = _get_htmx(client_in, "drinking:facilities")
        assert "2 of the 3" in partial
        assert "It is not filtered" not in partial

    def test_the_htmx_partial_never_carries_the_map_host(
        self, client_in, mapped_system
    ):
        """The half of the split that must NOT move.

        A map inside `#results` is destroyed and rebuilt on every keystroke. If
        the host ever appears in this partial, that is what has happened.
        """
        assert 'id="drinking-facilities-map"' not in _get_htmx(
            client_in, "drinking:facilities"
        )

    def test_the_geojson_ignores_every_filter(self, client_in, mapped_system):
        """The endpoint takes no parameters, and this proves it still doesn't."""
        plain = client_in.get(reverse("drinking:facilities_geojson")).content
        filtered = client_in.get(
            reverse("drinking:facilities_geojson"),
            {"q": "Well 08", "facility_type": "WL", "activity_status": "A"},
        ).content
        assert plain == filtered, (
            "the map endpoint grew a filter, so the two numbers now disagree "
            "silently instead of being explained"
        )


# -- 4. The ordered sequence -------------------------------------------------


class TestTheStepSequence:
    STEPS = ("Onboard a water system", "Build its sampling points", "Import lab results")

    def test_the_three_steps_render_in_order(self, client_in, mapped_system):
        html = _get(client_in, "drinking:overview")
        positions = []
        for heading in self.STEPS:
            assert heading in html, f"the page is missing the step {heading!r}"
            positions.append(html.index(heading))
        assert positions == sorted(positions), (
            f"the steps render out of order: {positions}"
        )

    def test_there_are_exactly_three_step_cards(self, client_in, mapped_system):
        html = _get(client_in, "drinking:overview")
        assert html.count('class="card-raised step-card"') == 3

    def test_each_step_links_somewhere(self, client_in, mapped_system):
        """Scoped to `text-accent`, the step cards' own link class.

        NOT to every anchor on the page: the sidebar registers both "Onboard
        System" and the importer, so an unscoped assertion would pass on a page
        with no step cards at all.
        """
        hrefs = _hrefs_with_class(client_in, "drinking:overview", "text-accent")
        assert reverse("drinking:onboard") in hrefs
        assert reverse(
            "drinking:onboard_points", args=[mapped_system["system"].pwsid]
        ) in hrefs
        assert reverse("drinking:import") in hrefs

    def test_the_point_builder_link_carries_this_systems_pwsid(
        self, client_in, mapped_system
    ):
        """The PWSID comes from the loop, so a second system links to itself.

        A deployment carrying a wholesaler alongside its own system must not send
        both cards to whichever one happened to be first.
        """
        second = WaterSystemFactory(pwsid="CA9999999", name="Wholesale Supplier")
        hrefs = _hrefs_with_class(client_in, "drinking:overview", "text-accent")
        assert reverse("drinking:onboard_points", args=["CA2410009"]) in hrefs
        assert reverse("drinking:onboard_points", args=[second.pwsid]) in hrefs

    def test_the_completion_state_is_computed_not_written_down(
        self, client_in, mapped_system
    ):
        """The fixture holds 3 / 4 / 0 — none of the demonstration's numbers.

        A numeral typed into the eyebrow passes on staging and fails right here.
        """
        html = _get(client_in, "drinking:overview")
        assert "Step 1 · done — 3 facilities" in html
        assert "Step 2 · done — 4 points" in html
        assert "Step 3 · not yet" in html

    def test_an_undone_step_says_not_yet(self, client_in, db):
        """A system with no points and no results: two steps outstanding."""
        WaterSystemFactory(pwsid="CA0000002", name="Bare Water System")
        html = _get(client_in, "drinking:overview")
        assert "Step 1 · done" in html
        assert "Step 2 · not yet" in html
        assert "Step 3 · not yet" in html
        assert "done" not in html.split("Step 2")[1].split("Onboard a water")[0]

    def test_the_page_states_no_coverage_literal(self, client_in, mapped_system):
        html = _get(client_in, "drinking:overview")
        for literal in FORBIDDEN_LITERALS:
            assert literal not in html


# -- 5. The empty-state doors ------------------------------------------------


class TestTheEmptyStateDoorsOpen:
    """"Add it in the Django admin" is not a door an operator can walk through.

    Both branches of the sampling-point condition are covered, because that page
    is a two-branch decision rather than a flag flip: the builder needs a PWSID,
    and when no system exists there isn't one.
    """

    def test_an_empty_facilities_page_offers_onboarding(self, client_in, db):
        doors = _hrefs_with_class(client_in, "drinking:facilities", "btn-primary")
        assert reverse("drinking:onboard") in doors
        assert "Add it in the Django admin" not in _get(
            client_in, "drinking:facilities"
        )

    def test_an_empty_point_list_offers_the_builder_when_a_system_exists(
        self, client_in, db
    ):
        WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
        doors = _hrefs_with_class(
            client_in, "drinking:sampling_points", "btn-primary"
        )
        assert reverse("drinking:onboard_points", args=["CA2410009"]) in doors
        assert "Add it in the Django admin" not in _get(
            client_in, "drinking:sampling_points"
        )

    def test_an_empty_point_list_offers_onboarding_when_no_system_exists(
        self, client_in, db
    ):
        doors = _hrefs_with_class(
            client_in, "drinking:sampling_points", "btn-primary"
        )
        assert reverse("drinking:onboard") in doors
        assert not any("/points/" in href for href in doors), (
            "the builder was offered with no system to build on, so its URL "
            "cannot have been given a PWSID"
        )
        assert "Add it in the Django admin" not in _get(
            client_in, "drinking:sampling_points"
        )

    def test_two_systems_fall_back_to_onboarding(self, client_in, db):
        """No honest default with two, and picking the first is silently wrong.

        Scoped to `btn-primary` — the empty state's own button. Unscoped, the
        sidebar's "Onboard System" entry satisfies this on any drinking page,
        which is precisely how this assertion passed against the pre-change
        tree that had no door here at all.
        """
        WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
        WaterSystemFactory(pwsid="CA9999999", name="Wholesale Supplier")
        doors = _hrefs_with_class(
            client_in, "drinking:sampling_points", "btn-primary"
        )
        assert reverse("drinking:onboard") in doors
        assert reverse("drinking:onboard_points", args=["CA2410009"]) not in doors
        assert reverse("drinking:onboard_points", args=["CA9999999"]) not in doors
