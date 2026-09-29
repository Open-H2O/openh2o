# SPDX-License-Identifier: AGPL-3.0-or-later
"""148-04 Task 3: the calculation page names what happened to canal water
beyond what the crop could use, and the field page shows (c)'s line.

Every ``CalculationRun`` here is built directly with the ORM, never by
running the engine — the sentence and the figures are read off the run's OWN
stamped columns, so a fixture that sets those columns by hand is the whole
test. Hand numbers, carried from the 148-04 plan and
``tests/test_over_delivery_treatment.py`` (ET 10.0000, over 4.0000, share
0.100 -> 3.6000 credited, 0.4000 left in the basin), so a reader can check
the arithmetic without re-deriving it.

Runs in the web container (needs the DB).
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from core.models import SiteConfig
from tests.factories import ParcelFactory

User = get_user_model()

pytestmark = pytest.mark.django_db

# 148-03: the calculation page's result row prints the short form on its
# cell label (a tight label, per DESIGN.md rule 12's row); the field page's own
# line keeps the short form too.
CARD_LABEL = "Canal water beyond crop use"
FIELD_LABEL = "Canal water beyond crop use:"

OVER = Decimal("4.0000")
SHARE = Decimal("0.100")
CREDITED = Decimal("3.6000")
LEFT = Decimal("0.4000")

# The four sentences are literal template text (composed with floatformat
# in the template, not a pre-built Python string), so Django's autoescape
# never touches them; the apostrophes render plain.
NOT_CREDITED_SENTENCE = "Recorded here and not credited to anyone."
CREDITED_FIELD_SENTENCE = (
    "3.6000 AF is credited to this field; 0.4000 AF (10%) stays in the basin."
)
CREDITED_POOL_SENTENCE = (
    "3.6000 AF is credited to the zone's shared account, because this "
    "field has no well to pump it back; 0.4000 AF (10%) stays in the basin."
)
NAMED_LINE_SENTENCE = (
    "Shown on the field's page as its own line. Not a credit and not charged."
)


def _user(name="r148-04-reader"):
    return User.objects.create_user(
        username=name, email=f"{name}@example.com", password="x", is_active=True,
    )


def _client():
    client = Client()
    client.force_login(_user())
    return client


def _run(
    parcel,
    period,
    *,
    over_delivery_af=OVER,
    treatment="not_credited",
    credited_af=None,
    leave_behind=None,
    pooled=False,
):
    return CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=Decimal("10.0000"),
        net_consumptive_use_af=Decimal("10.0000"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("10.0000"),
        over_delivery_af=over_delivery_af,
        over_delivery_treatment=treatment,
        over_delivery_leave_behind=leave_behind,
        over_delivery_credited_af=credited_af,
        over_delivery_credit_pooled=pooled,
    )


def _calc_page(parcel, period):
    resp = _client().get(
        reverse(
            "accounting:calculation_run_detail",
            kwargs={"parcel_id": parcel.pk, "period": period},
        )
    )
    assert resp.status_code == 200
    return resp.content.decode()


def _field_page(parcel):
    resp = _client().get(
        reverse("parcels:detail", args=[parcel.pk]), HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    return resp.content.decode()


class TestCalculationPageSentenceByStamp:
    """One of the plan's four sentences, chosen by the run's own stamp."""

    def test_not_credited(self):
        parcel = ParcelFactory(parcel_number="R148-04-A")
        _run(parcel, "2026-08", treatment="not_credited")
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL in html
        assert NOT_CREDITED_SENTENCE in html
        assert "4.0000" in html

    def test_credited_to_the_field(self):
        parcel = ParcelFactory(parcel_number="R148-04-B")
        _run(
            parcel, "2026-08", treatment="credited",
            credited_af=CREDITED, leave_behind=SHARE, pooled=False,
        )
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL in html
        assert CREDITED_FIELD_SENTENCE in html

    def test_credited_to_the_pool(self):
        parcel = ParcelFactory(parcel_number="R148-04-C")
        _run(
            parcel, "2026-08", treatment="credited",
            credited_af=CREDITED, leave_behind=SHARE, pooled=True,
        )
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL in html
        assert CREDITED_POOL_SENTENCE in html

    def test_named_line(self):
        parcel = ParcelFactory(parcel_number="R148-04-D")
        _run(parcel, "2026-08", treatment="named_line")
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL in html
        assert NAMED_LINE_SENTENCE in html

    def test_credited_with_nothing_actually_credited_reads_as_not_credited(self):
        """A no-well field with no zone to hold its share: `treatment` stamps
        "credited" but `over_delivery_credited_af` stays None (148-04 Task 2's
        `_over_delivery_decision`, the "no zone to hold it" branch). Not one of
        the plan's four named sentences; it must read the same as
        not_credited honestly does, never crash and never claim a credit that
        was not made."""
        parcel = ParcelFactory(parcel_number="R148-04-K")
        _run(
            parcel, "2026-08", treatment="credited",
            credited_af=None, leave_behind=SHARE, pooled=False,
        )
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL in html
        assert NOT_CREDITED_SENTENCE in html
        assert CREDITED_FIELD_SENTENCE not in html
        assert CREDITED_POOL_SENTENCE not in html

    def test_zero_over_delivery_renders_no_card(self):
        parcel = ParcelFactory(parcel_number="R148-04-E")
        _run(parcel, "2026-08", over_delivery_af=Decimal("0.0000"), treatment="credited")
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL not in html


class TestSentenceIsTheRunsOwnStamp:
    """ISS-177: the live setting is read never; only what THIS run stamped."""

    def test_changing_the_live_setting_after_the_run_does_not_move_the_sentence(self):
        parcel = ParcelFactory(parcel_number="R148-04-F")
        _run(parcel, "2026-08", treatment="not_credited")

        config, _ = SiteConfig.objects.get_or_create(
            defaults={"agency_name": "148-04 Test Agency"}
        )
        config.over_delivery_treatment = "credited"
        config.over_delivery_leave_behind = SHARE
        config.save()

        html = _calc_page(parcel, "2026-08")
        assert NOT_CREDITED_SENTENCE in html
        assert CREDITED_FIELD_SENTENCE not in html
        assert CREDITED_POOL_SENTENCE not in html


class TestFieldPageLine:
    """(c)'s line: only a named_line run contributes, and it sums."""

    def test_appears_only_for_named_line_and_sums_the_shown_amount(self):
        parcel = ParcelFactory(parcel_number="R148-04-G")
        _run(
            parcel, "2026-01", over_delivery_af=Decimal("4.0000"),
            treatment="named_line",
        )
        _run(
            parcel, "2026-02", over_delivery_af=Decimal("1.5000"),
            treatment="named_line",
        )
        # Credited elsewhere the same month range; must not be counted here.
        _run(
            parcel, "2026-03", over_delivery_af=Decimal("2.0000"),
            treatment="credited", credited_af=Decimal("1.8000"),
            leave_behind=SHARE, pooled=False,
        )

        html = _field_page(parcel)
        assert FIELD_LABEL in html
        assert "5.50" in html, "4.0000 + 1.5000 named_line AF, the credited run excluded"
        assert "AF, not a credit and not charged" in html

    def test_absent_for_a_field_with_no_named_line_run(self):
        parcel = ParcelFactory(parcel_number="R148-04-H")
        _run(
            parcel, "2026-01", over_delivery_af=Decimal("4.0000"),
            treatment="credited", credited_af=Decimal("3.6000"),
            leave_behind=SHARE, pooled=False,
        )

        html = _field_page(parcel)
        assert FIELD_LABEL not in html


