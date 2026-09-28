# SPDX-License-Identifier: AGPL-3.0-or-later
"""148-03 Task 2: the help pages' shared partial and its selection rule.

``accounting.services.example_field_month()`` picks the one real field-month
``templates/help/partials/_the_subtraction.html`` teaches its arithmetic from
(words-help-pages.md A.1, and the coordinator's own tightening: a month still
in progress is never the example, and the preferred remainder is at least
0.01 AF, not merely nonzero). These tests cover the selection order on a
small hand-built fixture, the words-only variant with no qualifying run, and
the two help pages themselves: reachable signed-out on a public demo, and
clear of the two words this rewrite retired ("recharge", "Billable").
"""
import datetime
from decimal import Decimal

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from accounting.models import CalculationRun
from accounting.services import example_field_month
from core.models import SiteConfig
from parcels.models import ParcelLedger
from tests.factories import ParcelFactory

pytestmark = pytest.mark.django_db


def _run(parcel, period, *, disposition="groundwater", delivered=None,
         final=Decimal("0.0000"), efficiency=None, gw_extracted=None,
         over_delivery=Decimal("0.0000"), breakdown=None):
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal("10.0000"),
        effective_precip_af=Decimal("0.0000"),
        surface_delivered_af=delivered,
        surface_efficiency=efficiency,
        surface_water_af=delivered,
        final_af=final,
        gw_extracted_af=gw_extracted,
        over_delivery_af=over_delivery,
        residual_disposition=disposition,
        breakdown=breakdown or [],
    )


def _period_str(d):
    return f"{d.year:04d}-{d.month:02d}"


