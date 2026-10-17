# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calculation page (148-03; rebuilt as the equation panel 2026-10-11).

The page answers one question, where this field's groundwater extraction
(estimated) for the month came from, and only a month on a field with a well
and no meter reading has that question. These tests build every ``CalculationRun`` directly with
the ORM and type the expected figures in by hand (10.0000 less 1.0000 less
4.0000 is 5.0000; 5.0000 divided by 0.75 is 6.6667), so a page-level
regression can never be confused with the engine's own arithmetic.

Parcel numbers here are fictional so the session-scoped Merced seed cannot
collide with them. Runs in the web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from accounting.services import parcel_receipt_periods, parcel_run_periods
from core.models import SiteConfig
from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

User = get_user_model()

pytestmark = pytest.mark.django_db

#: 150.1-02 (2026-10-11): the page is three equations in the engineer's terms.
#: Each label sits directly above its
#: figure (`.budget-seg-label`), in the order the equations run.
LABELS = (
    "Crop ET",
    "Effective precipitation",
    "ETAW",
    "ETAW met by surface water",
    "ETAW met by groundwater",
    "Irrigation efficiency",
    "Groundwater extraction (estimated)",
)
METER_LINE = "A meter reading for June 2026 would replace this estimate."
#: Words the owner rejected on this page, never to return (2026-09-28 to
#: 2026-10-11: the step table, the receipt table, the coined terms).
REJECTED = (
    "Calculation steps",
    "In (AF)",
    "Out (AF)",
    "Amount (AF)",
    "Left (AF)",
    "Clamp",
    "clamp at floor",
    "facility-only",
    "Zero out",
    "Groundwater consumed",
    "groundwater consumed",
    "no supply on record",
    "Canal water the crop did not need",
    "Crop water use",
    "rain the crop could use",
    "canal water the crop could use",
    "well water the crop used",
    "share of pumped water",
    "Where it comes from",
    "How was this calculated?",
)
NO_WELL_SENTENCE = (
    "This field has no well on record, so there is no groundwater extraction "
    "to estimate."
)
METERED_SENTENCE = (
    "This field has a meter reading for {month}, so the groundwater extraction "
    "is the reading and OpenH2O estimates nothing."
)


def _user():
    # A page may be fetched more than once in a test; each fetch signs in a
    # fresh reader rather than reusing a username the DB already holds.
    name = f"receipt-reader-{User.objects.count() + 1}"
    return User.objects.create_user(
        username=name, email=f"{name}@example.com", password="x", is_active=True,
    )


def _client():
    client = Client()
    client.force_login(_user())
    return client


def _canal_step(delivered="5.3333", efficiency_source="agency"):
    return {
        "step_type": "subtract_surface_water",
        "label": "Subtract delivery × irrigation efficiency",
        "detail": {
            "delivered_af": delivered,
            "efficiency": "0.750",
            "efficiency_source": efficiency_source,
            "consumed_af": "4.0000",
            "surface_water_af": "4.0000",
        },
        "input_af": "9.0000",
        "output_af": "5.0000",
    }


def _well_run(parcel, period="2026-06", **overrides):
    """The hand-built receipt: crop 10.0000, rain 1.0000, canal 4.0000 (a
    5.3333 delivery times 0.75), well water 5.0000, pumped 6.6667 at the
    same 75%, the Delivery Settings default the run stamped (150.2-02)."""
    fields = dict(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal("10.0000"),
        net_consumptive_use_af=Decimal("9.0000"),
        effective_precip_af=Decimal("1.0000"),
        surface_delivered_af=Decimal("5.3333"),
        surface_efficiency=Decimal("0.750"),
        surface_water_af=Decimal("4.0000"),
        final_af=Decimal("5.0000"),
        gw_extracted_af=Decimal("6.6667"),
        groundwater_application_efficiency=Decimal("0.750"),
        groundwater_efficiency_source="agency",
        over_delivery_af=Decimal("0.0000"),
        residual_disposition="groundwater",
        breakdown=[_canal_step()],
        methodology_plan_name="Default Methodology",
    )
    fields.update(overrides)
    return CalculationRun.objects.create(**fields)


def _zero_run(parcel, period="2025-12", **overrides):
    """A well month rain and canal water covered: crop 8.0000, rain 8.0000,
    canal 4.0000, well water 0, and 4.0000 of the canal water beyond what
    the crop could use."""
    fields = dict(
        gross_et_af=Decimal("8.0000"),
        net_consumptive_use_af=Decimal("0.0000"),
        effective_precip_af=Decimal("8.0000"),
        final_af=Decimal("0.0000"),
        gw_extracted_af=Decimal("0.0000"),
        over_delivery_af=Decimal("4.0000"),
    )
    fields.update(overrides)
    return _well_run(parcel, period, **fields)


