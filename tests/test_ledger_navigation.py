# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 63: view-layer tests for the at-scale ledger navigation tools —
sortable columns (whitelist + fallback), the Zone facet (with de-duplication),
and the page-size selector. These exercise ``accounting.views.ledger_list``
query handling directly; the sticky/HTMX UI is verified live in the checkpoint.
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
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"navuser{n}")
    email = factory.Sequence(lambda n: f"navuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


def _ledger_url(**params):
    """Ledger URL with an explicit period= so the ISS-022 bare-landing
    auto-default never narrows the rows out from under a navigation assertion."""
    from urllib.parse import urlencode

    base = reverse("accounting:ledger_list")
    params.setdefault("period", "")  # "All Periods" — bypass the auto-default
    return f"{base}?{urlencode(params)}"


def _results_region(html):
    """Scope a check to the swapped #ledger-results region (the subtitle,
    table and paging), never the filter form above it. A period or zone name
    always appears in the filter form's own <select> options regardless of
    what the subtitle says, so a bare `name in html` check would pass whether
    or not the subtitle names it -- this excludes that false pass."""
    marker = 'id="ledger-results"'
    idx = html.index(marker)
    return html[idx:]


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Sortable columns
# ---------------------------------------------------------------------------


class TestLedgerSort:
    def _three_amounts(self):
        period = ReportingPeriodFactory()
        for amt, day in ((Decimal("5.0000"), 5), (Decimal("30.0000"), 6), (Decimal("12.0000"), 7)):
            ParcelLedgerFactory(
                reporting_period=period,
                amount_acre_feet=amt,
                effective_date=date(2024, 6, day),
                source_type="manual_entry",
            )
        return period

    def test_sort_amount_ascending(self, auth_client):
        self._three_amounts()
        resp = auth_client.get(_ledger_url(sort="amount", dir="asc"))
        assert resp.status_code == 200
        amounts = [r.amount_acre_feet for r in resp.context["page_obj"]]
        assert amounts == sorted(amounts)
        assert amounts[0] == Decimal("5.0000")

    def test_sort_amount_descending(self, auth_client):
        self._three_amounts()
        resp = auth_client.get(_ledger_url(sort="amount", dir="desc"))
        assert resp.status_code == 200
        amounts = [r.amount_acre_feet for r in resp.context["page_obj"]]
        assert amounts == sorted(amounts, reverse=True)
        assert amounts[0] == Decimal("30.0000")

    def test_bogus_sort_falls_back_to_newest_first(self, auth_client):
        self._three_amounts()
        resp = auth_client.get(_ledger_url(sort="bogus"))
        assert resp.status_code == 200  # fail closed, no 500
        rows = list(resp.context["page_obj"])
        # Default is newest effective_date first.
        assert rows[0].effective_date == date(2024, 6, 7)
        assert resp.context["sort"] == "bogus"  # echoed back; just not applied

    def test_amount_ties_break_by_parcel_number_ascending(self, auth_client):
        """143-05 (candidate B kept the single 'amount' sort key unchanged;
        R-020's tiebreak was added to every sortable key). Three rows tied on
        amount must still come out in a predictable order rather than
        whatever -created_at happens to be."""
        period = ReportingPeriodFactory()
        for number in ("050", "010", "030"):
            ParcelLedgerFactory(
                parcel=ParcelFactory(parcel_number=number),
                reporting_period=period,
                amount_acre_feet=Decimal("10.0000"),
                effective_date=date(2024, 6, 10),
                source_type="manual_entry",
            )
        resp = auth_client.get(_ledger_url(period=str(period.pk), sort="amount", dir="asc"))
        assert resp.status_code == 200
        rows = list(resp.context["page_obj"])
        assert [r.parcel.parcel_number for r in rows] == ["010", "030", "050"]


# ---------------------------------------------------------------------------
# Page size
# ---------------------------------------------------------------------------


class TestLedgerPageSize:
    def test_page_size_500_is_honored(self, auth_client):
        resp = auth_client.get(_ledger_url(page_size="500"))
        assert resp.status_code == 200
        assert resp.context["page_obj"].paginator.per_page == 500
        assert resp.context["page_size"] == 500

    def test_invalid_page_size_falls_back_to_100(self, auth_client):
        resp = auth_client.get(_ledger_url(page_size="9999"))
        assert resp.status_code == 200
        assert resp.context["page_obj"].paginator.per_page == 100
        assert resp.context["page_size"] == 100

    def test_non_numeric_page_size_falls_back_to_100(self, auth_client):
        resp = auth_client.get(_ledger_url(page_size="lots"))
        assert resp.status_code == 200
        assert resp.context["page_obj"].paginator.per_page == 100


# ---------------------------------------------------------------------------
# Zone facet
# ---------------------------------------------------------------------------


class TestLedgerZoneFacet:
    def test_zone_filter_narrows_and_does_not_duplicate(self, auth_client):
        period = ReportingPeriodFactory()
        zone_a = ZoneFactory()
        zone_b = ZoneFactory()

        # A parcel living in TWO zones, with two ledger rows of its own.
        parcel_in_both = ParcelFactory()
        ParcelZoneFactory(parcel=parcel_in_both, zone=zone_a)
        ParcelZoneFactory(parcel=parcel_in_both, zone=zone_b)
        for day in (10, 11):
            ParcelLedgerFactory(
                parcel=parcel_in_both,
                reporting_period=period,
                effective_date=date(2024, 6, day),
                source_type="manual_entry",
            )

        # A parcel in neither filtered zone — must be excluded.
        other = ParcelFactory()
        ParcelLedgerFactory(
            parcel=other,
            reporting_period=period,
            effective_date=date(2024, 6, 12),
            source_type="manual_entry",
        )

        resp = auth_client.get(_ledger_url(zone=str(zone_a.pk)))
        assert resp.status_code == 200
        rows = list(resp.context["page_obj"])

        # Two genuine ledger rows for the zoned parcel — no duplication from the
        # parcel also belonging to zone_b.
        assert resp.context["total_count"] == 2
        assert len(rows) == 2
        pks = [r.pk for r in rows]
        assert len(pks) == len(set(pks))  # count == distinct count
        assert all(r.parcel_id == parcel_in_both.pk for r in rows)

    def test_zone_composes_with_source_type(self, auth_client):
        period = ReportingPeriodFactory()
        zone = ZoneFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)

        ParcelLedgerFactory(
            parcel=parcel,
            reporting_period=period,
            source_type="calculated",
            effective_date=date(2024, 6, 1),
        )
        ParcelLedgerFactory(
            parcel=parcel,
            reporting_period=period,
            source_type="manual_entry",
            effective_date=date(2024, 6, 2),
        )

        resp = auth_client.get(_ledger_url(zone=str(zone.pk), source_type="calculated"))
        assert resp.status_code == 200
        rows = list(resp.context["page_obj"])
        assert len(rows) == 1
        assert rows[0].source_type == "calculated"