class TestExampleFieldMonthSelection:
    """A.1's selection rule, on a fixture small enough to check by hand.

    Every period below is 2025-something, which is an ended month relative
    to any date this suite plausibly runs on; the one test that has to sit
    right at "now" (the in-progress-month exclusion) computes its periods
    from ``timezone.localdate()`` instead of a literal.
    """

    def test_prefers_the_most_recent_canal_month_with_a_nonzero_remainder(self):
        parcel_a = ParcelFactory(parcel_number="TEST-APN-A")
        parcel_b = ParcelFactory(parcel_number="TEST-APN-B")
        parcel_c = ParcelFactory(parcel_number="TEST-APN-C")

        # A: older period, would win on recency alone if B/C didn't exist.
        _run(parcel_a, "2025-06", delivered=Decimal("50.0000"), final=Decimal("0.0000"))
        # C: same period as B, alphabetically after B, remainder is 0.00.
        _run(parcel_c, "2025-07", delivered=Decimal("10.0000"), final=Decimal("0.0000"))
        # B: same period as C, alphabetically before it, AND the only run
        # with a nonzero remainder -- the one the rule should pick.
        run_b = _run(parcel_b, "2025-07", delivered=Decimal("120.0000"),
                     final=Decimal("5.0000"), efficiency=Decimal("0.750"))
        # D: most recent period of all, but metered -- never a candidate.
        parcel_d = ParcelFactory(parcel_number="TEST-APN-D")
        _run(parcel_d, "2025-08", disposition="metered",
             delivered=Decimal("30.0000"), final=Decimal("2.0000"))

        result = example_field_month()

        assert result is not None
        assert result["example"] == run_b
        assert result["field_label"] == "TEST-APN-B"
        assert result["month_label"] == "July 2025"

    def test_the_remainder_threshold_is_one_cent_not_merely_nonzero(self):
        # X is the more recent month, but its remainder (0.0050 AF) is the
        # split's rounding noise, below the 0.01 AF preference threshold --
        # it must NOT be preferred over the older, larger remainder in Y.
        parcel_x = ParcelFactory(parcel_number="TEST-APN-X")
        parcel_y = ParcelFactory(parcel_number="TEST-APN-Y")
        _run(parcel_x, "2025-08", delivered=Decimal("30.0000"), final=Decimal("0.0050"))
        run_y = _run(parcel_y, "2025-07", delivered=Decimal("40.0000"), final=Decimal("5.0000"))

        result = example_field_month()

        assert result["example"] == run_y
        assert result["field_label"] == "TEST-APN-Y"

    def test_the_remainder_threshold_includes_exactly_one_cent(self):
        # A run at exactly 0.01 AF qualifies for the preference (>=, not >).
        parcel = ParcelFactory(parcel_number="TEST-APN-EXACTCENT")
        run = _run(parcel, "2025-08", delivered=Decimal("10.0000"), final=Decimal("0.0100"))

        result = example_field_month()

        assert result["example"] == run

    def test_ties_on_period_break_by_parcel_number_ascending(self):
        parcel_z = ParcelFactory(parcel_number="TEST-APN-Z")
        parcel_m = ParcelFactory(parcel_number="TEST-APN-M")
        _run(parcel_z, "2025-07", delivered=Decimal("20.0000"), final=Decimal("1.0000"))
        run_m = _run(parcel_m, "2025-07", delivered=Decimal("20.0000"), final=Decimal("1.0000"))

        result = example_field_month()

        assert result["example"] == run_m
        assert result["field_label"] == "TEST-APN-M"

    def test_falls_back_to_the_most_recent_canal_month_when_none_has_a_remainder(self):
        parcel_older = ParcelFactory(parcel_number="TEST-APN-OLD")
        parcel_newer = ParcelFactory(parcel_number="TEST-APN-NEW")
        _run(parcel_older, "2025-05", delivered=Decimal("40.0000"), final=Decimal("0.0000"))
        run_newer = _run(parcel_newer, "2025-06", delivered=Decimal("60.0000"),
                          final=Decimal("0.0000"))

        result = example_field_month()

        assert result is not None
        assert result["example"] == run_newer
        assert result["field_label"] == "TEST-APN-NEW"

    def test_falls_back_to_any_groundwater_run_with_no_canal_water(self):
        parcel = ParcelFactory(parcel_number="TEST-APN-NOCANAL")
        run = _run(parcel, "2025-04", delivered=None, final=Decimal("3.0000"),
                    gw_extracted=Decimal("3.7500"))

        result = example_field_month()

        assert result is not None
        assert result["example"] == run
        assert result["surface_delivered_af"] is None

    def test_a_month_still_in_progress_is_never_the_example(self):
        # The obviously "better" run (bigger remainder) sits in the current,
        # unfinished month, and must lose to an ended month with a smaller
        # one -- the whole point of the coordinator's `period_start__lt`
        # filter (ISS-221: a live month's figures still move).
        today = timezone.localdate()
        current_month = _period_str(today)
        # One month back, safely ended regardless of what day `today` is.
        ended = today.replace(day=1) - datetime.timedelta(days=1)
        ended_month = _period_str(ended)

        parcel_now = ParcelFactory(parcel_number="TEST-APN-INPROGRESS")
        parcel_ended = ParcelFactory(parcel_number="TEST-APN-ENDED")
        _run(parcel_now, current_month, delivered=Decimal("99.0000"), final=Decimal("9.0000"))
        run_ended = _run(parcel_ended, ended_month, delivered=Decimal("10.0000"),
                          final=Decimal("1.0000"))

        result = example_field_month()

        assert result["example"] == run_ended
        assert result["field_label"] == "TEST-APN-ENDED"

    def test_returns_none_with_no_qualifying_run(self):
        ParcelFactory(parcel_number="TEST-APN-LONE")
        assert example_field_month() is None

    def test_returns_none_when_parcels_disabled(self, monkeypatch):
        parcel = ParcelFactory(parcel_number="TEST-APN-GATED")
        _run(parcel, "2025-06", delivered=Decimal("10.0000"), final=Decimal("1.0000"))

        monkeypatch.setattr(
            "accounting.services.is_enabled",
            lambda name, names=None: name != "parcels",
        )
        assert example_field_month() is None


