# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's groundwater budget is spent by groundwater use (136-01, ISS-151).

Three value-asserting tests, written RED against the gross-ET basis before the
view changed, in the shape DESIGN.md rule 12's three review questions demand:
every expected number is a literal worked out by hand from the fixture and
written beside its arithmetic, never ``> 0`` and never the view's own formula.

**The basis (option A, Brent 2026-09-05).** Remaining = groundwater allocation
minus groundwater use, where groundwater use is the metered or calculated
pumping the dashboard already shows in its Groundwater column. Until 136-01 the
column subtracted gross crop water use, a quantity that FALLS in a drought
(ISS-151), so no basin could go over budget because of one.

**Like with like.** An account's allocation counts groundwater plans only. Six
of the eleven demonstration accounts sit in a surface-water service area as
well as a groundwater agency's zone, and the old column added the two
allocations: MER-ACCT-001 showed 2,901.42 AF of groundwater allocation plus
16,200.00 AF of surface entitlement as one number. Subtracting groundwater use
from that sum would have printed a surface entitlement as spare groundwater.
A zone with no groundwater plan shows a dash in its three budget cells.

The fixture extends the one ``tests/test_dashboard_golden.py`` builds (one
period, one zone, one parcel, one account, a 100.0000 AF plan) rather than
inventing a second.
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention: every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"basis{n}")
    email = factory.Sequence(lambda n: f"basis{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _basin(pumped="37.5000", gross_et="80.0000", net="60.0000", with_run=True):
    """One GSA zone with a 100.0000 AF groundwater plan, one parcel, one account.

    The parcel carries one meter reading of ``pumped`` AF (stored negative, the
    ledger's convention for water leaving its source) and one calculation run
    with the given gross and net crop water use, all inside WY 2025-2026.
    ``with_run=False`` leaves the engine output out, the ISS-099 state.
    """
    period = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )
    groundwater = WaterTypeFactory(name="Groundwater", code="GW")
    zone = ZoneFactory(name="Basis GSA Zone", zone_type="management_area")
    parcel = ParcelFactory()
    ParcelZoneFactory(parcel=parcel, zone=zone)
    account = WaterAccountFactory(account_number="BASIS-0001", name="Basis Account")
    WaterAccountParcelFactory(water_account=account, parcel=parcel)
    AllocationPlanFactory(
        zone=zone,
        water_type=groundwater,
        reporting_period=period,
        allocation_acre_feet=Decimal("100.0000"),
    )
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=period, source_type="meter_reading",
        water_type=groundwater, amount_acre_feet=-Decimal(pumped),
        transaction_date=date(2026, 1, 15), effective_date=date(2026, 1, 15),
    )
    if with_run:
        CalculationRun.objects.create(
            parcel=parcel, period="2026-01",
            gross_et_af=Decimal(gross_et),
            net_consumptive_use_af=Decimal(net),
            effective_precip_af=Decimal("0.0000"),
            final_af=Decimal(net),
        )
    return period, zone, parcel, account


def _dashboard(period):
    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard") + f"?period={period.pk}")
    assert response.status_code == 200
    return response


def _account_row(response, account):
    return next(r for r in response.context["account_summaries"] if r["account"] == account)


def _zone_row(response, zone):
    return next(r for r in response.context["zone_summaries"] if r["zone"] == zone)


def test_remaining_is_allocation_minus_groundwater_use():
    """100.0000 allocated, 37.5000 pumped, 80.0000 of gross ET.

    Remaining = 100.0000 - 37.5000 = 62.5000 on both tables. The old basis read
    100.0000 - 80.0000 = 20.0000, which is what this test was red against.
    """
    period, zone, _parcel, account = _basin()

    response = _dashboard(period)

    assert _account_row(response, account)["remaining"] == Decimal("62.5000")
    assert _zone_row(response, zone)["remaining"] == Decimal("62.5000")


def test_account_allocation_counts_groundwater_plans_only():
    """The same parcel also sits in a surface service area with a 1,000.0000 AF
    surface plan. The account's allocation is the groundwater plan alone,
    100.0000 (the old basis read 100.0000 + 1,000.0000 = 1,100.0000), and the
    surface zone's three budget cells are absent, not zero."""
    period, _gsa, parcel, account = _basin()
    surface = WaterTypeFactory(name="Surface Water", code="SW")
    service_area = ZoneFactory(name="Basis Surface Service Area", zone_type="custom")
    ParcelZoneFactory(parcel=parcel, zone=service_area)
    AllocationPlanFactory(
        zone=service_area,
        water_type=surface,
        reporting_period=period,
        allocation_acre_feet=Decimal("1000.0000"),
    )

    response = _dashboard(period)

    assert _account_row(response, account)["allocation"] == Decimal("100.0000")
    surface_row = _zone_row(response, service_area)
    assert surface_row["allocation"] is None
    assert surface_row["carryover"] is None
    assert surface_row["remaining"] is None


