# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parcel pane opens on the period that has a calculation, and can be moved.

ISS-147. The pane's period was resolved from the LEDGER — the most recent period
carrying a non-allocation row — so a field whose newer year has a calculation but
no delivery of its own opened on the older year, and there was no control to move
it. The six curtailed Merced fields are exactly that shape: the dry year is the
year with the finding, and it was the year the pane would not show.

The fixture here is that shape, hermetically: one parcel with NO well, a real
surface delivery in the older year, an allocation row (paper, not a supply) in the
newer year, and a ``CalculationRun`` in BOTH years — the newer one recording the
leftover as unmet demand rather than inventing pumping.

⛔ The default is NOT "the most recent period". That would hide the wet year with
no way back, which is ISS-147's own warning. It is the most recent period the
parcel has a calculation for, and ``?period=`` overrides it on every render path.
"""
import datetime as dt
import re
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from tests.factories import ParcelFactory, ParcelLedgerFactory, ReportingPeriodFactory

pytestmark = pytest.mark.django_db


#: The period control's selected option. Digits only, so the status filter's
#: `<option value="active" selected>` on the workspace page is never mistaken
#: for it.
_SELECTED_OPTION = re.compile(r'<option value="(\d+)" selected>([^<]*)</option>')


def selected_period(html):
    """``(pk, name)`` of the period the pane header says it is showing."""
    match = _SELECTED_OPTION.search(html)
    assert match, (
        "the pane header carries no period control with a selected option, so "
        "there is no way to see which period is being shown or to move to "
        "another one (ISS-147)"
    )
    return int(match.group(1)), match.group(2)


def _user():
    import factory
    from django.contrib.auth.hashers import make_password

    class _User(factory.django.DjangoModelFactory):
        class Meta:
            model = "core.User"

        username = factory.Sequence(lambda n: f"perioduser{n}")
        email = factory.Sequence(lambda n: f"perioduser{n}@example.com")
        password = factory.LazyFunction(lambda: make_password("testpass123"))
        is_active = True

    return _User()


@pytest.fixture
def curtailed_field():
    """A no-well field with a calculation in both years, activity only in the older.

    Returns ``(parcel, older_period, newer_period)``.
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
    parcel = ParcelFactory()

    # Older year: a real surface delivery. This is the row the OLD default read.
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=older, source_type="surface_diversion",
        amount_acre_feet=Decimal("-80.0000"),
        transaction_date=dt.date(2025, 1, 15), effective_date=dt.date(2025, 1, 15),
    )
    # Newer year: paper only. An allocation is not a supply (DESIGN.md rule 12),
    # and the old default deliberately excluded it — which is why this year was
    # invisible.
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=newer, source_type="allocation",
        amount_acre_feet=Decimal("100.0000"),
        transaction_date=dt.date(2026, 1, 15), effective_date=dt.date(2026, 1, 15),
    )

    CalculationRun.objects.create(
        parcel=parcel, period="2025-01",
        gross_et_af=Decimal("90.0000"),
        net_consumptive_use_af=Decimal("90.0000"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("10.0000"),
    )
    CalculationRun.objects.create(
        parcel=parcel, period="2026-01",
        gross_et_af=Decimal("363.2600"),
        net_consumptive_use_af=Decimal("363.2600"),
        effective_precip_af=Decimal("0.0000"),
        final_af=Decimal("0.0000"),
        residual_disposition="unmet_demand",
        unmet_demand_af=Decimal("330.3700"),
    )
    return parcel, older, newer


@pytest.fixture
def client_logged_in():
    client = Client()
    client.force_login(_user())
    return client


def test_the_pane_opens_on_the_most_recent_period_with_a_calculation(
    curtailed_field, client_logged_in
):
    """No ``?period=``: the newer year, because that is where the calculation is.

    Under the ledger-activity default this parcel opened on WY 2024-2025, the
    only year with a non-allocation row.
    """
    parcel, older, newer = curtailed_field

    response = client_logged_in.get(
        reverse("parcels:detail", args=[parcel.pk]), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200

    pk, name = selected_period(response.content.decode())
    assert (pk, name) == (newer.pk, "WY 2025-2026"), (
        f"the pane opened on {name!r}; the newer year is the one with a "
        "calculation, and it is the year the curtailment shows in (ISS-147)"
    )


def test_an_explicit_period_argument_opens_the_older_year(
    curtailed_field, client_logged_in
):
    """``?period=`` is honoured, so the wet year is never hidden."""
    parcel, older, newer = curtailed_field

    response = client_logged_in.get(
        reverse("parcels:detail", args=[parcel.pk]) + f"?period={older.pk}",
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200

    pk, name = selected_period(response.content.decode())
    assert (pk, name) == (older.pk, "WY 2024-2025")


def test_an_unknown_period_argument_falls_back_to_the_default(
    curtailed_field, client_logged_in
):
    """A stale bookmark or a hand-typed pk renders the pane, never a 404 or a 500."""
    parcel, older, newer = curtailed_field

    response = client_logged_in.get(
        reverse("parcels:detail", args=[parcel.pk]) + "?period=999999",
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200

    pk, name = selected_period(response.content.decode())
    assert (pk, name) == (newer.pk, "WY 2025-2026")


def test_the_page_and_the_workspace_preload_show_the_same_period_as_the_pane(
    curtailed_field, client_logged_in
):
    """All three render paths resolve the period identically.

    The HTMX fragment, the standalone page and the workspace's ``?selected=``
    preload share ``_parcel_detail_context``; a period resolved in only one of
    them is a pane that changes when you reload it.
    """
    parcel, older, newer = curtailed_field

    page = client_logged_in.get(reverse("parcels:detail", args=[parcel.pk]))
    assert page.status_code == 200
    assert selected_period(page.content.decode()) == (newer.pk, "WY 2025-2026")

    workspace = client_logged_in.get(
        reverse("parcels:list") + f"?selected={parcel.pk}"
    )
    assert workspace.status_code == 200
    assert selected_period(workspace.content.decode()) == (newer.pk, "WY 2025-2026")


def test_an_explicit_period_is_honoured_on_the_workspace_preload(
    curtailed_field, client_logged_in
):
    """A deep link into the workspace carries its period too."""
    parcel, older, newer = curtailed_field

    workspace = client_logged_in.get(
        reverse("parcels:list") + f"?selected={parcel.pk}&period={older.pk}"
    )
    assert workspace.status_code == 200
    assert selected_period(workspace.content.decode()) == (older.pk, "WY 2024-2025")
