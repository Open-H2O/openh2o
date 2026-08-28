# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 100-01 — the facility inventory as its own searchable page.

Two things here are load-bearing enough to state plainly.

**The type filter may not name a module this deployment does not run.**
``FACILITY_TYPE_CHOICES`` carries ("WL", "Well"), ("CW", "Clear Well") and
("WH", "Wellhead"), and a ``<select>`` renders its option TEXT on every load —
empty database included. ``tests/droppability/checks.py::visible_text()`` strips
tags and keeps text, so those options are read as page prose and
``_FORBIDDEN_VOCABULARY`` fails them on a ``wells``-less deployment. The view
therefore builds the options from the types PRESENT in the database, and
``TestTheTypeFilterNamesNoDroppedModule`` asserts that property here — in the
ordinary suite — because the droppability fixture seeds no drinking rows
(ISS-097), which is the same reason 99-02 put the map-layer gate here.

That test imports the REAL ``visible_text`` and ``find_forbidden_word`` from the
droppability harness rather than re-implementing the strip. A private copy would
drift from the gate it is standing in for, leaving this file green while the
thing it guards had moved.

**Note for whoever closes ISS-097.** The empty-database property is the one the
crawl exercises today. A deployment that genuinely holds ``WL`` facilities still
renders the option label *Well* — that word is the drinking domain's own
published facility type, not a reference to the ``wells`` section — so seeding
drinking rows into the droppability fixture would surface that as a vocabulary
failure. It is a copy decision at that point, not a bug here; the option label
would need to read as DDW's own wording rather than the shared English word.

