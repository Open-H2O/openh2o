# SPDX-License-Identifier: AGPL-3.0-or-later
"""The use-area pane's ledger card answers for the period the balance answers for.

ISS-165 / R-107. ``_parcel_detail_context`` resolved a ``balance_period`` with
four ordered fallbacks and then built ``recent_ledger`` with no period filter at
all, so the water balance and the "Recent ledger entries" card beside it — two
surfaces on one screen, a hand's width apart — answered for different years and
neither said which.

Measured on the demonstration data 2026-09-08, before the fix: the balance stood
at WY 2025-2026 while nine of the card's ten rows were dated October 2024 to
June 2025.

⚠ This is the test the issue asked for by name. The fix itself is one filter on
one queryset, which is exactly the shape of change that goes green forever and
then silently regresses when someone reorders the context builder: the card
would go back to listing the whole history and nothing else in the suite reads
its dates.

Every assertion below carries a literal from the fixture rather than recomputing
the query it is checking.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from parcels.views import _parcel_detail_context
from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

pytestmark = pytest.mark.django_db


def _user():
    import factory
    from django.contrib.auth.hashers import make_password

    class _User(factory.django.DjangoModelFactory):
        class Meta:
            model = "core.User"

        username = factory.Sequence(lambda n: f"ledgeruser{n}")
        email = factory.Sequence(lambda n: f"ledgeruser{n}@example.com")
        password = factory.LazyFunction(lambda: make_password("testpass123"))
        is_active = True

    return _User()


@pytest.fixture
def field_with_two_years():
    """One use area, three periods: two carrying entries and one carrying none.

    Returns ``(parcel, older, newer, empty)``. The shape mirrors the live
    demonstration data, where the newer year holds only its opening allocation
    and the older year holds the deliveries.
    """
    older = ReportingPeriodFactory(
        name="WY 2024-2025",
        start_date=dt.date(2024, 10, 1),
        end_date=dt.date(2025, 9, 30),
    )
    newer = ReportingPeriodFactory(
        name="WY 2025-2026",
        start_date=dt.date(2025, 10, 1),
        end_date=dt.date(2026, 9, 30),
    )
    empty = ReportingPeriodFactory(
        name="WY 2026-2027",
        start_date=dt.date(2026, 10, 1),
        end_date=dt.date(2027, 9, 30),
    )
    parcel = ParcelFactory()

    # Older year: an opening allocation and two deliveries. Deliveries are
    # stored negative -- the ledger's sign rule is a check constraint.
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=older, source_type="allocation",
        amount_acre_feet=Decimal("241.5600"),
        transaction_date=dt.date(2024, 10, 1), effective_date=dt.date(2024, 10, 1),
    )
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=older, source_type="surface_diversion",
        amount_acre_feet=Decimal("-26.2237"),
        transaction_date=dt.date(2024, 10, 15), effective_date=dt.date(2024, 10, 15),
    )
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=older, source_type="surface_diversion",
        amount_acre_feet=Decimal("-36.5502"),
        transaction_date=dt.date(2025, 6, 15), effective_date=dt.date(2025, 6, 15),
    )
    # Newer year: the opening allocation only.
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=newer, source_type="allocation",
        amount_acre_feet=Decimal("241.5600"),
        transaction_date=dt.date(2025, 10, 1), effective_date=dt.date(2025, 10, 1),
    )
    return parcel, older, newer, empty


def test_the_ledger_card_is_bounded_by_the_selected_period(field_with_two_years):
    """The newer year shows its one row, not the older year's three as well."""
    parcel, older, newer, _empty = field_with_two_years

    context = _parcel_detail_context(parcel, period_id=str(newer.pk))

    assert context["balance_period"] == newer
    dates = [entry.effective_date for entry in context["recent_ledger"]]
    assert dates == [dt.date(2025, 10, 1)], (
        "the ledger card is not bounded by the selected period, so it lists "
        f"{len(dates)} rows for a year that holds one (ISS-165): {dates}"
    )
    assert all(
        newer.start_date <= d <= newer.end_date for d in dates
    ), f"a row falls outside {newer.name} ({newer.start_date}..{newer.end_date}): {dates}"


def test_the_older_year_shows_its_own_three_rows(field_with_two_years):
    """The bound is a filter, not a cap: the year with entries still shows them."""
    parcel, older, _newer, _empty = field_with_two_years

    context = _parcel_detail_context(parcel, period_id=str(older.pk))

    assert context["balance_period"] == older
    dates = [entry.effective_date for entry in context["recent_ledger"]]
    assert dates == [
        dt.date(2025, 6, 15),
        dt.date(2024, 10, 15),
        dt.date(2024, 10, 1),
    ], f"expected {older.name}'s three rows newest-first, got {dates}"


def test_a_period_with_no_entries_shows_an_empty_card(field_with_two_years):
    """Empty, and empty is the truth -- not the previous year's rows."""
    parcel, _older, _newer, empty = field_with_two_years

    context = _parcel_detail_context(parcel, period_id=str(empty.pk))

    assert context["balance_period"] == empty
    assert list(context["recent_ledger"]) == [], (
        "a period with no ledger entries showed rows anyway, which is the "
        "whole of ISS-165: the card was answering for a different year"
    )


def test_the_card_states_the_period_it_is_showing(field_with_two_years):
    """R-107: the two surfaces can be SEEN to agree, not merely agree today."""
    parcel, _older, newer, _empty = field_with_two_years
    client = Client()
    client.force_login(_user())

    response = client.get(
        reverse("parcels:detail", args=[parcel.pk]),
        {"period": str(newer.pk)},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    html = response.content.decode()

    marker = "Recent ledger entries"
    assert marker in html
    subtitle_region = html[html.index(marker) : html.index(marker) + 1200]
    assert newer.name in subtitle_region, (
        "the ledger card does not name the period it is showing, so a reader "
        "cannot see that it agrees with the balance beside it (R-107)"
    )


def test_the_amount_column_says_what_a_negative_means(field_with_two_years):
    """R-108: 241.56 beside -36.55 with nothing saying which direction is which.

    143-05's second checkpoint (2026-09-12) shortened the sentence to two
    facts at 14px; the wording is carried VERBATIM from the Use Ledger's own
    facts line (``_ledger_list_results.html``, ``.ledger-card-head``) rather
    than reworded here -- one quantity, one wording, on every screen that
    shows it (DESIGN.md copy rule 12). The old 30-word sentence must be gone
    from this page too, not just shortened elsewhere.
    """
    parcel, older, _newer, _empty = field_with_two_years
    client = Client()
    client.force_login(_user())

    response = client.get(
        reverse("parcels:detail", args=[parcel.pk]),
        {"period": str(older.pk)},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()

    assert (
        "Negative amounts are water delivered or pumped; positive amounts "
        "are credits." in html
    ), "the ledger card prints negative amounts with nothing saying what they are (R-108)"
    assert (
        "Water leaving a canal or a well is stored as a negative entry." not in html
    ), "the old 30-word sentence should be gone, not merely duplicated (143-05)"
