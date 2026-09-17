# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards for the 143-13 finder shape.

The workspace FRAME ruling (open since 143-02, closed by Brent at this plan's
decision checkpoint, 2026-09-16 18:29/18:34 PDT) moved Use Areas and Wells off
the master-detail workspace (`templates/workspace.html`, now deleted) onto the
Bucket-3 list idiom every other list on the platform already uses: the 143-07
overview map card (count line + key, following the list) above a one-row
toolbar above a table, a row opening the record's own detail page. Water
accounts took the "accounts-table" ruling instead: the dashboard's own Active
water accounts table, with a search, since accounts have no geometry of their
own.

This file closes R-105 (six rows in a narrow rail beside an empty placeholder
pane) and R-106 (the two filter controls stacked, a quarter of the rail) on
all three finders. Every assertion here was run RED against the pre-143-13
tree (commit 84139bd, before Task 3's four commits) before this file existed,
to prove each one CAN fail; the failing output is quoted in
`143-13-EVIDENCE.md`.

`tests/test_overview_map_card.py` carries the map-card PATTERN guards (the
count line's wording, the swatch key, the always-on label layer, the map
following the list on a swap) for Use Areas and Wells, extended there rather
than duplicated here. This file is the page-level shape: row counts, the
toolbar, the workspace shell's absence, and the old `?selected=` deep link.
"""

import factory
import pytest
import re
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import ParcelFactory, WaterAccountFactory, WellFactory


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention: every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"finderpages{n}")
    email = factory.Sequence(lambda n: f"finderpages{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _oob_head(html, head_id):
    """The opening `<div id="{head_id}" ...>` tag from an htmx (oob) response."""
    match = re.search(r'<div id="%s"[^>]*>' % re.escape(head_id), html)
    assert match, f'no <div id="{head_id}"> in the response'
    return match.group(0)


def _between(body, start_needle, end_needle):
    """The slice of `body` between the first occurrence of each needle, so a
    toolbar's own controls can be checked without also matching an unrelated
    id elsewhere on the page."""
    start = body.index(start_needle)
    end = body.index(end_needle)
    return body[start:end]


# ---------------------------------------------------------------------------
# R-105 / R-106: Use Areas (`/parcels/`)
# ---------------------------------------------------------------------------


class TestUseAreasFinder:
    def test_thirty_use_areas_render_25_rows_and_one_pager(self, auth_client):
        for n in range(30):
            ParcelFactory(parcel_number=f"UA-{n:03d}")

        body = auth_client.get(reverse("parcels:list")).content.decode()
        assert body.count("data-table-link") == 25, (
            "the first page must show 25 rows, the page size the view paginates at"
        )
        assert "pagination-row" in body
        assert "Page 1 of 2" in body

    def test_body_has_no_workspace_shell(self, auth_client):
        ParcelFactory()

        body = auth_client.get(reverse("parcels:list")).content.decode()
        assert "workspace-split" not in body
        assert "master-row" not in body
        assert "toolbar-stack" not in body
        assert "pane-empty" not in body

    def test_the_head_reads_the_partials_own_words_for_thirty(self, auth_client):
        for n in range(30):
            ParcelFactory(parcel_number=f"UA-{n:03d}")

        body = auth_client.get(reverse("parcels:list")).content.decode()
        assert body.count("map-card-head") == 1, (
            "the count line must live once, in the map card's head"
        )
        assert "30 use areas, all on the map" in body

    def test_a_search_matching_two_renders_the_oob_head_and_the_results(
        self, auth_client
    ):
        for n in range(28):
            ParcelFactory(parcel_number=f"UA-{n:03d}", owner_name="Other Farms")
        ParcelFactory(parcel_number="UA-M01", owner_name="Match Farms")
        ParcelFactory(parcel_number="UA-M02", owner_name="Match Farms")

        response = auth_client.get(
            reverse("parcels:list"), {"q": "Match Farms"}, HTTP_HX_REQUEST="true"
        )
        body = response.content.decode()
        assert response.status_code == 200
        head = _oob_head(body, "parcels-overview-map-head")
        assert 'hx-swap-oob="true"' in head
        assert "2 of 30 match" in body
        assert "the map shows those 2" in body
        assert body.count("data-table-link") == 2

    def test_selected_redirects_to_the_detail_page(self, auth_client):
        parcel = ParcelFactory()

        response = auth_client.get(reverse("parcels:list"), {"selected": parcel.pk})
        assert response.status_code == 302
        assert response.url == reverse("parcels:detail", kwargs={"pk": parcel.pk})

    def test_the_toolbar_is_one_row_holding_both_controls(self, auth_client):
        ParcelFactory()

        body = auth_client.get(reverse("parcels:list")).content.decode()
        assert "toolbar-stack" not in body
        assert "toolbar-row" in body
        toolbar_section = _between(body, "toolbar-row", 'id="results"')
        assert 'id="filter-search"' in toolbar_section
        assert 'id="filter-status"' in toolbar_section


# ---------------------------------------------------------------------------
# R-105 / R-106: Wells (`/wells/`)
# ---------------------------------------------------------------------------


class TestWellsFinder:
    def test_thirty_wells_render_25_rows_and_one_pager(self, auth_client):
        for n in range(30):
            WellFactory(name=f"Well {n:03d}")

        body = auth_client.get(reverse("wells:list")).content.decode()
        assert body.count("data-table-link") == 25, (
            "the first page must show 25 rows, the page size the view paginates at"
        )
        assert "pagination-row" in body
        assert "Page 1 of 2" in body

    def test_body_has_no_workspace_shell(self, auth_client):
        WellFactory()

        body = auth_client.get(reverse("wells:list")).content.decode()
        assert "workspace-split" not in body
        assert "master-row" not in body
        assert "toolbar-stack" not in body
        assert "pane-empty" not in body

    def test_the_head_reads_the_partials_own_words_for_thirty(self, auth_client):
        for n in range(30):
            WellFactory(name=f"Well {n:03d}")

        body = auth_client.get(reverse("wells:list")).content.decode()
        assert body.count("map-card-head") == 1, (
            "the count line must live once, in the map card's head"
        )
        assert "30 wells, all on the map" in body

    def test_a_search_matching_two_renders_the_oob_head_and_the_results(
        self, auth_client
    ):
        for n in range(28):
            WellFactory(name=f"Well {n:03d}")
        WellFactory(name="Match Well One")
        WellFactory(name="Match Well Two")

        response = auth_client.get(
            reverse("wells:list"), {"q": "Match"}, HTTP_HX_REQUEST="true"
        )
        body = response.content.decode()
        assert response.status_code == 200
        head = _oob_head(body, "wells-overview-map-head")
        assert 'hx-swap-oob="true"' in head
        assert "2 of 30 match" in body
        assert "the map shows those 2" in body
        assert body.count("data-table-link") == 2

    def test_wells_search_reaches_the_owner_column(self, auth_client):
        """Brent, 143-13 checkpoint 2026-09-16 21:08 PDT: the Owner column is on
        the list, so the search box has to find it, as Use Areas and Accounts do."""
        for n in range(5):
            WellFactory(name=f"Well {n:03d}", owner_name="Other Ranch")
        WellFactory(name="Well 900", owner_name="Halvern Orchards")
        WellFactory(name="Well 901", owner_name="Halvern Orchards")

        response = auth_client.get(
            reverse("wells:list"), {"q": "Halvern"}, HTTP_HX_REQUEST="true"
        )
        body = response.content.decode()
        assert response.status_code == 200
        assert "2 of 7 match" in body
        assert body.count("data-table-link") == 2

    def test_selected_redirects_to_the_detail_page(self, auth_client):
        well = WellFactory()

        response = auth_client.get(reverse("wells:list"), {"selected": well.pk})
        assert response.status_code == 302
        assert response.url == reverse("wells:detail", kwargs={"pk": well.pk})

    def test_the_toolbar_is_one_row_holding_both_controls(self, auth_client):
        WellFactory()

        body = auth_client.get(reverse("wells:list")).content.decode()
        assert "toolbar-stack" not in body
        assert "toolbar-row" in body
        toolbar_section = _between(body, "toolbar-row", 'id="results"')
        assert 'id="filter-search"' in toolbar_section
        assert 'id="filter-status"' in toolbar_section


# ---------------------------------------------------------------------------
# Water accounts (`/accounting/accounts/`), the "accounts-table" ruling: the
# shared Active water accounts table, not the Bucket-3 map-card shape (there
# is no geometry to draw; a per-account map is ISS-175, filed for Phase 144).
# ---------------------------------------------------------------------------


class TestAccountsFinder:
    def test_renders_the_shared_active_accounts_table(self, auth_client):
        for n in range(9):
            WaterAccountFactory(account_number=f"ACCT-{n:04d}")
        WaterAccountFactory(account_number="ACCT-M01", name="Match Farms")
        WaterAccountFactory(account_number="ACCT-M02", name="Match Ranch")

        body = auth_client.get(reverse("accounting:accounts_list")).content.decode()
        assert "workspace-split" not in body
        assert "toolbar-row" in body
        assert "ledger-card-head" in body
        assert "11 active accounts" in body
        assert body.count("data-table-link") == 11
        toolbar_section = _between(body, "toolbar-row", 'id="results"')
        assert 'id="filter-period"' in toolbar_section
        assert 'id="filter-search"' in toolbar_section

    def test_search_by_account_number_narrows_to_one(self, auth_client):
        for n in range(9):
            WaterAccountFactory(account_number=f"ACCT-{n:04d}")
        WaterAccountFactory(account_number="ACCT-UNIQUE-99")
        WaterAccountFactory(account_number="ACCT-OTHER-01")

        response = auth_client.get(
            reverse("accounting:accounts_list"),
            {"q": "ACCT-UNIQUE-99"},
            HTTP_HX_REQUEST="true",
        )
        body = response.content.decode()
        assert response.status_code == 200
        assert body.count("data-table-link") == 1
        assert "ACCT-UNIQUE-99" in body
        assert "1 of 11 active accounts matches" in body

    def test_selected_redirects_to_the_detail_page(self, auth_client):
        account = WaterAccountFactory()

        response = auth_client.get(
            reverse("accounting:accounts_list"), {"selected": account.pk}
        )
        assert response.status_code == 302
        assert response.url == reverse(
            "accounting:account_detail", kwargs={"pk": account.pk}
        )