def _page(parcel, period):
    resp = _client().get(
        reverse(
            "accounting:calculation_run_detail",
            kwargs={"parcel_id": parcel.pk, "period": period},
        )
    )
    assert resp.status_code == 200
    return resp.content.decode()


def _field_page(parcel, period_id=None):
    url = reverse("parcels:detail", args=[parcel.pk])
    if period_id is not None:
        url = f"{url}?period={period_id}"
    resp = _client().get(url, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    return resp.content.decode()


class TestTheReceipt:
    def test_three_equations_in_hand_figures(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-001", area_acres=Decimal("12.00"))
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        assert "<title>Groundwater extraction (estimated), RCPT-APN-001, June 2026" in html
        # The labels in the order the three equations run.
        positions = [html.index(f'<div class="budget-seg-label">{label}</div>') for label in LABELS]
        assert positions == sorted(positions)
        # 10 - 1 = 9; 9 - 4 = 5; 5 / 75% = 6.67.
        for figure in ("10.00", "1.00", "9.00", "4.00", "5.00", "75%", "6.67"):
            assert f">{figure}<" in html, figure
        assert html.count("&minus;</div>") == 2
        assert html.count("&divide;</div>") == 1
        assert html.count("&equals;</div>") == 3
        # Two decimals; the run's own four-decimal value rides in the title.
        assert 'title="6.6667 acre-feet"' in html
        assert 'title="5.0000 acre-feet"' in html
        assert 'title="9.0000 acre-feet"' in html
        assert METER_LINE in html
        assert "Methodology: Default Methodology." in html
        assert "12.00 acres" in html
        assert "June 2026" in html

    def test_each_figure_names_its_source_and_setting(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-002")
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        assert "OpenET satellite estimate" in html
        assert "crop ET minus effective precipitation" in html
        assert "delivery &times; irrigation efficiency, up to ETAW" in html
        assert "<span>Delivered</span><b" in html
        assert ">5.33</b>" in html
        assert "Irrigation efficiency<span class=\"budget-breakdown-note\">Delivery Settings default</span>" in html
        assert "<b>75%</b>" in html
        # 150.2-02: the divisor names its source the same way the canal row does.
        assert '<div class="budget-seg-caption">Delivery Settings default</div>' in html
        assert "set on Delivery Settings when this month was calculated" not in html
        assert "charged to the groundwater allocation" in html
        assert "recorded on the field's ledger" in html
        # A field's own delivery (no split row on the ledger) says nothing
        # about a split; no excess, no excess row.
        assert "share of the headgate total" not in html
        assert "Surface water in excess of ETAW" not in html
        # No sentence writes the arithmetic out.
        assert "10.00 &minus;" not in html

    def test_a_delivery_divided_up_by_etaw_says_so(self):
        from accounting.ledger_words import DELIVERY_SHARE_BY_USE

        parcel = ParcelFactory(parcel_number="RCPT-APN-003")
        _well_run(parcel)
        ParcelLedgerFactory(
            parcel=parcel,
            source_type="surface_diversion",
            effective_date=dt.date(2026, 6, 15),
            transaction_date=dt.date(2026, 6, 15),
            amount_acre_feet=Decimal("-5.3333"),
            description=f"Share of 100.00 AF delivered from a canal, {DELIVERY_SHARE_BY_USE}",
            divided_from_headgate=True,  # 149-01: the split's rows say so in a column
        )
        html = _page(parcel, "2026-06")
        assert "share of the headgate total" in html

    def test_the_rejected_words_are_gone(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-004")
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        for words in REJECTED:
            assert words not in html, words
        # "measured" is never said of a satellite or weather estimate.
        assert "measured" not in html.lower()

    def test_the_percentages_are_the_runs_own_and_not_the_live_setting(self):
        """ISS-177's rule: both percentages are the run's own stamps (the 90%
        its canal water was multiplied by, the 70% its groundwater was divided
        by), so a change to Delivery Settings after the run moves nothing the
        page says."""
        parcel = ParcelFactory(parcel_number="RCPT-APN-005")
        _well_run(
            parcel,
            surface_efficiency=Decimal("0.900"),
            final_af=Decimal("7.0000"),
            gw_extracted_af=Decimal("10.0000"),
            groundwater_application_efficiency=Decimal("0.700"),
        )
        config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Receipt Test Agency"})
        config.default_irrigation_efficiency = Decimal("0.600")
        config.save()
        html = _page(parcel, "2026-06")
        assert ">70%<" in html
        assert "<b>90%</b>" in html
        assert "60%" not in html

    def test_a_run_from_before_the_stamp_reads_its_efficiency_back(self):
        """No stamp: final_af / gw_extracted_af, 5.0000 / 6.2500 = 80%."""
        parcel = ParcelFactory(parcel_number="RCPT-APN-005B")
        _well_run(
            parcel,
            gw_extracted_af=Decimal("6.2500"),
            groundwater_application_efficiency=None,
            groundwater_efficiency_source="",
        )
        html = _page(parcel, "2026-06")
        assert ">80%<" in html
        assert "Delivery Settings default</div>" not in html

    def test_the_efficiency_names_where_it_came_from(self):
        from parcels.models import IrrigationMethod, ParcelIrrigationMethod

        parcel = ParcelFactory(parcel_number="RCPT-APN-005C")
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        assert '<div class="budget-seg-caption">Delivery Settings default</div>' in html

        method = IrrigationMethod.objects.create(
            name="Receipt test pivot", assigned_efficiency=Decimal("0.850"),
            range_low=Decimal("0.800"), range_high=Decimal("0.900"),
        )
        ParcelIrrigationMethod.objects.create(parcel=parcel, method=method)
        _well_run(
            parcel, "2026-07",
            gw_extracted_af=Decimal("5.8824"),
            groundwater_application_efficiency=Decimal("0.850"),
            groundwater_efficiency_source="method",
        )
        html = _page(parcel, "2026-07")
        assert (
            '<div class="budget-seg-caption">Receipt test pivot, '
            "the field's irrigation method</div>"
        ) in html

    def test_a_run_from_before_extraction_was_stamped_stops_at_etaw_met_by_groundwater(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-006")
        _well_run(parcel, gw_extracted_af=None)
        html = _page(parcel, "2026-06")
        assert "&divide;" not in html
        assert '<div class="budget-seg-label">Groundwater extraction (estimated)</div>' not in html
        assert 'class="budget-seg budget-seg--result"' in html
        assert '<div class="budget-seg-label">ETAW met by groundwater</div>' in html

    def test_etaw_met_by_surface_water_stops_at_etaw(self):
        """The run's surface_water_af is the delivery times the efficiency,
        uncapped; the panel shows the part up to ETAW, and the excess as its
        own breakdown row from the run's own over_delivery_af."""
        parcel = ParcelFactory(parcel_number="RCPT-APN-007")
        _well_run(
            parcel,
            surface_water_af=Decimal("12.0000"),
            final_af=Decimal("0.0000"),
            gw_extracted_af=Decimal("0.0000"),
            over_delivery_af=Decimal("3.0000"),
        )
        html = _page(parcel, "2026-06")
        assert 'title="9.0000 acre-feet">9.00<' in html  # ETAW, and ETAW met by surface water
        assert "12.00" not in html
        assert "Surface water in excess of ETAW" in html
        assert 'title="3.0000 acre-feet">3.00</b>' in html

    def test_a_floor_above_zero_is_named(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-008")
        breakdown = [_canal_step(), {"step_type": "clamp_floor", "detail": {"floor": "0.5000"}}]
        _well_run(
            parcel,
            surface_water_af=Decimal("9.0000"),
            final_af=Decimal("0.5000"),
            gw_extracted_af=Decimal("0.6250"),
            breakdown=breakdown,
        )
        html = _page(parcel, "2026-06")
        assert "<span>Floor<span class=\"budget-breakdown-note\">Methodology Settings</span></span><b>0.50</b>" in html
        _well_run(parcel, "2026-07", breakdown=breakdown)
        html = _page(parcel, "2026-07")
        assert "<span>Floor" not in html


class TestAZeroMonth:
    """A well month with no ETAW met by groundwater."""

    def test_shows_the_same_three_equations_at_zero(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-010")
        _zero_run(parcel)
        html = _page(parcel, "2025-12")
        # Rain met crop ET: ETAW 0, so none of the 4.00 meets ETAW.
        assert 'title="0.0000 acre-feet">0.00<' in html
        assert "Surface water in excess of ETAW" in html
        assert 'title="4.0000 acre-feet">4.00</b>' in html
        # 150.2-02: the run stamped the field's efficiency even though there
        # was nothing to divide, so the zero month shows it, not a dash.
        assert "not applied this month" not in html
        assert ">75%<" in html
        assert '<div class="budget-seg-caption">Delivery Settings default</div>' in html
        # The default treatment (not credited) says nothing more.
        assert "Credited to this field" not in html
        assert "its own line" not in html
        assert "A meter reading for December 2025 would replace this estimate." in html

    def test_under_the_credited_setting_the_two_parts_are_shown(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-012")
        _zero_run(
            parcel,
            over_delivery_treatment="credited",
            over_delivery_leave_behind=Decimal("0.100"),
            over_delivery_credited_af=Decimal("3.6000"),
        )
        html = _page(parcel, "2025-12")
        assert "<span>Credited to this field</span><b>3.60</b>" in html
        assert "<span>Left in the basin (10%)</span><b>0.40</b>" in html

    def test_under_the_named_line_setting_the_excess_says_where_it_shows(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-013")
        _zero_run(parcel, over_delivery_treatment="named_line")
        html = _page(parcel, "2025-12")
        assert "shown on the field's page as its own line" in html

    def test_the_breakdown_is_the_runs_own_stamp_not_the_live_setting(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-014")
        _zero_run(parcel, over_delivery_treatment="not_credited")
        config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Receipt Test Agency"})
        config.over_delivery_treatment = "credited"
        config.over_delivery_leave_behind = Decimal("0.100")
        config.save()
        html = _page(parcel, "2025-12")
        assert "Credited to this field" not in html


class TestTheShortPage:
    """A month with nothing to estimate answers a direct URL with one
    sentence and a link back to the field. Not a 404."""

    def test_a_no_well_month(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-020")
        _well_run(
            parcel,
            residual_disposition="unmet_demand",
            gw_extracted_af=None,
            unmet_demand_af=Decimal("5.0000"),
        )
        html = _page(parcel, "2026-06")
        assert "No groundwater extraction estimated for June 2026" in html
        assert NO_WELL_SENTENCE in html
        assert reverse("parcels:detail", args=[parcel.pk]) in html
        assert "budget-panel" not in html
        assert "5.00" not in html
        for words in REJECTED:
            assert words not in html, words

    def test_a_metered_month(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-021")
        _well_run(parcel, residual_disposition="metered", gw_extracted_af=None)
        html = _page(parcel, "2026-06")
        assert "No groundwater extraction estimated for June 2026" in html
        assert METERED_SENTENCE.format(month="June 2026") in html
        assert NO_WELL_SENTENCE not in html
        assert "budget-panel" not in html

    def test_a_month_with_no_run_is_still_a_404(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-022")
        resp = _client().get(
            reverse(
                "accounting:calculation_run_detail",
                kwargs={"parcel_id": parcel.pk, "period": "2026-06"},
            )
        )
        assert resp.status_code == 404


class TestTheFieldPageLinks:
    """The field page links only the months that have a receipt."""

    def _period(self):
        return ReportingPeriodFactory(
            start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30)
        )

    def test_only_well_months_without_a_meter_link(self):
        rp = self._period()
        parcel = ParcelFactory(parcel_number="RCPT-APN-030")
        _well_run(parcel, "2026-05")
        _well_run(parcel, "2026-06", residual_disposition="metered", gw_extracted_af=None)
        _well_run(
            parcel, "2026-07",
            residual_disposition="unmet_demand", gw_extracted_af=None,
            unmet_demand_af=Decimal("5.0000"),
        )
        assert parcel_run_periods(parcel, rp) == ["2026-05", "2026-06", "2026-07"]
        assert parcel_receipt_periods(parcel, rp) == ["2026-05"]

        html = _field_page(parcel, rp.pk)
        assert "Estimated groundwater extraction, month by month:" in html
        link = lambda period: reverse(  # noqa: E731
            "accounting:calculation_run_detail", args=[parcel.pk, period]
        )
        assert link("2026-05") in html
        assert link("2026-06") not in html
        assert link("2026-07") not in html

    def test_a_field_with_no_receipt_month_has_no_link_block_and_keeps_its_balance(self):
        rp = self._period()
        parcel = ParcelFactory(parcel_number="RCPT-APN-031")
        _well_run(
            parcel, "2026-05",
            residual_disposition="unmet_demand", gw_extracted_af=None,
            unmet_demand_af=Decimal("5.0000"),
        )
        assert parcel_receipt_periods(parcel, rp) == []
        html = _field_page(parcel, rp.pk)
        assert "Estimated groundwater extraction, month by month:" not in html
        assert "calculation-run" not in html
        # The balance panel is still gated on the wider run_periods.
        assert "Water balance" in html