# ---------------------------------------------------------------------------
# The footer (136-01, ISS-155)
# ---------------------------------------------------------------------------


class TestLedgerFooter:
    """Two subtotals named by kind, and no net.

    The footer used to add allocation paper to delivered water and print one
    signed net, which stated WY 2025-2026 at -1,504.32 AF beside a dashboard
    reading +1,249.07 AF over the same rows. Paper and water are not addable
    (DESIGN.md rule 12, review question 3), so the net is gone and the two
    subtotals say what they are.
    """

    def _four_rows(self):
        period = ReportingPeriodFactory()
        parcel = ParcelFactory()
        for source_type, amount in (
            ("allocation", Decimal("100.0000")),
            ("recharge", Decimal("25.0000")),
            ("surface_diversion", Decimal("-40.0000")),
            ("meter_reading", Decimal("-10.0000")),
        ):
            ParcelLedgerFactory(
                parcel=parcel, reporting_period=period, source_type=source_type,
                amount_acre_feet=amount, effective_date=date(2024, 6, 15),
            )
        return period

    def test_footer_names_credits_and_water_and_prints_no_net(self, auth_client):
        period = self._four_rows()

        response = auth_client.get(_ledger_url(period=period.pk))
        assert response.status_code == 200
        html = response.content.decode()

        # 100.0000 allocation + 25.0000 recharge = +125.00 of credits.
        assert response.context["ledger_total_credits"] == Decimal("125.0000")
        assert "Credits" in html and "+125.00" in html
        # 40.0000 delivered + 10.0000 pumped = 50.00 of water, as a magnitude.
        assert response.context["ledger_total_water"] == Decimal("50.0000")
        assert "Delivered and pumped" in html and "50.00" in html
        # No net: neither the signed -75.00 nor its magnitude appears anywhere.
        assert "ledger_total_net" not in response.context
        assert "75.00" not in html
        assert "debits" not in html
        # 143-05: the sign sentence moved from the footer to the subtitle line
        # above the table, where a reader meets it before the rows. Its
        # second checkpoint (2026-09-12) shortened it from one 30-word
        # sentence to a two-clause facts line at 14px; the old sentence is
        # gone from the page, and the new one appears exactly once, never
        # inside <tfoot>.
        sentence = (
            "Negative amounts are water delivered or pumped; positive "
            "amounts are credits."
        )
        assert html.count(sentence) == 1
        assert "Credits are paper or banked water and are not a supply." not in html
        tfoot = re.search(r"<tfoot>.*?</tfoot>", html, re.S)
        assert tfoot, "footer should still render its two subtotals"
        assert sentence not in tfoot.group(0)