class TestExampleFieldMonthArithmetic:
    """The context dict's own figures, computed by hand against one run."""

    def test_the_context_dict_matches_the_run_it_was_built_from(self):
        SiteConfig.objects.create(agency_name="Test Agency", demonstration_mode=True)
        parcel = ParcelFactory(parcel_number="TEST-APN-FIGS")
        run = _run(
            parcel, "2025-07",
            delivered=Decimal("123.1800"),
            efficiency=Decimal("0.750"),
            final=Decimal("0.8800"),
            gw_extracted=Decimal("1.1000"),
            breakdown=[{
                "step_type": "subtract_surface_water",
                "input_af": "93.2600",
                "output_af": "0.8800",
                "detail": {
                    "delivered_af": "123.1800",
                    "efficiency": "0.750",
                    "efficiency_source": "agency",
                    "consumed_af": "123.1800",
                    "surface_water_af": "123.1800",
                },
            }],
        )
        run.surface_water_af = Decimal("123.1800")
        run.gross_et_af = Decimal("93.2600")
        run.save()

        result = example_field_month()

        assert result["example"] == run
        assert result["gross_et_af"] == Decimal("93.2600")
        assert result["final_af"] == Decimal("0.8800")
        assert result["irrigation_efficiency_pct"] == Decimal("75.000")
        assert result["irrigation_efficiency_source"] == "agency"
        # final_af / gw_extracted_af = 0.8800 / 1.1000 = 0.8000 exactly.
        assert result["gw_efficiency"] == Decimal("0.8000")
        assert result["gw_efficiency_pct"] == Decimal("80.0000")
        assert result["gw_efficiency_is_live_setting"] is False
        # No ParcelLedger row at all for this parcel-month, so delivery_split
        # defaults to "by_use" (words-help-pages.md A.2: "otherwise 'by_use'").
        assert result["delivery_split"] == "by_use"
        assert result["demonstration"] is True

    def test_delivery_split_reads_fixed_share_off_the_ledger_row(self):
        from accounting.ledger_words import DELIVERY_SHARE_BY_FIXED

        parcel = ParcelFactory(parcel_number="TEST-APN-FIXEDSHARE")
        run = _run(
            parcel, "2025-07",
            delivered=Decimal("50.0000"),
            efficiency=Decimal("0.750"),
            final=Decimal("2.0000"),
            gw_extracted=Decimal("2.5000"),
        )
        ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=datetime.date(2025, 7, 15),
            effective_date=datetime.date(2025, 7, 15),
            amount_acre_feet=Decimal("-50.0000"),
            source_type="surface_diversion",
            description=f"Share of 50.00 AF delivered from Test POD: 20%, "
                        f"{DELIVERY_SHARE_BY_FIXED}, because no use area it "
                        f"serves has an estimated use for the month",
        )

        result = example_field_month()

        assert result["example"] == run
        assert result["delivery_split"] == "fixed_share"


class TestSubtractionPartialWordsOnlyVariant:
    """A.4: no qualifying run renders the words-only shape, never a table."""

    def test_renders_the_words_only_variant_with_no_example(self):
        html = render_to_string(
            "help/partials/_the_subtraction.html", {"example": None}
        )
        assert "arithmetic in words" in html
        assert "<table" not in html
        assert "Groundwater extracted" not in html


class TestHelpPagesPublicAndClean:
    """Both pages 200 for a signed-out reader on a public demo, and clear of
    the two words 148-03 retired from them."""

    @override_settings(ACCESS_CONTROL_ENFORCED=False)
    def test_both_pages_200_for_an_anonymous_reader_on_the_open_demo(self):
        client = Client()
        for name in ("water_balances", "methods"):
            response = client.get(reverse(name))
            assert response.status_code == 200, (
                f"{name} returned {response.status_code} for a signed-out "
                f"reader on the open demo"
            )

    @override_settings(ACCESS_CONTROL_ENFORCED=False)
    def test_neither_page_says_recharge_or_billable(self):
        # Scoped to <main>: the sidebar nav (shared chrome on every page)
        # carries a literal "/recharge/" route link, which is not page prose
        # and is not what this check is about.
        client = Client()
        for name in ("water_balances", "methods"):
            content = client.get(reverse(name)).content.decode()
            main_start = content.index('id="main-content"')
            main = content[main_start:]
            assert "recharge" not in main.lower(), f"{name} still says 'recharge'"
            assert "Billable" not in main, f"{name} still says 'Billable'"
