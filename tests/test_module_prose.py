# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan 88-01 — prose that names only the domains a deployment runs.

ISS-082's copy half. 87-02 measured all three sites live under Configuration B:
the home page still said "every well, parcel, and *diversion*", Getting Started
still promised *recharge basins*, and Step 10 still named *CalWATRS CSV (surface
diversions)*. Every automated gate was green, because they check status codes
and link targets and never words.

Two properties are pinned, and the first is the one the milestone rests on:

* **A full deployment renders the original wording, character for character.**
  The Oxford join was chosen to reproduce the hardcoded sentences exactly, so
  making the copy conditional cost nothing on the default install.
* **A dropped module's noun disappears** -- from the sentence, not merely from
  the link beside it.

``tests/droppability/checks.py`` carries the general form of the second property
as a forbidden-vocabulary assertion over every kept page. These are the unit
tests underneath it: they pin the joining rule itself, which a page-level
assertion can only observe indirectly.
"""
import pytest
from django.template import Context, Template

from core import modules as mod
from core.templatetags.prose import oxford_join

WITHOUT_SURFACE = [
    name for name in mod.ALL_MODULE_NAMES if name not in ("surface", "recharge")
]

WIZARD_NOUNS = (
    '{% load prose %}{% module_nouns "parcels:use areas" "wells:wells" '
    '"recharge:recharge basins" "datasync:nearby monitoring stations" %}'
)

FILING_NOUNS = (
    '{% load prose %}{% module_nouns '
    '"wells:GEARS CSV (per-well or by-ET extraction)" '
    '"surface:CalWATRS CSV (surface diversions)" %}'
)


def render(source, **context):
    return Template(source).render(Context(context))


class TestOxfordJoin:
    """Plain English, tested as plain English."""

    @pytest.mark.parametrize(
        "items,expected",
        [
            ([], ""),
            (["wells"], "wells"),
            (["wells", "use areas"], "wells and use areas"),
            (["a", "b", "c"], "a, b, and c"),
            (["a", "b", "c", "d"], "a, b, c, and d"),
        ],
    )
    def test_joins_the_way_the_copy_already_reads(self, items, expected):
        assert oxford_join(items) == expected

    def test_the_serial_comma_is_deliberate(self):
        """The sentences being replaced used it; dropping it would be a copy change."""
        assert oxford_join(["a", "b", "c"]) == "a, b, and c"
        assert oxford_join(["a", "b", "c"]) != "a, b and c"

    def test_empty_entries_are_dropped_rather_than_joined_as_gaps(self):
        assert oxford_join(["wells", "", "use areas"]) == "wells and use areas"

    def test_the_conjunction_is_settable(self):
        assert oxford_join(["a", "b"], "or") == "a or b"


class TestMalformedPairs:
    def test_a_pair_without_a_colon_fails_loudly(self):
        """The quiet alternative is a noun that silently never renders."""
        from django.template import TemplateSyntaxError

        with pytest.raises(TemplateSyntaxError, match="module:noun"):
            render('{% load prose %}{% module_nouns "wells" %}')

    def test_a_noun_may_contain_a_colon(self):
        assert render('{% load prose %}{% module_nouns "wells:a: b" %}') == "a: b"


class TestFullDeploymentWordingIsUnchanged:
    """The pin. These strings are the pre-change text, copied verbatim."""

    def test_the_setup_wizard_sentence_is_character_for_character(self):
        assert render(WIZARD_NOUNS) == (
            "use areas, wells, recharge basins, and nearby monitoring stations"
        )

    def test_the_filing_sentence_is_character_for_character(self):
        assert render(FILING_NOUNS) == (
            "GEARS CSV (per-well or by-ET extraction) and "
            "CalWATRS CSV (surface diversions)"
        )

    def test_every_module_counts_as_available(self):
        assert render('{% load prose %}{% any_module_enabled "wells" "surface" %}') == "True"


class TestDroppedModulesLoseTheirNouns:
    @pytest.fixture(autouse=True)
    def _surface_is_off(self, settings):
        settings.OPENH2O_MODULES = WITHOUT_SURFACE

    def test_the_wizard_sentence_drops_recharge_and_regrows_its_grammar(self):
        """Not "use areas, wells, , and nearby monitoring stations"."""
        assert render(WIZARD_NOUNS) == (
            "use areas, wells, and nearby monitoring stations"
        )

    def test_the_filing_sentence_collapses_to_one_family(self):
        rendered = render(FILING_NOUNS)
        assert rendered == "GEARS CSV (per-well or by-ET extraction)"
        assert "CalWATRS" not in rendered
        assert " and " not in rendered, (
            "A one-item list rendered a dangling conjunction."
        )

    def test_a_deployment_that_can_file_nothing_says_so(self):
        assert render('{% load prose %}{% any_module_enabled "surface" %}') == "False"
        assert render('{% load prose %}{% any_module_enabled "wells" %}') == "True"


class TestRenderedPages:
    """The tags in the templates they were written for."""

    def test_getting_started_names_every_domain_on_a_full_deployment(self, admin_client):
        body = admin_client.get("/help/getting-started/").content.decode()
        assert (
            "populates your use areas, wells, recharge basins, and nearby "
            "monitoring stations for you" in body
        )
        assert (
            "generate GEARS CSV (per-well or by-ET extraction) and "
            "CalWATRS CSV (surface diversions) for submission" in body
        )

    def test_the_home_map_sublabel_no_longer_enumerates(self, admin_client):
        body = admin_client.get("/").content.decode()
        assert "Everything you manage on one basin view" in body
        assert "Every well, parcel, and diversion" not in body

    def test_the_home_report_card_names_both_families_when_both_are_on(
        self, admin_client
    ):
        body = admin_client.get("/").content.decode()
        assert "Generate GEARS and CalWATRS exports" in body

    def test_the_home_report_card_drops_calwatrs_when_surface_is_off(
        self, admin_client, settings
    ):
        """The fourth site, found by measuring rather than from the plan's list."""
        settings.OPENH2O_MODULES = WITHOUT_SURFACE
        body = admin_client.get("/").content.decode()
        assert "Generate GEARS exports" in body
        assert "CalWATRS" not in body

    def test_getting_started_drops_surface_nouns_when_surface_is_off(
        self, admin_client, settings
    ):
        settings.OPENH2O_MODULES = WITHOUT_SURFACE
        body = admin_client.get("/help/getting-started/").content.decode()
        assert "recharge basins" not in body
        assert "CalWATRS" not in body
        assert (
            "populates your use areas, wells, and nearby monitoring stations"
            in body
        ), "The wizard sentence lost a noun but did not repair its grammar."