class TestNoRecharge:
    """148-04: the new content on either page never names recharge.

    Every page in this deployment carries the sidebar nav, which links to
    "/recharge/" whenever that module is enabled — unrelated to Task 3 and
    out of scope to fix here — so both checks are scoped to the new card or
    line and its own explainer, not the whole page. The field page's
    PRE-EXISTING mass-balance panel also says "recharge" in its own prose (a
    Uses breakdown row and the "How this balance is built" popout), a
    second, independent reason its check must be scoped rather than
    whole-page.
    """

    def test_calculation_pages_new_card_says_nothing_about_recharge(self):
        parcel = ParcelFactory(parcel_number="R148-04-I")
        _run(
            parcel, "2026-08", treatment="credited",
            credited_af=CREDITED, leave_behind=SHARE, pooled=True,
        )
        html = _calc_page(parcel, "2026-08")
        assert CARD_LABEL in html
        start = html.index(CARD_LABEL)
        end = html.index("</p>", start)
        segment = html[start:end]
        assert "recharge" not in segment.lower()

    def test_field_pages_new_line_says_nothing_about_recharge(self):
        parcel = ParcelFactory(parcel_number="R148-04-J")
        _run(parcel, "2026-01", over_delivery_af=Decimal("4.0000"), treatment="named_line")
        html = _field_page(parcel)
        assert FIELD_LABEL in html
        start = html.index(FIELD_LABEL)
        end = html.index("</p>", start)
        segment = html[start:end]
        assert "recharge" not in segment.lower()
