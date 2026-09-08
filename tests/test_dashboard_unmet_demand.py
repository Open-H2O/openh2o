# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard lists WHICH fields recorded water use with no supply reported.

ISS-157, surface 2. The engine has always recorded this: where a field has no
well, the leftover after crop use minus rainfall minus canal deliveries is stored
as ``unmet_demand_af`` rather than invented as pumping through a well that does
not exist. Two help pages explain the concept and, since 137-01, the field's own
page shows its figure. Nothing showed a water master the LIST — and the list is
the half a regulator uses, because it names the fields to go and ask about.

**It is a figure, not a finding.** The arithmetic did not close from the supplies
on record, and the platform knows nothing about why: under-irrigation, a delivery
filed against the wrong field, and a surface allocation error all land here
identically. The screen wording is settled (Brent, 2026-09-06) and the tests here
hold it: *water use recorded, no supply reported*, arithmetic and then stop.

Every expected figure is a pasted literal, never a `> 0`.
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client

from accounting.models import CalculationRun
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

PERIOD_START = date(2025, 10, 1)
PERIOD_END = date(2026, 9, 30)
QUIET_START = date(2024, 10, 1)
QUIET_END = date(2025, 9, 30)

# Parcel X's two engine months, hand-added: 180.2000 + 150.1700 = 330.3700 AF of
# use with no supply reported, on 200.0000 + 163.2600 = 363.2600 AF of crop use.
X_UNMET_MONTHS = (Decimal("180.2000"), Decimal("150.1700"))
X_GROSS_MONTHS = (Decimal("200.0000"), Decimal("163.2600"))
X_UNMET_TOTAL = Decimal("330.3700")
X_GROSS_TOTAL = Decimal("363.2600")

SECTION_HEADING = "Fields with water use recorded and no supply reported"
COLUMN_HEADING = "Not met by supplies"  # 142-01: the card title carries the settled phrase
SECTION_ANCHOR = "unmet-demand"
PILL_WORDS = "field with water use recorded, no supply reported"


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"unmetuser{n}")
    email = factory.Sequence(lambda n: f"unmetuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _run(parcel, month, *, disposition, unmet, gross, final=Decimal("0")):
    """One engine month.

    ``final_af`` is the billable magnitude the run wrote to the ledger: zero on a
    field with no well (nothing was booked — that is the whole point of the
    unmet-demand disposition), the resolved pumping on a field that has one.
    """
    return CalculationRun.objects.create(
        parcel=parcel,
        period=month,
        period_start=date(int(month[:4]), int(month[5:]), 1),
        gross_et_af=gross,
        effective_precip_af=Decimal("0"),
        surface_water_af=Decimal("0"),
        net_consumptive_use_af=gross,
        residual_disposition=disposition,
        unmet_demand_af=unmet,
        final_af=final,
    )


@pytest.fixture
def basin():
    """Three fields in one period: one to list, two that must stay off the list."""
    period = ReportingPeriodFactory(
        name="WY 2025-2026", start_date=PERIOD_START, end_date=PERIOD_END
    )
    quiet_period = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=QUIET_START, end_date=QUIET_END
    )
    zone = ZoneFactory(name="ISS-157 Zone")
    gw_type = WaterTypeFactory(name="Groundwater", code="GW")
    AllocationPlanFactory(
        zone=zone,
        water_type=gw_type,
        reporting_period=period,
        allocation_acre_feet=Decimal("1000.0000"),
    )
    AllocationPlanFactory(
        zone=zone,
        water_type=gw_type,
        reporting_period=quiet_period,
        allocation_acre_feet=Decimal("1000.0000"),
    )

    # X — no well, two months of use with no supply reported. The one row.
    parcel_x = ParcelFactory(parcel_number="ISS157-X")
    ParcelZoneFactory(parcel=parcel_x, zone=zone)
    for month, unmet, gross in zip(
        ("2026-05", "2026-06"), X_UNMET_MONTHS, X_GROSS_MONTHS
    ):
        _run(parcel_x, month, disposition="unmet_demand", unmet=unmet, gross=gross)

    # Y — carries the disposition but the amount is zero. 41 of the demonstration's
    # 47 such fields look like this: canal water covered them. Listing a field at
    # 0.00 AF would send a water master to ask about nothing.
    parcel_y = ParcelFactory(parcel_number="ISS157-Y")
    ParcelZoneFactory(parcel=parcel_y, zone=zone)
    _run(
        parcel_y,
        "2026-05",
        disposition="unmet_demand",
        unmet=Decimal("0"),
        gross=Decimal("120.0000"),
    )

    # Z — has a well, so its leftover was resolved as pumping. Never this list.
    parcel_z = ParcelFactory(parcel_number="ISS157-Z")
    ParcelZoneFactory(parcel=parcel_z, zone=zone)
    _run(
        parcel_z,
        "2026-05",
        disposition="groundwater",
        unmet=Decimal("0"),
        gross=Decimal("140.0000"),
        final=Decimal("140.0000"),
    )

    # The quiet period gets one run so the engine has demonstrably RUN there —
    # otherwise the empty state below would be indistinguishable from ISS-099's
    # "nobody has measured this yet", which stands the whole section down.
    _run(
        parcel_z,
        "2025-05",
        disposition="groundwater",
        unmet=Decimal("0"),
        gross=Decimal("95.0000"),
        final=Decimal("95.0000"),
    )

    return {
        "period": period,
        "quiet_period": quiet_period,
        "x": parcel_x,
        "y": parcel_y,
        "z": parcel_z,
    }