**A filter must not inflate an annotation.** The search is one ``filter()`` with
a ``Q``; ``qs.filter(a) | qs.filter(b)`` would re-join ``sampling_points`` and
double every count. Asserted against a real count, not against the query.
"""

import re

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core import modules as mod
from tests.droppability.checks import (
    FORBIDDEN_VOCABULARY,
    find_forbidden_word,
    visible_text,
)
from tests.factories import (
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    WellFactory,
)

# Same mechanism as tests/test_drinking_map.py, and for the same reason:
# config/urls.py composes its module routes at IMPORT time, so a test that
# narrows OPENH2O_MODULES before the process's first request would permanently
# compose a reduced URLconf for every later test.
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

WITHOUT_WELLS = [name for name in mod.ALL_MODULE_NAMES if name != "wells"]


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinkfac{n}")
    email = factory.Sequence(lambda n: f"drinkfac{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def inventory(db):
    """One system, a mix of types and statuses, and one facility with points."""
    system = WaterSystemFactory(pwsid="CA2410009", name="CITY OF MERCED")
    source = SystemFacilityFactory(
        system=system, facility_id="001", name="North source",
        facility_type="WL", activity_status="A",
    )
    plant = SystemFacilityFactory(
        system=system, facility_id="002", name="Riverside treatment",
        facility_type="TP", activity_status="A",
    )
    retired = SystemFacilityFactory(
        system=system, facility_id="003", name="Old distribution",
        facility_type="DS", activity_status="I",
    )
    for _ in range(3):
        SamplingPointFactory(facility=source)
    return {"system": system, "source": source, "plant": plant, "retired": retired}


def _count_pill(html):
    """The number in the count bar, as an int."""
    return int(re.search(r'count-pill">(\d+)<', html).group(1))


# -- 1. The page ------------------------------------------------------------


class TestTheListRenders:
    def test_it_returns_200_and_lists_every_facility(self, client_in, inventory):
        response = client_in.get(reverse("drinking:facilities"))
        assert response.status_code == 200
        html = response.content.decode()
        assert _count_pill(html) == 3
        for facility_id in ("001", "002", "003"):
            assert facility_id in html

    def test_each_row_opens_the_facility_it_names(self, client_in, inventory):
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        for key in ("source", "plant", "retired"):
            url = reverse("drinking:facility_detail", args=[inventory[key].pk])
            assert url in html, f"the {key} row links nowhere"

    def test_it_paginates_past_fifty(self, client_in, inventory):
        SystemFacilityFactory.create_batch(60, system=inventory["system"])
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        assert _count_pill(html) == 63
        assert html.count('class="data-table-link"') == 50
        second = client_in.get(reverse("drinking:facilities"), {"page": 2})
        assert second.content.decode().count('class="data-table-link"') == 13


# -- 2. Search and filters --------------------------------------------------


class TestSearchAndFilters:
    def test_search_matches_the_facility_id(self, client_in, inventory):
        response = client_in.get(reverse("drinking:facilities"), {"q": "002"})
        assert _count_pill(response.content.decode()) == 1

    def test_search_matches_the_name(self, client_in, inventory):
        response = client_in.get(reverse("drinking:facilities"), {"q": "Riverside"})
        html = response.content.decode()
        assert _count_pill(html) == 1
        assert "Riverside treatment" in html

    def test_the_type_filter_narrows(self, client_in, inventory):
        response = client_in.get(
            reverse("drinking:facilities"), {"facility_type": "TP"}
        )
        assert _count_pill(response.content.decode()) == 1

    def test_the_status_filter_narrows(self, client_in, inventory):
        response = client_in.get(
            reverse("drinking:facilities"), {"activity_status": "I"}
        )
        assert _count_pill(response.content.decode()) == 1

    def test_the_options_come_from_the_database_not_the_choices_table(
        self, client_in, inventory
    ):
        """Three types are present out of the twenty-two published."""
        response = client_in.get(reverse("drinking:facilities"))
        options = response.context["facility_type_choices"]
        assert [code for code, _ in options] == ["DS", "TP", "WL"], (
            "sorted by label: Distribution System, Treatment Plant, Well"
        )

    def test_a_filter_plus_a_search_does_not_inflate_the_point_count(
        self, client_in, inventory
    ):
        """The Q-vs-OR bug, asserted with a real count.

        ``qs.filter(a) | qs.filter(b)`` re-joins sampling_points and doubles
        ``sampling_point_count``. The source facility has exactly three points,
        so an inflated count reads as 6 or 9 rather than failing abstractly.
        """
        response = client_in.get(
            reverse("drinking:facilities"),
            {"q": "001", "facility_type": "WL"},
        )
        assert response.status_code == 200
        rows = list(response.context["page_obj"])
        assert len(rows) == 1
        assert rows[0].sampling_point_count == 3


# -- 3. Empty states --------------------------------------------------------


class TestBothEmptyStates:
    def test_filters_matched_nothing_says_so(self, client_in, inventory):
        response = client_in.get(
            reverse("drinking:facilities"), {"q": "nothing-matches-this"}
        )
        html = response.content.decode()
        assert "No facilities found" in html
        assert "A facility is a physical part" not in html

    def test_nothing_onboarded_offers_the_domain_explainer(self, client_in):
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        assert "A facility is a physical part" in html
        # 123-02 REVERSES the onboarding half of this assertion, and the reason
        # the old one gave is the reason it had to go: "onboarding belongs to
        # the overview" is true of where the link lives and false of where the
        # operator is. Someone who followed the Facilities link and found
        # nothing has already left the overview; telling them to go back to a
        # page they came from is not a door. Onboarding writes the system AND
        # its facilities, so it is the right one here.
        #
        # The import half stands unchanged: a lab file creates results, never
        # structure, so offering it here would still be a dead end.
        #
        # Still asserted on the BUTTON LABELS, not the URLs — the sidebar links
        # /drinking/onboard on every page, so a URL assertion would be about the
        # nav rather than about this empty state. (The same trap caught three
        # assertions in tests/test_drinking_module_shows_what_to_do.py during
        # its red run; that file scopes by CSS class instead.)
        assert "Onboard a water system" in html
        assert "Import lab results" not in html


# -- 4. The drinking-water utility flavor -----------------------------------


class TestTheTypeFilterNamesNoDroppedModule:
    """The property the droppability crawl cannot see, asserted directly.

    Its fixture seeds no drinking rows (ISS-097), so the crawl reaches this page
    with an empty database — which is exactly the state that would render the
    full choices table if the view built the options from
    ``FACILITY_TYPE_CHOICES``.
    """

    @pytest.fixture(autouse=True)
    def _wells_is_off(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_WELLS

    def test_an_empty_database_names_no_forbidden_word(self, client_in):
        response = client_in.get(reverse("drinking:facilities"))
        assert response.status_code == 200
        found = find_forbidden_word(
            visible_text(response.content.decode()),
            FORBIDDEN_VOCABULARY["wells"],
        )
        assert found is None, (
            f"the facilities page names {found} on a wells-less deployment"
        )

    def test_the_select_renders_no_type_option_at_all(self, client_in):
        """The mechanism behind the property above, pinned separately.

        Reading the rendered ``<select>`` rather than the context, because it is
        the rendered option TEXT the vocabulary gate sees.
        """
        html = client_in.get(reverse("drinking:facilities")).content.decode()
        select = re.search(
            r'id="filter-facility-type".*?</select>', html, re.S
        ).group(0)
        options = [
            text.strip() for text in re.findall(r"<option[^>]*>(.*?)</option>",
                                                select, re.S)
        ]
        assert options == ["All Types"], (
            "an empty database rendered a facility-type option list"
        )


class TestTheWellColumnIsModuleGuarded:
    @pytest.fixture(autouse=True)
    def _wells_is_off(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_WELLS

    def test_a_linked_well_degrades_to_plain_text(self, client_in, inventory):
        facility = inventory["source"]
        facility.well = WellFactory(name="Alpha 4")
        facility.save()

        response = client_in.get(reverse("drinking:facilities"))
        assert response.status_code == 200, (
            "the facilities page 500s on a drinking-water-only deployment"
        )
        html = response.content.decode()
        assert "Alpha 4" in html, "the linked name vanished with the module"
        assert "/wells/" not in html, "an unguarded wells link survived"