def test_the_strip_counts_groundwater_overdrafts():
    """Pumping raised to 120.0000 against the 100.0000 plan: remaining is
    100.0000 - 120.0000 = -20.0000, so exactly one account is over its
    groundwater budget and the strip says so. Gross ET stays at 80.0000, so the
    old basis (100.0000 - 80.0000 = 20.0000) counted zero, which is what this
    test was red against."""
    period, _zone, _parcel, account = _basin(pumped="120.0000")

    response = _dashboard(period)
    html = response.content.decode()

    assert _account_row(response, account)["remaining"] == Decimal("-20.0000")
    assert response.context["accounts_over_budget"] == 1
    assert "account over groundwater budget" in html


def test_the_budget_columns_say_groundwater():
    """The words beside the numbers: both tables head their budget columns under
    one group label, "Groundwater budget" (136-01, DESIGN.md rule 12; the
    group header replaced the per-column "GW allocation (AF)" in 142-01)."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert html.count("Groundwater budget") == 2
    assert "GW allocation (AF)" not in html
    assert "GW remaining (AF)" not in html
    assert "Allocation minus estimated consumptive use" not in html


def test_zone_names_link_to_the_zone_page():
    """ISS-163 (141-01): a zone's name in the Zones table is the same kind of
    link as an account's number in the Accounts table above it -- an anchor
    classed ``data-table-link`` whose href is that zone's own page. The exact
    anchor is asserted, not "some href exists"."""
    period, zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    href = reverse("geography:zone_detail", args=[zone.pk])
    assert f'<a href="{href}" class="data-table-link">{zone.name}</a>' in html


# ---------------------------------------------------------------------------
# Phase 142, plan 01: the panel says what its figures are (R-003, R-004, R-005,
# R-006). Every expected figure below is a literal worked out by hand from
# ``_basin``: one meter reading of 37.5000 AF pumped, no surface delivery, no
# effective rain, so supplies are 0.00 + 37.50 + 0.00 = 37.50; gross crop water
# use 80.00; balance 37.50 - 80.00 = -42.50; one active account.
# ---------------------------------------------------------------------------

def test_the_panel_is_named_for_the_district_balance():
    """R-003: 'Supply vs. use' named an operation; the panel is now named for
    the thing it summarises."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert "District water balance" in html
    assert "Supply vs. use" not in html


def test_the_result_segment_is_marked_as_the_lead():
    """R-004: Balance is the only lead figure. The class is what the stylesheet
    keys the larger size on, and there is exactly one of it."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert html.count('class="budget-seg budget-seg--result"') == 1


def test_the_breakdown_says_of_which():
    """R-005: the three supply parts are titled as parts of the Supplies figure
    ("by source": Brent at the checkpoint asked what "of which" meant),
    and carry the fixture's figures: surface 0.00, groundwater 37.50, rain 0.00."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert "Supplies by source" in html
    assert "<span>Surface</span><b>0.00</b>" in html
    assert "<span>Groundwater</span><b>37.50</b>" in html
    assert "<span>Rain</span><b>0.00</b>" in html


def test_the_panel_names_its_population():
    """The totals are the sum of ACTIVE ACCOUNTS ONLY (views.py), not the basin,
    and the panel says so with the count as a literal."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert "Totals across the 1 active water account below." in html


def test_the_inset_explainer_is_gone():
    """R-006: the 'How this summary works' inset stated the relation the table
    did not show. The captions and the group headers now carry it."""
    period, _zone, _parcel, _account = _basin()

    html = _dashboard(period).content.decode()

    assert "How this summary works" not in html


# ---------------------------------------------------------------------------
# Phase 142, plan 01: the two tables read as the equation (R-007, R-008, R-010).
# ---------------------------------------------------------------------------

import re  # noqa: E402


def _accounts_table(html):
    """The Active water accounts card's markup, from its heading to the next card."""
    start = html.index('<h2 class="section-header-flush">Active water accounts</h2>')
    # The next card's own heading. The "Zone details" eyebrow that used to
    # mark this boundary came off the page in 143-04 (2026-09-11).
    end = html.index('<h2 class="section-header-flush">Zones</h2>', start)
    return html[start:end]


def _zones_table(html):
    start = html.index('<h2 class="section-header-flush">Zones</h2>')
    end = html.index("</table>", start)
    return html[start:end]


def _header_rows(table_html):
    """The leading text of every <th>, row by row: the word before any popout."""
    thead = table_html[table_html.index("<thead>"):table_html.index("</thead>")]
    thead = thead.replace('<span class="th-stack">', "").replace("</span></th>", "</th>")
    rows = [r for r in thead.split("<tr")[1:]]
    return [[t.strip() for t in re.findall(r"<th\b[^>]*>\s*([^<]*)", r)] for r in rows]


def test_the_accounts_table_reads_as_the_equation():
    """Design B: Account | Supplies (Surface, Groundwater, Rain, Total) |
    Consumptive use | Balance | Groundwater budget (Allocation, Remaining)."""
    period, _zone, _parcel, _account = _basin()

    table = _accounts_table(_dashboard(period).content.decode())

    assert _header_rows(table) == [
        ["Account", "Supplies", "Consumptive use", "Balance", "Groundwater budget"],
        ["Surface", "Groundwater", "Rain", "Total", "Allocation", "Remaining"],
    ]
    assert 'colspan="4"' in table
    assert 'colspan="2"' in table