@pytest.fixture
def viewer():
    user = UserFactory()
    client = Client()
    client.force_login(user)
    return client


def _section(body):
    """The unmet-demand section's own HTML, sliced off the rest of the page.

    Asserting a parcel number is "absent from the section" against the whole page
    would pass for the wrong reason the moment another table lists every parcel.
    """
    start = body.index(f'id="{SECTION_ANCHOR}"')
    return body[start:]


def test_the_section_lists_the_one_field_with_its_two_figures(basin, viewer):
    resp = viewer.get(f"/accounting/dashboard/?period={basin['period'].pk}")
    assert resp.status_code == 200
    rows = resp.context["unmet_demand_rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["parcel_number"] == "ISS157-X"
    assert row["unmet"] == X_UNMET_TOTAL
    assert row["gross_et"] == X_GROSS_TOTAL
    assert resp.context["unmet_demand_total"] == X_UNMET_TOTAL
    assert resp.context["unmet_demand_count"] == 1

    section = _section(resp.content.decode())
    assert SECTION_HEADING in section
    assert COLUMN_HEADING in section
    assert "ISS157-X" in section
    assert "330.37" in section
    assert "363.26" in section
    # The link carries the period, so the field's own page opens on the year the
    # dashboard was showing (137-01 made `?period=` real on that page).
    assert f'/parcels/{basin["x"].pk}/?period={basin["period"].pk}' in section


def test_a_zero_amount_field_and_a_pumping_field_are_not_listed(basin, viewer):
    resp = viewer.get(f"/accounting/dashboard/?period={basin['period'].pk}")
    section = _section(resp.content.decode())
    assert "ISS157-Y" not in section, (
        "a field whose shortfall is 0.00 AF has nothing for anyone to ask about"
    )
    assert "ISS157-Z" not in section, (
        "a field with a well had its leftover resolved as pumping, not as this"
    )


def test_the_attention_strip_carries_the_count(basin, viewer):
    resp = viewer.get(f"/accounting/dashboard/?period={basin['period'].pk}")
    body = resp.content.decode()
    assert PILL_WORDS in body
    assert f'href="#{SECTION_ANCHOR}"' in body
    # The pill must be counted in, or "All clear" would be a false claim on a
    # period that has six of these.
    assert resp.context["attention_total"] >= 1


def test_a_period_with_no_such_field_says_so_in_one_sentence(basin, viewer):
    quiet = basin["quiet_period"]
    resp = viewer.get(f"/accounting/dashboard/?period={quiet.pk}")
    assert resp.context["unmet_demand_rows"] == []
    assert resp.context["unmet_demand_count"] == 0
    section = _section(resp.content.decode())
    assert (
        f"No field recorded water use without a reported supply in {quiet.name}."
        in section
    )
    assert PILL_WORDS not in resp.content.decode()


def test_the_section_never_uses_a_word_that_alleges_wrongdoing(basin, viewer):
    """⛔ The wording is settled and this is its guard on THIS section.

    The platform records that arithmetic did not close. It does not know why, and
    a regulator reading an accusation into a figure is the failure that cannot be
    walked back.
    """
    resp = viewer.get(f"/accounting/dashboard/?period={basin['period'].pk}")
    section = _section(resp.content.decode()).lower()
    for word in (
        "unauthorized",
        "unpermitted",
        "unlawful",
        "illegal",
        "stolen",
        "flagged",
        "unexplained",
        "suspicious",
    ):
        assert word not in section, f"{word!r} makes a claim this figure cannot support"