# ---------------------------------------------------------------------------
# 143-05 guards: the seven register rows this plan closes (R-016, R-018,
# R-042, R-017, R-019, R-020, R-043). Each guard below observed RED against
# the pre-change tree (ad08624's templates and views.py) before it was made
# to pass; see 143-05-EVIDENCE.md for the quoted failing assertion.
# ---------------------------------------------------------------------------


class TestLedgerFilterBarShape:
    """R-016/R-017: one filter row. The quick-filter chips and the
    jump-to-page input are gone from the whole page, not merely relocated;
    exactly one control on the page sets page_size."""

    def test_page_size_control_appears_exactly_once(self, auth_client):
        resp = auth_client.get(_ledger_url())
        html = resp.content.decode()
        assert html.count('name="page_size"') == 1

    def test_no_element_named_page_exists_anywhere_on_the_page(self, auth_client):
        # The old jump-to-page <input name="page"> is gone outright (R-017);
        # the Previous/Next buttons set "page" through hx-vals, never a named
        # form control, so this count is 0 both before and after -- what
        # changed is the jump control that used to make it 1.
        resp = auth_client.get(_ledger_url())
        html = resp.content.decode()
        assert 'name="page"' not in html

    def test_the_this_period_chip_and_jump_to_page_input_are_gone(self, auth_client):
        resp = auth_client.get(_ledger_url())
        html = resp.content.decode()
        assert "chip-this-period" not in html
        assert "filter-page" not in html
        assert "filter-chip" not in html


class TestLedgerSubtitle:
    """R-042: the subtitle line above the table names the period (or "All
    periods") and the row count, and the zone's name when a zone narrows the
    set, instead of a bare "N entries" that never says which period."""

    def test_subtitle_names_the_period_and_the_entry_count(self, auth_client):
        period = TestLedgerFooter()._four_rows()
        resp = auth_client.get(_ledger_url(period=str(period.pk)))
        assert resp.status_code == 200
        region = _results_region(resp.content.decode())
        assert period.name in region
        assert "4 entries" in region

    def test_subtitle_reads_all_periods_when_no_period_is_set(self, auth_client):
        TestLedgerFooter()._four_rows()
        resp = auth_client.get(_ledger_url(period=""))
        assert resp.status_code == 200
        region = _results_region(resp.content.decode())
        assert "All periods" in region

    def test_subtitle_names_the_zone_when_a_zone_is_set(self, auth_client):
        period = ReportingPeriodFactory()
        zone = ZoneFactory(name="Halvern")
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        ParcelLedgerFactory(
            parcel=parcel, reporting_period=period,
            effective_date=date(2024, 6, 20), source_type="manual_entry",
        )
        resp = auth_client.get(_ledger_url(period=str(period.pk), zone=str(zone.pk)))
        assert resp.status_code == 200
        region = _results_region(resp.content.decode())
        assert "Halvern" in region


