# SPDX-License-Identifier: AGPL-3.0-or-later
"""The five explainer Help pages, and the two lists that have to agree about them.

Plan 89-02 decided that a Help page whose SUBJECT is a domain this deployment
does not run should not be reachable — hidden, not rewritten, because a
module-neutral rewrite of "How Water Balances Work" would be a page about
nothing.

That decision lives in two places by necessity: ``config/views.py`` serves the
pages and ``tests/droppability/checks.py`` decides which pages the harness
demands. Two lists of the same fact drift, and the failure mode is silent — the
harness would keep asking for a page the view had stopped serving, or worse,
stop asking for one it still serves. These tests are the join.
"""
import pytest
from django.test import Client
from django.urls import reverse

from config.views import EXPLAINER_MODULES, explainer_is_available
from core.modules import ALL_MODULE_NAMES
from tests.droppability import checks


@pytest.mark.django_db
class TestExplainerGate:
    def test_every_explainer_names_only_real_modules(self):
        """A typo in the module set would silently hide the page forever."""
        for name, modules in EXPLAINER_MODULES.items():
            unknown = [m for m in modules if m not in ALL_MODULE_NAMES]
            assert not unknown, (
                f"Explainer {name!r} requires {unknown}, which the module "
                f"registry does not know about. `explainer_is_available` would "
                f"return False in every configuration and the page would be a "
                f"permanent 404."
            )

    def test_the_harness_page_table_agrees_with_the_view(self):
        """``_PAGES`` and ``EXPLAINER_MODULES`` must name the same module sets.

        The harness owner column is what stops it demanding a page that is no
        longer served. If the two lists disagree, one of them is wrong and
        nothing else in the suite can tell which.
        """
        paths = {
            "water_balances": "/help/water-balances/",
            "methods": "/help/methods/",
            "settings_explained": "/help/settings/",
            "surface_deliveries": "/help/surface-deliveries/",
            "budgets_allocations": "/help/budgets-allocations/",
        }
        rows = dict(checks._PAGES)
        for name, path in paths.items():
            assert path in rows, (
                f"{path} has no row in tests/droppability/checks.py::_PAGES, so "
                f"no assertion in the harness ever opens it — the exact defect "
                f"88-03 found on /drinking/ and 89-02 found on eleven pages."
            )
            assert tuple(rows[path]) == tuple(EXPLAINER_MODULES[name]), (
                f"{path} is owned by {rows[path]} in the harness and by "
                f"{EXPLAINER_MODULES[name]} in config/views.py."
            )

    def test_every_explainer_is_served_on_a_full_deployment(self, admin_client):
        """The default deployment loses nothing. The milestone's hardest rule."""
        for name in EXPLAINER_MODULES:
            assert explainer_is_available(name)

    def test_a_missing_module_404s_the_page_rather_than_redirecting(
        self, admin_client, monkeypatch
    ):
        """404, not 302 and not a page that loads and lies.

        Substituting the predicate rather than dropping a module for real, for the
        same reason 88-01 unit-tested the GEARS gate that way: the branch is
        proven before any configuration exercises it, and this file runs in a
        process that has every module.
        """
        monkeypatch.setattr(
            "config.views.explainer_is_available", lambda name: False
        )
        for url_name in ("water_balances", "methods", "settings_explained",
                         "surface_deliveries", "budgets_allocations"):
            response = admin_client.get(reverse(url_name))
            assert response.status_code == 404, (
                f"{url_name} returned {response.status_code} with its subject "
                f"absent; a page whose domain is gone is absent, not protected."
            )

    def test_a_hidden_page_takes_its_glossary_pointer_with_it(self, monkeypatch):
        """A definition must not send the reader at a 404.

        ISS-085 is untouched — the glossary still defines every term. This is
        only the cross-reference, which 89-02 created the problem for by making
        those pages conditional.
        """
        from config.views import _without_unavailable_help_pointers

        definition = (
            "A single account's share of a zone's Allocation Ceiling. "
            "See Help > Allocations & Ceilings."
        )
        assert _without_unavailable_help_pointers(definition) == definition

        monkeypatch.setattr(
            "config.views.explainer_is_available", lambda name: False
        )
        stripped = _without_unavailable_help_pointers(definition)
        assert "See Help" not in stripped
        assert stripped.endswith("Allocation Ceiling.")