def test_the_zones_table_spans_three_budget_columns():
    """Zones carry Carried fwd between Allocation and Remaining."""
    period, _zone, _parcel, _account = _basin()

    table = _zones_table(_dashboard(period).content.decode())

    assert _header_rows(table) == [
        ["Zone", "Supplies", "Consumptive use", "Balance", "Groundwater budget"],
        ["Surface", "Groundwater", "Rain", "Total", "Allocation", "Carried fwd", "Remaining"],
    ]
    assert 'colspan="3"' in table


def test_the_separator_starts_at_the_groundwater_budget():
    """Design C: exactly one `col-sep` cell in each header row and in every body
    row of both tables (and in the accounts footer), never anywhere else."""
    period, _zone, _parcel, _account = _basin()
    html = _dashboard(period).content.decode()

    for table in (_accounts_table(html), _zones_table(html)):
        thead = table[table.index("<thead>"):table.index("</thead>")]
        header_rows = thead.split("<tr")[1:]
        assert len(header_rows) == 2
        for row in header_rows:
            assert row.count("col-sep") == 1
        tbody = table[table.index("<tbody>"):table.index("</tbody>")]
        body_rows = [r for r in tbody.split("<tr")[1:] if 'class="row-group"' not in r]
        assert len(body_rows) == 1
        for row in body_rows:
            assert row.count("col-sep") == 1
    accounts = _accounts_table(html)
    tfoot = accounts[accounts.index("<tfoot>"):accounts.index("</tfoot>")]
    assert tfoot.count("col-sep") == 1


def test_the_accounts_footer_equals_the_panel():
    """Design F: the footer carries the panel's own figures. From the fixture:
    supplies 0.00 + 37.50 + 0.00 = 37.50; balance 37.50 - 80.00 = -42.50."""
    period, _zone, _parcel, _account = _basin()
    html = _dashboard(period).content.decode()

    accounts = _accounts_table(html)
    tfoot = accounts[accounts.index("<tfoot>"):accounts.index("</tfoot>")]
    assert '<td class="tfoot-total">All 1 active account</td>' in tfoot
    assert '<td class="td-num text-supply">0.00</td>' in tfoot
    assert '<td class="td-num text-supply">37.50</td>' in tfoot
    assert '<td class="td-num-bold text-supply">37.50</td>' in tfoot
    assert '<td class="td-num text-usage">80.00</td>' in tfoot
    assert '<td class="td-num-bold text-deficit">-42.50</td>' in tfoot
    # The same literals lead the panel above.
    assert '>37.50<span class="budget-seg-unit">' in html
    assert '>-42.50<span class="budget-seg-unit">' in html
    # And the Zones table has no footer: a parcel can lie in more than one zone.
    assert "<tfoot>" not in _zones_table(html)
    assert "A parcel can lie in more than one zone, so rows are not added." in html


def test_no_leaf_header_carries_a_unit_and_each_card_states_it_once():
    """Design D: acre-feet is said once per card (accounts, zones, fields), and
    on no column header."""
    period, _zone, _parcel, _account = _basin()
    html = _dashboard(period).content.decode()

    main = html[html.index("<main"):html.index("</main>")]
    assert "(AF)</th>" not in main
    assert main.count("All figures in acre-feet (AF).") == 3


def test_the_footer_dashes_when_the_engine_never_ran():
    """ISS-099 reaches the footer: with no calculation run the use and balance
    cells dash, while the supply cells keep the ledger's 37.50."""
    period, _zone, _parcel, _account = _basin(with_run=False)
    html = _dashboard(period).content.decode()

    accounts = _accounts_table(html)
    tfoot = accounts[accounts.index("<tfoot>"):accounts.index("</tfoot>")]
    assert '<td class="td-num-bold text-supply">37.50</td>' in tfoot
    assert '<td class="td-num text-supply">37.50</td>' in tfoot
    assert '<td class="td-num text-tertiary">&mdash;</td>' in tfoot
    assert '<td class="td-num-bold text-tertiary">&mdash;</td>' in tfoot
    assert "80.00" not in tfoot


def test_zone_rows_are_grouped_by_groundwater_budget():
    """Design H (R-010): budgeted zones first under one divider, unbudgeted
    zones after a second divider that says why their budget cells are blank."""
    period, gsa, _parcel, _account = _basin()
    other = ParcelFactory()
    service_area = ZoneFactory(name="Basis Unbudgeted Zone", zone_type="custom")
    ParcelZoneFactory(parcel=other, zone=service_area)

    html = _dashboard(period).content.decode()
    table = _zones_table(html)

    budgeted = "Zones with a groundwater budget for Water Year 2025-2026"
    unbudgeted = (
        "Zones with no groundwater budget for Water Year 2025-2026: "
        "allocation, carry-over and remaining are not applicable"
    )
    assert table.count(budgeted) == 1
    assert table.count(unbudgeted) == 1
    assert table.index(budgeted) < table.index(gsa.name) < table.index(unbudgeted) < table.index(service_area.name)