class TestLedgerSignSentenceInSubtitle:
    """R-018 (second checkpoint, 2026-09-12): the settled facts line lives in
    the subtitle line above the table exactly once, and never inside
    <tfoot> -- the footer keeps its two subtotals and no sentence. The first
    checkpoint's candidate-B sentence was itself replaced at this second
    checkpoint: "tiny", "unnecessarily wordy" (Brent), shortened from one
    30-word sentence to two clauses at 14px."""

    def test_full_sentence_appears_once_in_the_subtitle_and_not_the_footer(self, auth_client):
        period = TestLedgerFooter()._four_rows()
        resp = auth_client.get(_ledger_url(period=str(period.pk)))
        html = resp.content.decode()
        sentence = (
            "Negative amounts are water delivered or pumped; positive "
            "amounts are credits."
        )
        assert html.count(sentence) == 1
        old_sentence = (
            "Water leaving a canal or a well is stored as a negative entry. "
            "Credits are paper or banked water and are not a supply."
        )
        assert old_sentence not in html
        head = re.search(r'<div class="ledger-card-head">.*?</div>\s*</div>', html, re.S)
        assert head, "subtitle region not found"
        assert sentence in head.group(0)
        tfoot = re.search(r"<tfoot>.*?</tfoot>", html, re.S)
        assert tfoot and sentence not in tfoot.group(0)


class TestLedgerDescriptionUntruncated:
    """R-019: the Description column loses truncatechars and its fixed width,
    so the true 125-character maximum in the live demo round-trips whole
    instead of being cut at 60 characters with an ellipsis."""

    def test_a_125_character_description_round_trips_whole(self, auth_client):
        period = ReportingPeriodFactory()
        long_desc = (
            "Diversion from MER-POD-099-DEMO Stevinson Diversion Canal Headgate: "
            "214.5813 AF, Direct Use, demand weighted and ET allocated"
        )
        assert len(long_desc) == 125
        ParcelLedgerFactory(
            reporting_period=period, effective_date=date(2024, 6, 1),
            source_type="manual_entry", description=long_desc,
        )
        resp = auth_client.get(_ledger_url(period=str(period.pk)))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert long_desc in html
        # Scoped to the table body: the page head's own search combobox
        # legitimately carries an ellipsis in unrelated placeholder text, so
        # the guard checks the Description cell's own region, not the page.
        tbody = re.search(r"<tbody>.*?</tbody>", html, re.S)
        assert tbody, "table body not found"
        assert "&hellip;" not in tbody.group(0)
        assert "…" not in tbody.group(0)


class TestLedgerWithinDateOrder:
    """R-020: within one date, rows render in use-area (parcel number)
    ascending order rather than raw seed-insertion order."""

    def test_three_same_date_rows_order_by_parcel_number_ascending(self, auth_client):
        period = ReportingPeriodFactory()
        same_date = date(2024, 6, 15)
        # Insertion order is deliberately scrambled and non-alphabetical, so a
        # pass here can only come from the view's own ordering.
        for number in ("076", "002", "041"):
            ParcelLedgerFactory(
                parcel=ParcelFactory(parcel_number=number),
                reporting_period=period,
                effective_date=same_date,
                source_type="manual_entry",
            )
        resp = auth_client.get(_ledger_url(period=str(period.pk)))
        assert resp.status_code == 200
        rows = list(resp.context["page_obj"])
        numbers = [r.parcel.parcel_number for r in rows]
        assert numbers == ["002", "041", "076"]


class TestLedgerZeroRowSentence:
    """R-043: a `calculated` row at exactly 0.0000 AF carries the engine's own
    sentence in its Description cell and a muted Amount cell; an ordinary
    negative row does not."""

    def test_zero_calculated_row_gets_the_sentence_and_a_negative_row_does_not(self, auth_client):
        period = ReportingPeriodFactory()
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel, reporting_period=period, source_type="calculated",
            amount_acre_feet=Decimal("0.0000"), effective_date=date(2024, 6, 1),
            description="Derived groundwater extraction estimate (calculation engine)",
        )
        ParcelLedgerFactory(
            parcel=parcel, reporting_period=period, source_type="meter_reading",
            amount_acre_feet=Decimal("-10.0000"), effective_date=date(2024, 6, 2),
        )
        resp = auth_client.get(_ledger_url(period=str(period.pk)))
        assert resp.status_code == 200
        html = resp.content.decode()
        sentence = (
            "No groundwater extraction was derived for this month; rainfall "
            "and delivered surface water covered the estimated use."
        )
        assert html.count(sentence) == 1
        assert 'class="td-num text-tertiary"' in html


# ---------------------------------------------------------------------------
# 143-05 second checkpoint (2026-09-12): the merged "Water" column
# ---------------------------------------------------------------------------