@pytest.mark.django_db
class TestGettingStartedNumbering:
    """ISS-088. The numbers are computed; the citations are computed from the
    same table, because 88-03's lesson was that gating the nouns and leaving the
    numbers produces a wrong instruction rather than a gap."""

    def test_a_full_deployment_numbers_one_through_eleven(self):
        # These numbers MOVED, and the move is not drift: 92-01 (ISS-092) added
        # the ``pwsid`` row to the front of GETTING_STARTED_STEPS, so every step
        # below it shifted up by one — 1-10 became 1-11, the wizard citation
        # "1, 2, 8, and 9" became "2, 3, 9, and 10", and the accounting range
        # "3 through 7" became "4 through 8". One table row moved all three,
        # which is the whole point of 89-02's machinery.
        from config.views import _getting_started_numbering

        result = _getting_started_numbering()
        assert sorted(result["steps"].values()) == list(range(1, 12))
        assert result["wizard_cited_steps"] == "2, 3, 9, and 10"
        assert result["accounting_step_range"] == "4 through 8"

    def test_the_citations_only_ever_name_steps_that_render(self, monkeypatch):
        """Every number cited has to be a number on the page.

        Checked across a spread of configurations rather than one, because the
        defect 88-03 fixed only appeared in two of them.
        """
        from config import views as config_views

        for dropped in (
            (),
            ("wells",),
            ("wells", "datasync"),
            ("parcels", "accounting"),
            ("parcels", "accounting", "surface", "recharge", "wells",
             "datasync", "reporting"),
            # 92-01: the wizard sentence has to stay correct when the NEWEST
            # module is the one missing, which is the case a spread written
            # before `pwsid` existed could not cover.
            ("drinking",),
            # The nine-module drinking-water configuration inverted: every
            # optional domain dropped INCLUDING the new one. This is where the
            # table is shortest — `zones` alone renders — so it is where an
            # off-by-one in either citation would show up first.
            ("drinking", "parcels", "accounting", "surface", "recharge",
             "wells", "datasync", "reporting"),
        ):
            monkeypatch.setattr(
                config_views, "is_enabled", lambda name, d=dropped: name not in d
            )
            result = config_views._getting_started_numbering()
            rendered = set(result["steps"].values())
            cited = {
                int(part.strip().rstrip(","))
                for part in result["wizard_cited_steps"]
                .replace(" and ", " ")
                .split()
                if part.strip().rstrip(",").isdigit()
            }
            assert cited <= rendered, (
                f"With {dropped} dropped the wizard sentence cites {cited} but "
                f"only {sorted(rendered)} render."
            )
            if result["accounting_step_range"]:
                low, high = result["accounting_step_range"].split(" through ")
                assert int(low) in rendered and int(high) in rendered

    def test_the_drinking_deployment_opens_with_the_pwsid_step(self, monkeypatch):
        """ISS-092 in its smallest form.

        The nine-module drinking-water flavor — a login, a map and Drinking
        Water — used to open on "Step 1 · Define Management Zones", offering a
        utility a map as its first instruction while the action it actually
        starts with (enter your PWSID) was not on the page at all. The first
        step now IS that action.
        """
        from config import views as config_views

        nine = {
            "core", "geography", "measurements", "standards",
            "health", "setup", "infrastructure", "feedback", "drinking",
        }
        monkeypatch.setattr(config_views, "is_enabled", lambda name: name in nine)
        result = config_views._getting_started_numbering()
        assert result["steps"] == {"pwsid": 1, "zones": 2}
