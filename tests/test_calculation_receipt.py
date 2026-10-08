# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calculation page as a receipt (148-03, design approved 2026-09-28).

The page answers one question, where this field's estimated pumping for the
month came from, and only a month on a field with a well and no meter reading
has that question. These tests build every ``CalculationRun`` directly with
the ORM and type the expected figures in by hand (10.0000 less 1.0000 less
4.0000 is 5.0000; 5.0000 divided by 0.8 is 6.2500), so a page-level
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

HEADLINE = "Estimated pumping, June 2026:"
LEAD = "This field's well has no meter, so the pumping is worked out from what the crop used."
METER_LINE = "With a meter on this well, its reading would replace the estimate."
LINES = (
    "Water the crop used (satellite estimate)",
    "minus rain the crop could use",
    "minus canal water the crop could use",
    "= well water the crop used",
    "divided by 80%, because a pump lifts more than the crop uses",
    "= pumped, charged to the groundwater budget",
)
#: Words the owner rejected on this page, 2026-09-28, never to return.
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
    "no supply on record",
    "Canal water the crop did not need",
)
NO_WELL_SENTENCE = "This field has no well on record, so there is no pumping to estimate."
METERED_SENTENCE = (
    "This field's well has a meter, so the pumping is the meter's reading and "
    "nothing is estimated."
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
        "label": "Subtract canal water the crop could use",
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
    5.3333 delivery times 0.75), well water 5.0000, pumped 6.2500 at 80%."""
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
        gw_extracted_af=Decimal("6.2500"),
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
    def test_answer_first_then_the_subtraction_in_hand_figures(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-001", area_acres=Decimal("12.00"))
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        assert HEADLINE in html
        assert LEAD in html
        # The headline figure, the pumped line, and the answer before the
        # table: the headline sits above the first line of the subtraction.
        assert html.index(HEADLINE) < html.index(LINES[0])
        for line in LINES:
            assert line in html, line
        for figure in ("10.00", "1.00", "4.00", "5.00", "6.25"):
            assert f">{figure}<" in html, figure
        # Two decimals on the receipt; the run's own four-decimal value rides
        # in the title attribute.
        assert 'title="6.2500 acre-feet"' in html
        assert 'title="5.0000 acre-feet"' in html
        assert METER_LINE in html
        assert "Methodology:" in html
        assert "Default Methodology" in html
        assert "12.00 acres" in html

    def test_the_notes_say_where_each_figure_comes_from(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-002")
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        assert "A satellite estimate for this field, this month." in html
        assert (
            "Weather data for the area, then the share the crop could use by the "
            "method set on Methodology Settings."
        ) in html
        assert "The district's delivery record, <span" in html
        assert ">5.33</span> acre-feet" in html
        assert "Times the field's irrigation efficiency, 75% (the deployment's default on Delivery Settings)." in html
        # 149.1-05: the notes are the table's third column; the setting is
        # named with its page and its live label (Delivery Settings).
        assert (
            "Share of pumped groundwater the crop consumes, 80%, on Delivery "
            "Settings; stamped on this month when it was calculated."
        ) in html
        assert "Where it comes from" in html
        assert "With a meter on this well, its reading would replace the estimate." in html
        # A field's own delivery (no split sentence on the ledger row) says
        # nothing about a split.
        assert "divided up from the canal total" not in html

    def test_a_delivery_divided_up_by_crop_water_use_says_so_in_the_ruled_words(self):
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
        assert (
            "divided up from the canal total in proportion to each field's crop "
            "water use after rain. Times the field's irrigation efficiency, 75%"
        ) in html

    def test_the_rejected_words_are_gone(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-004")
        _well_run(parcel)
        html = _page(parcel, "2026-06")
        for words in REJECTED:
            assert words not in html, words
        # "measured" is never said of a satellite or weather estimate.
        assert "measured" not in html.lower()

    def test_the_percentages_are_the_runs_own_and_not_the_live_setting(self):
        """ISS-177's rule: the 80% is read back off final_af / gw_extracted_af,
        the 75% off the run's stamped efficiency, so a change to Delivery
        Settings after the run moves nothing the page says."""
        parcel = ParcelFactory(parcel_number="RCPT-APN-005")
        _well_run(
            parcel,
            surface_efficiency=Decimal("0.900"),
            final_af=Decimal("7.0000"),
            gw_extracted_af=Decimal("10.0000"),
        )
        config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Receipt Test Agency"})
        config.groundwater_efficiency = Decimal("0.500")
        config.default_irrigation_efficiency = Decimal("0.600")
        config.save()
        html = _page(parcel, "2026-06")
        assert "divided by 70%, because a pump lifts more than the crop uses" in html
        assert "irrigation efficiency, 90%" in html
        assert "divided by 50%" not in html
        assert "Share of pumped groundwater the crop consumes, 70%, on Delivery Settings" in html

    def test_a_run_from_before_pumping_was_stamped_stops_at_the_well_water(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-006")
        _well_run(parcel, gw_extracted_af=None)
        html = _page(parcel, "2026-06")
        assert "Estimated well water, June 2026:" in html
        assert "divided by" not in html
        assert "= pumped" not in html
        assert "= well water the crop used" in html


class TestAZeroMonth:
    """A well month where rain and canal water covered the crop."""

    def test_says_so_in_the_months_own_numbers(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-010")
        _zero_run(parcel)
        html = _page(parcel, "2025-12")
        assert "Estimated pumping, December 2025:" in html
        assert ">0.00 acre-feet</span>" in html
        assert (
            "Rain and canal water covered the crop this month, so nothing was pumped."
        ) in html
        # 149.1-05: the figure is a row of the table, its figure beside its name.
        assert "Canal water beyond what the crop could use" in html
        assert 'title="4.0000 acre-feet">4.00</td>' in html
        assert "More than the crop needed this month." in html
        # Nothing to divide, so no division line and no 80% note.
        assert "divided by" not in html
        assert "= pumped" not in html
        # The default treatment (not credited) says nothing more.
        assert "credited" not in html
        assert "its own line" not in html
        assert METER_LINE in html

    def test_names_only_the_water_that_covered_the_crop(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-011")
        _zero_run(
            parcel, "2025-11",
            effective_precip_af=Decimal("0.0000"),
            surface_water_af=Decimal("8.0000"),
            over_delivery_af=Decimal("0.0000"),
        )
        html = _page(parcel, "2025-11")
        assert "Canal water covered the crop this month, so nothing was pumped." in html
        assert "more than the crop needed" not in html
        _zero_run(
            parcel, "2025-10",
            surface_water_af=Decimal("0.0000"),
            surface_delivered_af=Decimal("0.0000"),
            over_delivery_af=Decimal("0.0000"),
        )
        html = _page(parcel, "2025-10")
        assert "Rain covered the crop this month, so nothing was pumped." in html
        assert "No canal delivery on record for this field this month." in html

    def test_under_the_credited_setting_one_sentence_says_what_happened(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-012")
        _zero_run(
            parcel,
            over_delivery_treatment="credited",
            over_delivery_leave_behind=Decimal("0.100"),
            over_delivery_credited_af=Decimal("3.6000"),
        )
        html = _page(parcel, "2025-12")
        assert (
            "3.60 acre-feet of it is credited to this field; 0.40 acre-feet (10%) "
            "stays in the basin."
        ) in html

    def test_under_the_named_line_setting_one_sentence_says_where_it_shows(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-013")
        _zero_run(parcel, over_delivery_treatment="named_line")
        html = _page(parcel, "2025-12")
        assert (
            "It is shown on the field's page as its own line, not a credit and "
            "not charged."
        ) in html

    def test_the_sentence_is_the_runs_own_stamp_not_the_live_setting(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-014")
        _zero_run(parcel, over_delivery_treatment="not_credited")
        config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Receipt Test Agency"})
        config.over_delivery_treatment = "credited"
        config.over_delivery_leave_behind = Decimal("0.100")
        config.save()
        html = _page(parcel, "2025-12")
        assert "credited" not in html


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
        assert "No estimated pumping for June 2026" in html
        assert NO_WELL_SENTENCE in html
        assert reverse("parcels:detail", args=[parcel.pk]) in html
        assert "Estimated pumping," not in html
        assert "5.00" not in html
        for words in REJECTED:
            assert words not in html, words

    def test_a_metered_month(self):
        parcel = ParcelFactory(parcel_number="RCPT-APN-021")
        _well_run(parcel, residual_disposition="metered", gw_extracted_af=None)
        html = _page(parcel, "2026-06")
        assert "No estimated pumping for June 2026" in html
        assert METERED_SENTENCE in html
        assert NO_WELL_SENTENCE not in html
        assert "Estimated pumping," not in html
        assert "= well water" not in html

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
        assert "Estimated pumping, month by month:" in html
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
        assert "Estimated pumping, month by month:" not in html
        assert "calculation-run" not in html
        # The balance panel is still gated on the wider run_periods.
        assert "Water balance" in html
