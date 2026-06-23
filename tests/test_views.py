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

    def test_getting_started_redirects_anonymous(self, client):
        response = client.get(reverse("getting_started"))
        assert response.status_code == 302

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
        water_type = WaterTypeFactory()

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
        assert b"Active Water Accounts" in response.content


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
        # Resting empty pane before a selection.
        assert "Select an account from the list" in body

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
        assert "Account Balance" in body
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
        assert "Account Balance" in body
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
# Datasync pages (login required)
# ---------------------------------------------------------------------------


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

    def test_report_list_is_workspace_with_action_list(self, auth_client):
        """The overview renders the v2.0 workspace shell, leads with the
        action-list, and rests in the empty detail pane when nothing is picked."""
        response = auth_client.get(reverse("reporting:report_list"))
        html = response.content.decode()
        assert response.status_code == 200
        assert "workspace-split" in html
        assert "Start a filing" in html
        assert "Select a report from the history" in html  # resting empty pane
        assert "maplibre-gl.js" not in html  # map-less: MapLibre never loads

    def test_report_list_deeplink_preloads_detail_pane(self, auth_client):
        """?selected=<pk> pre-loads that submission into the detail pane (deep
        link / reload), not the resting empty state."""
        sub = _report_submission()
        response = auth_client.get(
            reverse("reporting:report_list"), {"selected": sub.pk}
        )
        html = response.content.decode()
        assert response.status_code == 200
        assert "pane-header" in html
        assert sub.report_template.name in html
        assert "is-selected" in html  # the matching history row is highlighted
        assert "Select a report from the history" not in html

    def test_report_list_htmx_returns_history_partial(self, auth_client):
        """A search/filter swap (HX-Request) returns just the history list, not
        the whole workspace."""
        _report_submission()
        response = auth_client.get(
            reverse("reporting:report_list"), HTTP_HX_REQUEST="true"
        )
        html = response.content.decode()
        assert response.status_code == 200
        assert "count-pill" in html
        assert "workspace-split" not in html

    def test_report_detail_htmx_returns_pane_only(self, auth_client):
        """A row click (HX-Request) swaps in the detail pane partial, with the
        'open full page' escape — not a full standalone page."""
        sub = _report_submission()
        response = auth_client.get(
            reverse("reporting:report_detail", args=[sub.pk]), HTTP_HX_REQUEST="true"
        )
        html = response.content.decode()
        assert response.status_code == 200
        assert "pane-header" in html
        assert "Open full page" in html
        assert "workspace-split" not in html  # it's the body fragment, not a page

    def test_report_detail_full_page_wraps_pane(self, auth_client):
        """The standalone page (deep link / escape) wraps the same pane body with
        the breadcrumb and a back-link to the overview."""
        sub = _report_submission()
        response = auth_client.get(reverse("reporting:report_detail", args=[sub.pk]))
        html = response.content.decode()
        assert response.status_code == 200
        assert "breadcrumb" in html
        assert "status-section" in html  # the shared pane body is included
        assert f"?selected={sub.pk}" in html  # back-link returns to the workspace
