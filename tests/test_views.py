# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Smoke tests verifying every page returns HTTP 200 for appropriate users.

Uses Django's test Client with force_login for authenticated routes.
Health endpoints are public (no login required per Phase 7 design decision).
"""

import pytest
import factory
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    WellFactory,
    RechargeSiteFactory,
    WaterRightFactory,
    ZoneFactory,
)
from reporting.models import ReportSubmission, ReportTemplate


def _report_submission(report_type="gears_by_well", name="GEARS by Well", status="draft"):
    """A minimal ReportSubmission for the reports-workspace view tests."""
    template, _ = ReportTemplate.objects.get_or_create(
        report_type=report_type, defaults={"name": name}
    )
    return ReportSubmission.objects.create(
        report_template=template,
        reporting_period=ReportingPeriodFactory(),
        status=status,
    )


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def auth_client():
    user = UserFactory()
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------------------
# Public pages (no login required)
# ---------------------------------------------------------------------------


class TestPublicPages:
    def test_index_unauthenticated(self, client):
        """Index returns 200 for unauthenticated users."""
        response = client.get(reverse("index"))
        assert response.status_code == 200

    def test_health_dashboard_public(self, client):
        """Health dashboard is public (no login required)."""
        response = client.get(reverse("health:dashboard"))
        assert response.status_code == 200

    def test_health_api_public(self, client):
        """Health API is public (no login required)."""
        response = client.get(reverse("health:api"))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Help pages (login required)
# ---------------------------------------------------------------------------


class TestHelpPages:
    def test_getting_started(self, auth_client):
        response = auth_client.get(reverse("getting_started"))
        assert response.status_code == 200

    def test_glossary(self, auth_client):
        response = auth_client.get(reverse("glossary"))
        assert response.status_code == 200

    # Help pages are login-gated on an ENFORCED deployment only; the open demo
    # serves them to anonymous prospects (core.access.public_in_open_demo —
    # both directions pinned in tests/test_public_demo_access.py).
    @override_settings(ACCESS_CONTROL_ENFORCED=True)
    def test_getting_started_redirects_anonymous(self, client):
        response = client.get(reverse("getting_started"))
        assert response.status_code == 302

    @override_settings(ACCESS_CONTROL_ENFORCED=True)
    def test_glossary_redirects_anonymous(self, client):
        response = client.get(reverse("glossary"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Accounting pages (login required)
# ---------------------------------------------------------------------------


class TestDashboardAllocationProRating:
    def test_prorates_allocation_by_parcel_count(self, auth_client):
        """Zone with 4 parcels, account owns 1: allocation = 25% of zone total."""
        from datetime import date
        from decimal import Decimal

        period = ReportingPeriodFactory(
            start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        zone = ZoneFactory()
        # Groundwater plan (136-01): the allocation column counts GW plans only.
        water_type = WaterTypeFactory(name="Groundwater", code="GW")

        # Create 4 parcels in the zone
        parcels = [ParcelFactory() for _ in range(4)]
        for p in parcels:
            ParcelZoneFactory(parcel=p, zone=zone)

        # Account owns only 1 of the 4 parcels
        account = WaterAccountFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcels[0])

        # Zone allocation is 100 AF
        AllocationPlanFactory(
            zone=zone,
            water_type=water_type,
            reporting_period=period,
            allocation_acre_feet=Decimal("100.0000"),
        )

        response = auth_client.get(
            reverse("accounting:dashboard") + f"?period={period.pk}"
        )
        assert response.status_code == 200

        # Find the account summary in context
        account_summaries = response.context["account_summaries"]
        match = [s for s in account_summaries if s["account"] == account]
        assert len(match) == 1
        # Pro-rated: 100 AF * (1/4) = 25 AF
        assert match[0]["allocation"] == Decimal("25.0000")


class TestLedgerDefaultPeriod:
    """ISS-022: the ledger should land on the period that surfaces the audit
    trail, not the empty calendar-current one."""

    def _two_periods_with_rows(self):
        from datetime import date

        # Older period carries the calculated (audit-linked) rows; a newer
        # period carries only a manual row, so by start_date it is the most
        # recent period but it would hide every "How was this calculated?" link.
        period_calc = ReportingPeriodFactory(
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )
        period_recent = ReportingPeriodFactory(
            start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        ParcelLedgerFactory(
            reporting_period=period_calc,
            source_type="calculated",
            effective_date=date(2024, 6, 15),
        )
        ParcelLedgerFactory(
            reporting_period=period_recent,
            source_type="manual_entry",
            effective_date=date(2026, 1, 15),
        )
        return period_calc, period_recent

    def test_defaults_to_most_recent_calculated_bearing_period(self, auth_client):
        period_calc, _ = self._two_periods_with_rows()

        response = auth_client.get(reverse("accounting:ledger_list"))

        assert response.status_code == 200
        assert response.context["period_auto_defaulted"] is True
        # period_id is rendered as a string for the dropdown selected-state check
        assert response.context["period_id"] == str(period_calc.pk)
        rows = list(response.context["page_obj"])
        assert rows, "default period should not be empty"
        assert all(r.reporting_period_id == period_calc.pk for r in rows)
        assert all(r.source_type == "calculated" for r in rows)

    def test_explicit_all_periods_stays_unfiltered(self, auth_client):
        self._two_periods_with_rows()

        # An explicit empty period= (the "All Periods" choice) must be honored.
        response = auth_client.get(reverse("accounting:ledger_list") + "?period=")

        assert response.status_code == 200
        assert response.context["period_auto_defaulted"] is False
        assert response.context["total_count"] == 2


class TestLedgerPresetChips:
    """143-05: the quick-filter chip row is retired ("This Period" duplicated
    the Period select; "Active Use Areas" is now the "Active use areas only"
    checkbox in the disclosed filter row). The chip elements are gone from
    the page, but the two mechanisms behind them survive under new controls:
    `active_areas` still narrows to active parcels, and `current_period_id`
    is still the value the ledger auto-defaults to on a bare landing, so the
    two never disagree. Class name kept for history; the assertions below
    test the surviving mechanism, not a chip."""

    def test_active_use_areas_filters_to_active_parcels(self, auth_client):
        from datetime import date

        active_parcel = ParcelFactory(status="active")
        inactive_parcel = ParcelFactory(status="inactive")
        ParcelLedgerFactory(parcel=active_parcel, effective_date=date(2024, 6, 1))
        ParcelLedgerFactory(parcel=inactive_parcel, effective_date=date(2024, 6, 1))

        response = auth_client.get(
            reverse("accounting:ledger_list") + "?active_areas=1"
        )

        assert response.status_code == 200
        # The "Active use areas only" checkbox's on-state is driven by this
        # context value (143-05; formerly the chip's on-state).
        assert response.context["active_areas"] == "1"
        rows = list(response.context["page_obj"])
        assert rows, "the active parcel's row should survive the filter"
        assert all(r.parcel.status == "active" for r in rows)
        assert all(r.parcel_id != inactive_parcel.pk for r in rows)

    def test_this_period_chip_target_matches_auto_default(self, auth_client):
        from datetime import date

        # current_period_id is no longer a chip's destination (143-05 removed
        # the chip); it must still equal the period the ledger auto-defaults
        # to on a bare landing, which is what the Period select shows.
        period_calc = ReportingPeriodFactory(
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )
        ParcelLedgerFactory(
            reporting_period=period_calc,
            source_type="calculated",
            effective_date=date(2024, 6, 15),
        )

        response = auth_client.get(reverse("accounting:ledger_list"))

        assert response.status_code == 200
        assert response.context["current_period_id"] == period_calc.pk
        assert response.context["period_id"] == str(period_calc.pk)


class TestAccessibility:
    """WCAG 2.1 AA / 508 remediation (2026-06-23, audit docs/2.0-ACCESSIBILITY-AUDIT.md):
    F1 keyboard-operable master rows, F3 a real per-page <h1>."""

    def test_master_rows_are_keyboard_activatable(self, auth_client):
        # F1 (2.1.1 Keyboard): the div[role=link] rows must carry an Enter-key
        # trigger, not rely on HTMX's default mouse-only click.
        WellFactory(name="MER-WELL-001")
        response = auth_client.get(reverse("wells:list"))
        body = response.content.decode()
        assert 'role="link"' in body
        assert "keyup[key=='Enter']" in body

    def test_page_has_one_real_h1_that_is_the_page_subject(self, auth_client):
        # F3 (1.3.1 / 2.4.6): exactly one <h1>, and it is the page subject,
        # NOT the static app name that used to live in the header. The
        # page_title block override only reaches the chain-defined h1, never
        # the {% include %}d header. Since Phase 143-02 that h1 is the visible
        # `.page-title` in the page head, not a screen-reader-only element
        # (tests/test_page_head.py holds the platform-wide guard).
        import re

        response = auth_client.get(reverse("accounting:ledger_list"))
        body = response.content.decode()
        assert body.count("<h1") == 1
        assert '<h1 class="app-header-title"' not in body
        h1 = re.search(r'<h1 class="page-title">(.*?)</h1>', body, re.S)
        assert h1 and "use ledger" in h1.group(1).lower()


class TestAccountDetailBillableLedger:
    """ISS-026: the per-parcel breakdown on account_detail must route through
    billable_ledger so a netted `calculated` row suppresses its gross
    `et_estimate` twin. Otherwise the same parcel-month is counted twice and the
    per-parcel usage shows ~double the (correct) account total in the same table."""

    def test_per_parcel_usage_suppresses_et_estimate_twin(self, auth_client):
        from datetime import date
        from decimal import Decimal

        account = WaterAccountFactory()
        parcel = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcel)

        # The normal post-run state: a gross et_estimate row AND its netted
        # calculated twin for the SAME (parcel, month), both stored negative.
        eff = date(2024, 6, 1)
        ParcelLedgerFactory(
            parcel=parcel, source_type="et_estimate",
            effective_date=eff, amount_acre_feet=Decimal("-10.0000"),
        )
        ParcelLedgerFactory(
            parcel=parcel, source_type="calculated",
            effective_date=eff, amount_acre_feet=Decimal("-10.0000"),
        )

        # ?period= (empty value, non-empty querystring) yields selected_period=None
        # and NO period filter — the state where summing both rows double-counts
        # (et_estimate rows carry reporting_period=None, so a period filter would
        # hide the bug).
        response = auth_client.get(
            reverse("accounting:account_detail", kwargs={"pk": account.pk})
            + "?period="
        )
        assert response.status_code == 200

        pbs = response.context["parcel_balances"]
        match = [b for b in pbs if b["parcel"] == parcel]
        assert len(match) == 1
        # 57-02: under the consumptive lens the groundwater SUPPLY is the billable
        # _balance_dict usage term, so the suppression still shows here: the
        # calculated row only -> groundwater 10, NOT 10 + 10 = 20.
        assert match[0]["groundwater"] == Decimal("10.0000")
        # And the per-parcel figure reconciles with the account-level total.
        assert response.context["balance"]["supplies"]["groundwater"] == Decimal(
            "10.0000"
        )


class TestAccountDetailConsumptiveLens:
    """57-02: the account-detail page reads in the corrected v1.10 lens —
    measured consumptive use (gross ET) vs. the surface/groundwater/precip
    supplies that met it. The headline correction: a canal/surface-only account
    that delivers a full year of water now shows real Consumptive Use where the
    old supply/usage framing reported Usage 0 (surface counted as supply, only
    groundwater counted as use)."""

    def test_canal_district_account_shows_consumptive_use_not_zero(self, auth_client):
        from datetime import date
        from decimal import Decimal

        from accounting.models import CalculationRun

        period = ReportingPeriodFactory(
            start_date=date(2023, 10, 1), end_date=date(2024, 9, 30)
        )
        account = WaterAccountFactory()
        parcel = ParcelFactory(parcel_number="MER-APN-031")
        WaterAccountParcelFactory(water_account=account, parcel=parcel)

        # Surface-only: a full year of canal delivery (stored NEGATIVE) and NO
        # groundwater extraction. Under the OLD model this account read Usage 0.
        ParcelLedgerFactory(
            parcel=parcel,
            reporting_period=period,
            source_type="surface_diversion",
            effective_date=date(2024, 6, 1),
            amount_acre_feet=Decimal("-50.0000"),
        )
        # The engine measured the crop's consumptive use (gross ET) regardless of
        # source — the spine quantity the corrected lens surfaces.
        CalculationRun.objects.create(
            parcel=parcel,
            period="2024-06",
            gross_et_af=Decimal("48.0000"),
            net_consumptive_use_af=Decimal("45.0000"),
            effective_precip_af=Decimal("3.0000"),
            final_af=Decimal("0"),
        )

        response = auth_client.get(
            reverse("accounting:account_detail", kwargs={"pk": account.pk})
            + f"?period={period.pk}"
        )
        assert response.status_code == 200

        balance = response.context["balance"]
        # The correction: consumptive use is now VISIBLE (was Usage 0).
        assert balance["consumptive_use_gross"] == Decimal("48.0000")
        # Met entirely by surface — no phantom groundwater on a no-well parcel.
        assert balance["supplies"]["surface"] == Decimal("50.0000")
        assert balance["supplies"]["groundwater"] == Decimal("0")
        assert balance["supplies"]["precip"] == Decimal("3.0000")

    def test_per_parcel_rows_sum_to_account_total(self, auth_client):
        from datetime import date
        from decimal import Decimal

        from accounting.models import CalculationRun

        period = ReportingPeriodFactory(
            start_date=date(2023, 10, 1), end_date=date(2024, 9, 30)
        )
        account = WaterAccountFactory()

        # Two parcels with different supply mixes so the sum is a real check.
        p1 = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=p1)
        ParcelLedgerFactory(
            parcel=p1, reporting_period=period, source_type="surface_diversion",
            effective_date=date(2024, 6, 1), amount_acre_feet=Decimal("-10.0000"),
        )
        CalculationRun.objects.create(
            parcel=p1, period="2024-06", gross_et_af=Decimal("12.0000"),
            net_consumptive_use_af=Decimal("10.0000"),
            effective_precip_af=Decimal("2.0000"), final_af=Decimal("0"),
        )

        p2 = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=p2)
        ParcelLedgerFactory(
            parcel=p2, reporting_period=period, source_type="calculated",
            effective_date=date(2024, 7, 1), amount_acre_feet=Decimal("-7.0000"),
        )
        CalculationRun.objects.create(
            parcel=p2, period="2024-07", gross_et_af=Decimal("9.0000"),
            net_consumptive_use_af=Decimal("8.0000"),
            effective_precip_af=Decimal("1.0000"), final_af=Decimal("0"),
        )

        response = auth_client.get(
            reverse("accounting:account_detail", kwargs={"pk": account.pk})
            + f"?period={period.pk}"
        )
        assert response.status_code == 200

        balance = response.context["balance"]
        pbs = response.context["parcel_balances"]
        for key in ("consumptive_use_gross", "supply_total"):
            assert sum(b[key] for b in pbs) == balance[key]
        for key in ("surface", "groundwater", "precip"):
            assert sum(b[key] for b in pbs) == balance["supplies"][key]


class TestDashboardActiveAccountScope:
    """ISS-032: the dashboard grand totals sum active accounts while the zone
    block covers all parcels. The account section is labeled so the two
    populations are not read as one."""

    def test_account_section_labeled_active(self, auth_client):
        from datetime import date

        ReportingPeriodFactory(
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )
        response = auth_client.get(reverse("accounting:dashboard"))
        assert response.status_code == 200
        assert b"Active water accounts" in response.content


class TestDashboardAttentionStrip:
    """E1: the dashboard's 'what needs attention' strip — a compact row of
    clickable exception pills (periods to close / stations down / accounts over
    budget) that collapses to an 'all clear' line when every count is zero."""

    def _down_station(self):
        """An active monitoring station with no data ever — classifies 'dead'."""
        from django.contrib.gis.geos import Point
        from datasync.models import DataSource, MonitoredStation

        source = DataSource.objects.create(name="USGS NWIS", code="usgs")
        return MonitoredStation.objects.create(
            data_source=source,
            external_station_id="11303500",
            station_name="San Joaquin R nr Vernalis",
            location=Point(-121.27, 37.67),
            is_active=True,
            last_data_at=None,
        )

    def test_strip_flags_unclosed_period(self, auth_client):
        """A period past its end date and not finalized shows the 'to close'
        pill, linking to the periods list."""
        ReportingPeriodFactory()  # default end_date is in the past, not finalized
        response = auth_client.get(reverse("accounting:dashboard"))
        html = response.content.decode()
        assert response.status_code == 200
        assert "Needs attention" in html
        assert "to close" in html
        assert reverse("accounting:periods_list") in html

    def test_strip_flags_down_station(self, auth_client):
        """An active station with dead data shows the 'station down' pill, linking
        to the monitoring stations list."""
        ReportingPeriodFactory(is_finalized=True)  # isolate: no period to close
        self._down_station()
        response = auth_client.get(reverse("accounting:dashboard"))
        html = response.content.decode()
        assert response.status_code == 200
        assert "Needs attention" in html
        assert "down" in html
        assert reverse("datasync:station_list") in html

    def test_strip_all_clear_when_nothing_flagged(self, auth_client):
        """A finalized period, no down stations, no over-budget accounts → the
        strip collapses to the 'All clear' line, with no exception pills."""
        ReportingPeriodFactory(is_finalized=True)
        response = auth_client.get(reverse("accounting:dashboard"))
        html = response.content.decode()
        assert response.status_code == 200
        assert "All clear" in html
        assert "Needs attention" not in html


class TestAccessibilityAndHelp:
    """E3 (skip-to-content link) + E4 (inline contextual help) — small
    cross-cutting UX wins that ride on the shared layout and the existing
    explainer-popout component."""

    def test_skip_link_present_and_targets_main(self, auth_client):
        """Every page carries a skip-to-content link as an early focusable
        element, pointing at the #main-content landmark on <main>."""
        response = auth_client.get(reverse("accounting:dashboard"))
        html = response.content.decode()
        assert response.status_code == 200
        assert 'href="#main-content"' in html
        assert "Skip to main content" in html
        assert 'id="main-content"' in html

    def test_dashboard_budget_columns_have_explainers(self, auth_client):
        """The budget-math columns carry the '?' explainer pop-out, cross-linked
        to the budgets-and-allocations help page."""
        from datetime import date
        from decimal import Decimal

        period = ReportingPeriodFactory(
            start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        zone = ZoneFactory()
        water_type = WaterTypeFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        account = WaterAccountFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
        AllocationPlanFactory(
            zone=zone,
            water_type=water_type,
            reporting_period=period,
            allocation_acre_feet=Decimal("100.0000"),
        )

        response = auth_client.get(
            reverse("accounting:dashboard") + f"?period={period.pk}"
        )
        html = response.content.decode()
        assert response.status_code == 200
        # The explainer button's aria-label is "Explain: <title>". The two
        # budget columns are the groundwater budget (136-01, DESIGN.md rule 12).
        assert "Explain: GW allocation" in html
        assert "Explain: GW remaining" in html
        assert reverse("budgets_allocations") in html


class TestResponsiveTables:
    """E5: dense tables (ledger, dashboard account/zone) carry a horizontal-scroll
    wrapper so a wide table scrolls within itself on a phone instead of dragging
    the whole page sideways.

    TWO utility classes deliver that property, and which one a page uses is a
    real design decision, not drift (see the comment beside them in
    ``static/css/app.css``):

      * ``.table-scroll`` — ``overflow-x: auto`` at EVERY width. What the
        dashboard's account and zone tables use.
      * ``.table-scroll-mobile`` — the same, confined to ``max-width: 767px``.
        The LEDGER needs the weaker variant because its sticky ``<thead>``
        sticks relative to ``.app-content``, and an overflow context on desktop
        would break it.

    ISS-081 read the dashboard as unwrapped because it grepped
    ``templates/accounting/dashboard.html``, which holds no ``<table>`` at all —
    both tables live in ``partials/_dashboard_content.html`` and have been
    wrapped since ``939a4ba``, the very commit that wrote this assertion. So the
    behaviour always shipped; only the assertion named the wrong class. It now
    pins the PROPERTY (a scroll container per dense table) rather than one
    implementation token, which is the same rule 101-02 wrote into DESIGN.md
    after a pinned sentence turned corrected copy red.
    """

    def test_dashboard_tables_have_mobile_scroll_wrapper(self, auth_client):
        from datetime import date
        from decimal import Decimal

        period = ReportingPeriodFactory(
            start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
        )
        zone = ZoneFactory()
        water_type = WaterTypeFactory()
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        account = WaterAccountFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
        AllocationPlanFactory(
            zone=zone,
            water_type=water_type,
            reporting_period=period,
            allocation_acre_feet=Decimal("100.0000"),
        )

        response = auth_client.get(
            reverse("accounting:dashboard") + f"?period={period.pk}"
        )
        html = response.content.decode()
        assert response.status_code == 200
        # Both the account and the zone table are wrapped. Count either utility,
        # so a page may pick the variant its sticky-header situation calls for.
        wrapped = html.count("table-scroll")
        assert wrapped >= 2, (
            f"expected the account and zone tables each inside a horizontal-scroll "
            f"container, found {wrapped}"
        )


class TestAccountingPages:
    def test_dashboard(self, auth_client):
        response = auth_client.get(reverse("accounting:dashboard"))
        assert response.status_code == 200

    def test_accounts_list(self, auth_client):
        response = auth_client.get(reverse("accounting:accounts_list"))
        assert response.status_code == 200

    # Water Accounts — Bucket 1 master-detail workspace (v2.0 conversion).
    def test_accounts_list_is_master_detail(self, auth_client):
        """The list is the shared workspace shell: clickable rows (no flat table)
        that swap each account's detail into #detail-body, plus a resting empty
        pane until one is picked."""
        WaterAccountFactory(account_number="ACC-DEEP", name="Deep Link Farms")
        response = auth_client.get(reverse("accounting:accounts_list"))
        assert response.status_code == 200
        body = response.content.decode()
        # On the shared shell, with a clickable master row (not the old table).
        assert "workspace-split" in body
        assert "data-row" in body
        assert "ACC-DEEP" in body
        # Resting empty pane before a selection (the E6 orientation panel).
        assert "Select an account" in body
        assert "Choose one from the list" in body

    def test_accounts_list_selected_preloads_detail_pane(self, auth_client):
        """?selected=<pk> renders the chosen account's detail server-side so a
        reload or deep link lands on the same workspace view."""
        account = WaterAccountFactory(account_number="ACC-SEL", name="Selected Farms")
        response = auth_client.get(
            reverse("accounting:accounts_list"), {"selected": account.pk}
        )
        assert response.status_code == 200
        body = response.content.decode()
        # The pane is pre-rendered: account header + its interactive workflows.
        assert "Account balance" in body
        assert 'id="parcel-assignments"' in body
        assert "Open full page" in body

    def test_account_detail_hx_request_returns_pane_fragment(self, auth_client):
        """An HTMX row click (no period param) gets just the detail-pane fragment
        swapped into #detail-body — not the full standalone page shell."""
        account = WaterAccountFactory(account_number="ACC-HX")
        response = auth_client.get(
            reverse("accounting:account_detail", kwargs={"pk": account.pk}),
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Account balance" in body
        # Fragment, not a full document: no <html> shell from base.html.
        assert "<html" not in body.lower()

    def test_periods_list(self, auth_client):
        response = auth_client.get(reverse("accounting:periods_list"))
        assert response.status_code == 200

    def test_allocations_list(self, auth_client):
        response = auth_client.get(reverse("accounting:allocations_list"))
        assert response.status_code == 200

    def test_ledger_list(self, auth_client):
        response = auth_client.get(reverse("accounting:ledger_list"))
        assert response.status_code == 200

    def test_account_create_get(self, auth_client):
        response = auth_client.get(reverse("accounting:account_create"))
        assert response.status_code == 200

    def test_period_create_get(self, auth_client):
        response = auth_client.get(reverse("accounting:period_create"))
        assert response.status_code == 200


class TestPeriodDetailPage:
    """143-06, R-034: the water-year page leads with the period, not a tile
    row titled 'Summary' whose larger figure was a count of ledger rows."""

    def test_no_summary_tile_and_the_ledger_count_links_to_the_ledger(self, auth_client):
        from datetime import date
        from decimal import Decimal

        period = ReportingPeriodFactory(
            name="WY 2025-2026",
            start_date=date(2025, 10, 1),
            end_date=date(2026, 9, 30),
        )
        # An allocation has to exist for the panel's ledger-count note to render
        # at all (the "No allocations for this period" branch has no note and
        # no link); the demonstration data always carries at least one.
        AllocationPlanFactory(
            zone=ZoneFactory(),
            water_type=WaterTypeFactory(name="Groundwater", code="GW"),
            reporting_period=period,
            allocation_acre_feet=Decimal("500.0000"),
        )
        response = auth_client.get(
            reverse("accounting:period_detail", kwargs={"pk": period.pk})
        )
        assert response.status_code == 200
        html = response.content.decode()

        assert ">Summary<" not in html
        ledger_href = f"{reverse('accounting:ledger_list')}?period={period.pk}"
        assert f'href="{ledger_href}"' in html

    def test_the_panel_prints_per_type_totals_and_not_their_sum(self, auth_client):
        from datetime import date
        from decimal import Decimal

        period = ReportingPeriodFactory(
            name="WY 2025-2026",
            start_date=date(2025, 10, 1),
            end_date=date(2026, 9, 30),
        )
        surface = WaterTypeFactory(name="Surface Water", code="SW")
        groundwater = WaterTypeFactory(name="Groundwater", code="GW")
        AllocationPlanFactory(
            zone=ZoneFactory(),
            water_type=surface,
            reporting_period=period,
            allocation_acre_feet=Decimal("148500.0000"),
        )
        AllocationPlanFactory(
            zone=ZoneFactory(),
            water_type=groundwater,
            reporting_period=period,
            allocation_acre_feet=Decimal("11171.4600"),
        )
        response = auth_client.get(
            reverse("accounting:period_detail", kwargs={"pk": period.pk})
        )
        assert response.status_code == 200
        html = response.content.decode()

        assert "148,500.00" in html
        assert "11,171.46" in html
        assert "159,671.46" not in html


# ---------------------------------------------------------------------------
# Parcels pages (login required)
# ---------------------------------------------------------------------------


class TestParcelsPages:
    def test_parcels_list(self, auth_client):
        response = auth_client.get(reverse("parcels:list"))
        assert response.status_code == 200

    def test_parcels_list_redirects_anonymous(self, client):
        response = client.get(reverse("parcels:list"))
        assert response.status_code == 302

    def test_parcel_detail(self, auth_client):
        parcel = ParcelFactory()
        response = auth_client.get(reverse("parcels:detail", kwargs={"pk": parcel.pk}))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Wells pages (login required)
# ---------------------------------------------------------------------------


class TestWellsPages:
    def test_wells_list(self, auth_client):
        response = auth_client.get(reverse("wells:list"))
        assert response.status_code == 200

    def test_wells_list_redirects_anonymous(self, client):
        response = client.get(reverse("wells:list"))
        assert response.status_code == 302

    def test_well_detail(self, auth_client):
        well = WellFactory()
        response = auth_client.get(reverse("wells:detail", kwargs={"pk": well.pk}))
        assert response.status_code == 200

    def test_wells_list_names_the_depth(self, auth_client):
        """143-10 (R-110): the list's master-row figure says what it measures."""
        from decimal import Decimal

        WellFactory(name="Depth-named well", depth_ft=Decimal("340.00"))
        response = auth_client.get(reverse("wells:list"))
        assert response.status_code == 200
        assert "Depth 340.00 ft" in response.content.decode()


# ---------------------------------------------------------------------------
# Surface water pages (login required)
# ---------------------------------------------------------------------------


class TestSurfacePages:
    def test_water_rights_list(self, auth_client):
        response = auth_client.get(reverse("surface:water_rights_list"))
        assert response.status_code == 200

    def test_water_rights_list_redirects_anonymous(self, client):
        response = client.get(reverse("surface:water_rights_list"))
        assert response.status_code == 302

    # Water Rights — Bucket 3 overview (full-width list -> detail page, no map).
    def test_water_right_detail(self, auth_client):
        right = WaterRightFactory()
        response = auth_client.get(
            reverse("surface:detail", kwargs={"pk": right.pk})
        )
        assert response.status_code == 200

    def test_water_rights_list_is_bucket3_overview(self, auth_client):
        """The overview is a finder, not a master-detail workspace: a full-width
        list whose rows link to each right's own detail page. Water rights have
        no geometry, so unlike the other Bucket-3 screens there is no overview
        map and no in-page detail pane."""
        right = WaterRightFactory(right_id="WR-DEEPLINK")
        response = auth_client.get(reverse("surface:water_rights_list"))
        assert response.status_code == 200
        body = response.content.decode()
        # Rows link out to the standalone detail page...
        assert reverse("surface:detail", kwargs={"pk": right.pk}) in body
        assert "WR-DEEPLINK" in body
        # ...with no master-detail pane shell and no overview map on this screen.
        assert "detail-body" not in body
        assert "overview-map" not in body

    def test_water_right_detail_hx_request_returns_pane_fragment(self, auth_client):
        """An HTMX row click gets just the detail-pane fragment (swapped into
        #detail-body), not the full standalone page wrapped in base.html."""
        right = WaterRightFactory(right_id="WR-FRAGMENT")
        response = auth_client.get(
            reverse("surface:detail", kwargs={"pk": right.pk}),
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "WR-FRAGMENT" in body
        # Fragment, not full document: no <html> shell from base.html.
        assert "<html" not in body.lower()

    def test_curtailed_right_carries_no_demo_badge_on_the_list_but_one_on_detail(
        self, auth_client
    ):
        """143-10 (R-118): the list's notice above the table already says the
        set is mixed and every id already ends -DEMO, so a pill on one row of
        several read as though the others were something else
        (`_status_badge.html`'s `demo_marker=False`, list-only). The detail
        page is untouched -- `tests/test_demo_marker.py` already pins it."""
        from core.models import SiteConfig

        SiteConfig.objects.create(agency_name="Demo GSA", demonstration_mode=True)
        right = WaterRightFactory(status="curtailed")

        list_body = auth_client.get(reverse("surface:water_rights_list")).content.decode()
        assert "badge-demo" not in list_body

        detail_body = auth_client.get(
            reverse("surface:detail", kwargs={"pk": right.pk})
        ).content.decode()
        assert "badge-demo" in detail_body

    # Surface Diversions — Bucket 3 overview (overview map + list -> detail page).
    def test_pod_list(self, auth_client):
        response = auth_client.get(reverse("surface:pod_list"))
        assert response.status_code == 200

    def test_pod_list_redirects_anonymous(self, client):
        response = client.get(reverse("surface:pod_list"))
        assert response.status_code == 302

    def test_pod_detail(self, auth_client):
        pod = PointOfDiversionFactory()
        response = auth_client.get(reverse("surface:pod_detail", kwargs={"pk": pod.pk}))
        assert response.status_code == 200

    def test_pod_list_is_bucket3_overview(self, auth_client):
        """The overview is a finder, not a master-detail workspace: an overview
        map up top, and list rows that link to each POD's own full detail page
        (no in-page detail pane)."""
        pod = PointOfDiversionFactory(name="Deep Link Weir")
        response = auth_client.get(reverse("surface:pod_list"))
        assert response.status_code == 200
        body = response.content.decode()
        # Overview map container is present.
        assert 'id="pods-overview-map"' in body
        # Rows link out to the standalone detail page...
        assert reverse("surface:pod_detail", kwargs={"pk": pod.pk}) in body
        assert "Deep Link Weir" in body
        # ...and there is no master-detail pane shell on the overview.
        assert "detail-body" not in body

    def test_pod_detail_hx_request_returns_pane_fragment(self, auth_client):
        """An HTMX row click gets just the detail-pane fragment (swapped into
        #detail-body), not the full standalone page wrapped in base.html."""
        pod = PointOfDiversionFactory(name="Fragment Headgate")
        response = auth_client.get(
            reverse("surface:pod_detail", kwargs={"pk": pod.pk}),
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Fragment Headgate" in body
        # Fragment, not full document: no <html> shell from base.html.
        assert "<html" not in body.lower()


# ---------------------------------------------------------------------------
# Recharge pages (login required)
# ---------------------------------------------------------------------------


class TestRechargePages:
    def test_recharge_list(self, auth_client):
        response = auth_client.get(reverse("recharge:list"))
        assert response.status_code == 200

    def test_recharge_list_redirects_anonymous(self, client):
        response = client.get(reverse("recharge:list"))
        assert response.status_code == 302

    # Recharge — Bucket 3 overview (overview map + list -> detail page).
    def test_recharge_list_is_bucket3_overview(self, auth_client):
        """The overview is a finder, not a master-detail workspace: an overview
        map up top, and list rows that link to each site's own full detail page
        (no in-page detail pane)."""
        site = RechargeSiteFactory(name="Deep Link Basin")
        response = auth_client.get(reverse("recharge:list"))
        assert response.status_code == 200
        body = response.content.decode()
        # Overview map container is present.
        assert 'id="recharge-overview-map"' in body
        # Rows link out to the standalone detail page...
        assert reverse("recharge:detail", kwargs={"pk": site.pk}) in body
        assert "Deep Link Basin" in body
        # ...and there is no master-detail pane shell on the overview.
        assert "detail-body" not in body


# ---------------------------------------------------------------------------
# 143-10 (R-112 well and add): the well page's account grid and the add
# page's stretched map column, each a rendered-markup / CSS-text assertion,
# never a screenshot measurement re-derived here.
# ---------------------------------------------------------------------------


class TestAccountGridOnWellsAndAddPage:
    def test_well_page_uses_the_account_grid_with_a_full_width_measurement_card(
        self, auth_client
    ):
        from datetime import datetime
        from decimal import Decimal

        from django.utils import timezone

        from measurements.models import Meter, MeterReading, WaterMeasurement
        from standards.models import ObservedProperty

        well = WellFactory(name="Grid-checked well")
        meter = Meter.objects.create(serial_number="MTR-GRID-1", unit="acre_feet")
        from wells.models import WellMeter

        WellMeter.objects.create(well=well, meter=meter, is_current=True)
        MeterReading.objects.create(
            meter=meter,
            reading_date=timezone.make_aware(datetime(2025, 11, 30, 14, 0)),
            previous_value=Decimal("100.0000"), current_value=Decimal("110.0000"),
            calculated_volume=Decimal("10.0000"), quality="approved",
        )
        prop, _ = ObservedProperty.objects.get_or_create(
            key="groundwater_level_depth", defaults={"name": "Depth to groundwater"}
        )
        WaterMeasurement.objects.create(
            name="sounder", measurement_type="groundwater_level", observed_property=prop,
            value=Decimal("86.9400"), unit="ft",
            measurement_date=timezone.make_aware(datetime(2025, 11, 10, 10, 0)),
            well=well,
        )

        body = auth_client.get(reverse("wells:detail", kwargs={"pk": well.pk})).content.decode()
        assert "page-grid-account" in body

        heading_pos = body.index("Measurement history")
        assert "page-grid-account-full" in body[heading_pos - 300:heading_pos]

        # Bounded by the next <script> tag: the persistent-map script is the
        # last thing in the pane, after Measurement history, so everything
        # between the heading and it is this card's own two tables.
        card = body[heading_pos:body.index("<script>", heading_pos)]
        assert card.count("<table") == 2

    def test_add_page_map_form_layout_stretches_the_shorter_column(self):
        from pathlib import Path

        app_css = (Path(__file__).resolve().parent.parent / "static/css/app.css").read_text()
        # The SAME literal block test_template_hygiene.py's style of check reads:
        # the `.map-form-layout` rule (outside the phone-width media query,
        # which resets it to one column) must carry the stretch rule that
        # makes the map column run the taller form column's height.
        block_start = app_css.index("/* Infrastructure form */")
        block = app_css[block_start:block_start + app_css[block_start:].index("}") + 1]
        assert ".map-form-layout" in block
        assert "align-items: stretch;" in block


class TestDatasyncPages:
    def test_station_list(self, auth_client):
        response = auth_client.get(reverse("datasync:station_list"))
        assert response.status_code == 200

    def test_station_list_redirects_anonymous(self, client):
        response = client.get(reverse("datasync:station_list"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Reporting pages (login required)
# ---------------------------------------------------------------------------


class TestReportingPages:
    def test_report_list(self, auth_client):
        response = auth_client.get(reverse("reporting:report_list"))
        assert response.status_code == 200

    def test_report_list_redirects_anonymous(self, client):
        response = client.get(reverse("reporting:report_list"))
        assert response.status_code == 302

    def test_report_list_is_bucket3_finder(self, auth_client):
        """The overview is a finder, not a master-detail workspace: a full-width
        page that leads with the 'Start a filing' actions and a history table.
        A report has no geometry, so there is no map and no in-page detail pane."""
        response = auth_client.get(reverse("reporting:report_list"))
        html = response.content.decode()
        assert response.status_code == 200
        assert "Start a filing" in html
        # No master-detail shell and no map on this screen.
        assert "workspace-split" not in html
        assert "detail-body" not in html
        assert "maplibre-gl.js" not in html

    def test_report_list_rows_link_to_detail_page(self, auth_client):
        """History rows link out to each submission's own standalone detail page
        (full navigation), not an in-page pane swap."""
        sub = _report_submission()
        response = auth_client.get(reverse("reporting:report_list"))
        html = response.content.decode()
        assert response.status_code == 200
        assert reverse("reporting:report_detail", args=[sub.pk]) in html
        assert sub.report_template.name in html

    def test_report_list_htmx_returns_history_partial(self, auth_client):
        """A search/filter swap (HX-Request) returns just the history table, not
        the whole page."""
        _report_submission()
        response = auth_client.get(
            reverse("reporting:report_list"), HTTP_HX_REQUEST="true"
        )
        html = response.content.decode()
        assert response.status_code == 200
        assert "count-pill" in html
        assert "data-table" in html
        assert "<html" not in html.lower()  # fragment, not a full document

    def test_report_detail_htmx_returns_pane_fragment(self, auth_client):
        """An in-page HTMX caller gets just the detail-pane body fragment, not a
        full standalone page wrapped in base.html."""
        sub = _report_submission()
        response = auth_client.get(
            reverse("reporting:report_detail", args=[sub.pk]), HTTP_HX_REQUEST="true"
        )
        html = response.content.decode()
        assert response.status_code == 200
        assert "pane-header" in html
        assert "<html" not in html.lower()  # it's the body fragment, not a page

    def test_report_detail_full_page_wraps_pane(self, auth_client):
        """The standalone page (the history row's link target) wraps the shared
        pane body with the breadcrumb and a back-link to the overview."""
        sub = _report_submission()
        response = auth_client.get(reverse("reporting:report_detail", args=[sub.pk]))
        html = response.content.decode()
        assert response.status_code == 200
        assert "breadcrumb" in html
        assert "status-section" in html  # the shared pane body is included
        assert reverse("reporting:report_list") in html  # back-link to the overview