class TestLedgerWaterColumnWords:
    """The Source + Water type columns merged into one "Water" column,
    computed by ``accounting/ledger_words.py::ledger_row_words`` and reached
    from the template through the ``ledger_row_words`` filter. Observed RED
    against the pre-change tree (155bfa7's ``_ledger_list_results.html``,
    ``_source_badge.html`` and ``accounting/views.py``, checked out via
    ``docker compose cp`` alongside this test): the old markup rendered
    "Meter Read" as the badge column's word (truncated by CSS, the full
    string being "Meter reading") and "Surface diversion" for a diverted row,
    never "Groundwater, metered" or "Surface water, diverted" -- see
    143-05-EVIDENCE.md for the quoted failing assertions.
    """

    def test_meter_reading_groundwater_row_reads_groundwater_metered(self, auth_client):
        period = ReportingPeriodFactory()
        gw = WaterTypeFactory(name="Groundwater", code="GW-T")
        ParcelLedgerFactory(
            reporting_period=period, source_type="meter_reading",
            water_type=gw, amount_acre_feet=Decimal("-5.0000"),
            effective_date=date(2024, 6, 1),
        )
        html = auth_client.get(_ledger_url(period=str(period.pk))).content.decode()
        assert "Groundwater, metered" in html

    def test_calculated_groundwater_row_reads_groundwater_estimated(self, auth_client):
        period = ReportingPeriodFactory()
        gw = WaterTypeFactory(name="Groundwater", code="GW-T2")
        ParcelLedgerFactory(
            reporting_period=period, source_type="calculated",
            water_type=gw, amount_acre_feet=Decimal("-3.0000"),
            effective_date=date(2024, 6, 2),
        )
        html = auth_client.get(_ledger_url(period=str(period.pk))).content.decode()
        assert "Groundwater, estimated" in html

    def test_surface_diversion_surface_water_row_reads_surface_water_diverted(self, auth_client):
        period = ReportingPeriodFactory()
        sw = WaterTypeFactory(name="Surface Water", code="SW-T")
        ParcelLedgerFactory(
            reporting_period=period, source_type="surface_diversion",
            water_type=sw, amount_acre_feet=Decimal("-8.0000"),
            effective_date=date(2024, 6, 3),
        )
        html = auth_client.get(_ledger_url(period=str(period.pk))).content.decode()
        assert "Surface water, diverted" in html

    def test_allocation_surface_water_row_reads_surface_water_allocation(self, auth_client):
        period = ReportingPeriodFactory()
        sw = WaterTypeFactory(name="Surface Water", code="SW-T2")
        ParcelLedgerFactory(
            reporting_period=period, source_type="allocation",
            water_type=sw, amount_acre_feet=Decimal("20.0000"),
            effective_date=date(2024, 6, 4),
        )
        html = auth_client.get(_ledger_url(period=str(period.pk))).content.decode()
        assert "Surface water allocation" in html

    def test_recharge_row_reads_recharge_credit_regardless_of_water_type(self, auth_client):
        period = ReportingPeriodFactory()
        sw = WaterTypeFactory(name="Surface Water", code="SW-T3")
        ParcelLedgerFactory(
            reporting_period=period, source_type="recharge",
            water_type=sw, amount_acre_feet=Decimal("15.0000"),
            effective_date=date(2024, 6, 5),
        )
        html = auth_client.get(_ledger_url(period=str(period.pk))).content.decode()
        assert "Recharge credit" in html

    def test_the_old_badge_words_are_gone_from_the_page(self, auth_client):
        period = ReportingPeriodFactory()
        gw = WaterTypeFactory(name="Groundwater", code="GW-T3")
        sw = WaterTypeFactory(name="Surface Water", code="SW-T4")
        for source_type, water_type, day in (
            ("meter_reading", gw, 10),
            ("surface_diversion", sw, 11),
        ):
            ParcelLedgerFactory(
                reporting_period=period, source_type=source_type,
                water_type=water_type, amount_acre_feet=Decimal("-1.0000"),
                effective_date=date(2024, 6, day),
            )
        html = auth_client.get(_ledger_url(period=str(period.pk))).content.decode()
        assert "Meter Reading" not in html
        assert "Meter Read" not in html
        assert "Surface diversion" not in html
