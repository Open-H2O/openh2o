# SPDX-License-Identifier: AGPL-3.0-or-later
"""The use area page opens on a Water use card: three or four year figures, the lines
that say what is off, and one row for each month of the water year.

* The figures are the sums of the month cells: each column's cells are rounded so they
  add exactly to the year figure, and the lead figure is that year figure.
* A figure that rounds to 0.00 prints as an empty cell, and a fallow month reads Fallow
  in the crop ET column.
* The Water balance panel (supplies minus uses, the residual and its badge) is not on this
  page. The dashboard and the account pages keep it.

Every expected figure is a literal worked by hand.
"""

import datetime as dt
import html as html_lib
import re
from decimal import Decimal as D

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from core.map_labels import map_label
from parcels.models import ParcelIrrigationMethod
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

START = dt.date(2025, 10, 1)
END = dt.date(2026, 9, 30)
MONTHS = [
    dt.date(2025, 10, 1), dt.date(2025, 11, 1), dt.date(2025, 12, 1),
    dt.date(2026, 1, 1), dt.date(2026, 2, 1), dt.date(2026, 3, 1),
    dt.date(2026, 4, 1), dt.date(2026, 5, 1), dt.date(2026, 6, 1),
    dt.date(2026, 7, 1), dt.date(2026, 8, 1), dt.date(2026, 9, 1),
]
NOV, DEC, JAN = MONTHS[1], MONTHS[2], MONTHS[3]


# ------------------------------------------------------------------ fixtures
def water_year():
    return ReportingPeriodFactory(name="WY 2025-2026", start_date=START, end_date=END)


def use_area(number="APN-D1", acres="57.01"):
    return ParcelFactory(parcel_number=number, area_acres=D(acres))


def run(parcel, month, et="0", precip="0", **extra):
    return CalculationRun.objects.create(
        parcel=parcel, period=f"{month:%Y-%m}", gross_et_af=D(et),
        effective_precip_af=D(precip), net_consumptive_use_af=D(et), final_af=D("0"),
        **extra,
    )


def delivery(parcel, rp, month, af, day=15, description="Delivery"):
    when = month.replace(day=day)
    return ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="surface_diversion",
        amount_acre_feet=-D(af), transaction_date=when, effective_date=when,
        description=description,
    )


def fetch(parcel, rp, hx=False):
    user, _ = User.objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    extra = {"HTTP_HX_REQUEST": "true"} if hx else {}
    response = client.get(reverse("parcels:detail", args=[parcel.pk]), {"period": rp.pk}, **extra)
    assert response.status_code == 200
    return response.content.decode()


def has_balance_panel(body):
    """Whether the page carries the `.budget-panel` component (its own class, not a `budget-panel-*` part)."""
    return re.search(r'class="[^"]*\bbudget-panel(?![\w-])', body) is not None


def card_of(body):
    """The Water use card: from its head to the use area details beside the ledger."""
    assert "statement-head" in body, "the page has no Water use card"
    return body.split("statement-head", 1)[1].split("page-grid-2col", 1)[0]


def words(fragment):
    """The visible text of a fragment, with entities decoded and spaces collapsed."""
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def card(parcel, rp, hx=False):
    return card_of(fetch(parcel, rp, hx))


def body_rows(card_html):
    tbody = card_html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return re.findall(r"<tr>(.*?)</tr>", tbody, re.S)


def cells(row):
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)


def column(card_html, index):
    """The text of column ``index`` for each month row, then the foot row."""
    rows = [words(cells(r)[index]) for r in body_rows(card_html)]
    foot = card_html.split("<tfoot>", 1)[1].split("</tfoot>", 1)[0]
    return rows, words(cells(foot)[index])


def fallow_periods():
    return apps.get_model("parcels", "FallowPeriod")


def make_fallow(parcel, start, end=None):
    return fallow_periods().objects.create(parcel=parcel, start_month=start, end_month=end)


def one_canal(name="Le Grand Canal Headgate", fields=("APN-D1", "APN-D2", "APN-D3")):
    pod = PointOfDiversionFactory(
        name=name, evaporation_fraction=D("0"), seepage_fraction=D("0"), spill_fraction=D("0"),
        division_method="shares",
    )
    parcels = [use_area(n) if n == "APN-D1" else ParcelFactory(parcel_number=n) for n in fields]
    for parcel in parcels:
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel, fraction=D("1.0000"))
    return pod, parcels


def canal_water(pod, rp, month, af="30.0000"):
    return DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=month,
        volume_acre_feet=D(af), diversion_type="direct_use",
    )


# ------------------------------------------------------------------ (a) the card replaces the panel
def test_the_page_shows_the_water_use_card_and_not_the_water_balance():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    body = fetch(parcel, rp)
    head = card_of(body)
    assert "Water use" in words(head)
    assert "All ledger entries" in words(head)
    assert f"?q={parcel.parcel_number}" in head
    assert 'name="period"' in head or "WY 2025-2026" in words(head)
    assert not has_balance_panel(body)
    text = words(head)
    for gone in ("Water balance", "Residual", "Deficit", "Supplies by source", "Not in this residual"):
        assert gone not in text


def test_the_workspace_pane_shows_the_same_card():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    body = fetch(parcel, rp, hx=True)
    assert not has_balance_panel(body)
    assert "Water use" in words(card_of(body))
    assert "All ledger entries" in words(card_of(body))


def test_switching_the_period_on_the_standalone_page_brings_no_second_head():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    user, _ = User.objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    page_url = reverse("parcels:detail", args=[parcel.pk])
    on_page = client.get(
        page_url, {"period": rp.pk},
        HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL=f"https://example.test{page_url}",
    ).content.decode()
    assert "pane-header" not in on_page
    assert "Open full page" not in on_page
    elsewhere = client.get(
        page_url, {"period": rp.pk},
        HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL="https://example.test/parcels/",
    ).content.decode()
    assert "Open full page" in elsewhere


def test_the_period_control_is_the_card_s_own_select():
    water_year()
    rp2 = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30)
    )
    parcel = use_area()
    run(parcel, dt.date(2025, 1, 1), et="1.0000")
    head = card(parcel, rp2)
    assert 'name="period"' in head
    assert re.search(r'<option value="%d" selected>WY 2024-2025</option>' % rp2.pk, head)


def test_the_dashboard_keeps_its_balance_panel():
    from tests.test_dashboard_budget_basis import UserFactory, _basin

    period, zone, parcel, account = _basin()
    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard") + f"?period={period.pk}")
    assert response.status_code == 200
    assert "budget-panel" in response.content.decode()


# ------------------------------------------------------------------ (b) a use area with no well
def test_a_use_area_with_no_well_has_three_figures_and_names_the_headgate():
    rp = water_year()
    pod, (parcel, _b, _c) = one_canal(name="Test Canal Headgate")
    run(parcel, NOV, et="10.0000", precip="1.0000")
    delivery(parcel, rp, NOV, "6.0000")
    head = card(parcel, rp)
    labels = re.findall(r'<div class="budget-seg-label">([^<]*)</div>', head)
    assert labels == ["Crop ET", "Surface water delivered", "Effective precipitation"]
    assert "57.01 acres" in words(head)
    assert "No well on this use area" in words(head)
    link = re.search(r'<a href="%s"[^>]*>([^<]*)</a>' % reverse("surface:pod_detail", args=[pod.pk]), head)
    assert link and link.group(1) == map_label("Test Canal Headgate")
    assert "Groundwater extraction" not in words(head)


def test_two_headgates_are_both_linked_and_a_use_area_with_none_has_no_note():
    rp = water_year()
    parcel = use_area()
    one = PointOfDiversionFactory(name="North Headgate")
    two = PointOfDiversionFactory(name="South Headgate")
    PointOfDiversionParcelFactory(point_of_diversion=one, parcel=parcel)
    PointOfDiversionParcelFactory(point_of_diversion=two, parcel=parcel)
    run(parcel, NOV, et="2.0000")
    head = card(parcel, rp)
    assert reverse("surface:pod_detail", args=[one.pk]) in head
    assert reverse("surface:pod_detail", args=[two.pk]) in head
    assert "North Headgate</a>, <a" in head

    bare = use_area("APN-BARE")
    run(bare, NOV, et="2.0000")
    bare_head = card(bare, rp)
    assert "/surface/diversion/" not in bare_head.split("statement-notes")[0]


# ------------------------------------------------------------------ (c) a use area with a well
def test_a_use_area_with_a_well_has_four_figures_with_groundwater_third():
    rp = water_year()
    parcel = use_area()
    link = WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, NOV, et="10.0000")
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=D("-3.0000"),
        transaction_date=dt.date(2025, 11, 20), effective_date=dt.date(2025, 11, 20),
    )
    head = card(parcel, rp)
    labels = re.findall(r'<div class="budget-seg-label">([^<]*)</div>', head)
    assert labels == [
        "Crop ET", "Surface water delivered", "Groundwater extraction", "Effective precipitation",
    ]
    assert reverse("wells:detail", args=[link.well.pk]) in head.split("statement-notes")[0]
    assert "No well on this use area" not in words(head)
    headers = [words(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", head, re.S)]
    assert headers == [
        "Month", "Crop ET", "Surface water delivered", "Groundwater extraction",
        "Effective precipitation",
    ]
    rows, total = column(head, 3)
    assert rows[1] == "3.00" and total == "3.00"
    lead = re.findall(r'<div class="budget-seg-value">([^<]*)<span', head)
    assert lead[2].strip() == "3.00"


# ------------------------------------------------------------------ (d) the month table
def test_one_row_for_each_month_each_linking_to_the_ledger():
    rp = water_year()
    parcel = use_area("APN-D1")
    run(parcel, NOV, et="4.0000")
    head = card(parcel, rp)
    rows = body_rows(head)
    assert len(rows) == 12
    labels = [words(cells(r)[0]) for r in rows]
    assert labels[0] == "Oct 2025" and labels[-1] == "Sep 2026"
    ledger = reverse("accounting:ledger_list")
    assert (
        f'href="{ledger}?q=APN-D1&amp;start_date=2025-10-01&amp;end_date=2025-10-31"' in rows[0]
    )
    assert (
        f'href="{ledger}?q=APN-D1&amp;start_date=2026-02-01&amp;end_date=2026-02-28"' in rows[4]
    )
    assert "data-table-link" in rows[11]


def test_a_month_with_nothing_on_record_is_an_empty_cell_never_0_00():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000", precip="0.0000")
    delivery(parcel, rp, NOV, "2.0000")
    head = card(parcel, rp)
    november = body_rows(head)[1]
    assert cells(november)[1:] == ["4.00", "2.00", ""]
    october = body_rows(head)[0]
    assert "0.00" not in october
    assert cells(october)[1:] == ["", "", ""]
    assert '<td class="td-num"></td>' in october


def test_a_fallow_month_reads_fallow_in_the_crop_et_cell_and_the_foot_names_the_year():
    rp = water_year()
    parcel = use_area()
    make_fallow(parcel, dt.date(2026, 3, 1), dt.date(2026, 4, 1))
    run(parcel, dt.date(2026, 3, 1), et="0.0000", precip="2.0000")
    head = card(parcel, rp)
    rows = body_rows(head)
    march = rows[5]
    assert 'class="td-fallow"' in march and "Fallow" in words(cells(march)[1])
    assert "Fallow" in words(cells(rows[6])[1])
    assert "Fallow" not in words(cells(rows[7])[1])
    assert cells(march)[3] == "2.00"
    foot = head.split("<tfoot>", 1)[1].split("</tfoot>", 1)[0]
    assert 'class="tfoot-total"' in foot and words(cells(foot)[0]) == "WY 2025-2026"


def test_the_ledger_date_filter_reads_the_date_the_figures_are_grouped_on():
    """A delivery on the 31st is in its month's figure and inside the month's link dates."""
    rp = water_year()
    parcel = use_area("APN-D1")
    delivery(parcel, rp, dt.date(2025, 12, 1), "5.0000", day=31, description="Last day delivery")
    run(parcel, dt.date(2025, 12, 1), et="5.0000")
    head = card(parcel, rp)
    assert column(head, 2)[0][2] == "5.00"
    user, _ = User.objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    listing = client.get(
        reverse("accounting:ledger_list"),
        {"q": "APN-D1", "start_date": "2025-12-01", "end_date": "2025-12-31"},
    ).content.decode()
    assert "Last day delivery" in listing
    outside = client.get(
        reverse("accounting:ledger_list"),
        {"q": "APN-D1", "start_date": "2025-11-01", "end_date": "2025-11-30"},
    ).content.decode()
    assert "Last day delivery" not in outside


# ------------------------------------------------------------------ (e) rounding
def test_round_to_total_adds_exactly_when_cell_rounding_overshoots():
    from accounting.services import round_to_total

    cells_ = round_to_total([D("0.005"), D("0.005"), D("0.005")])
    assert sum(cells_) == D("0.02")
    assert sorted(cells_) == [D("0.00"), D("0.01"), D("0.01")]


def test_round_to_total_adds_exactly_when_cell_rounding_undershoots():
    from accounting.services import round_to_total

    cells_ = round_to_total([D("0.004")] * 100)
    assert sum(cells_) == D("0.40")
    assert all(c in (D("0.00"), D("0.01")) for c in cells_)


def test_round_to_total_moves_a_cell_by_at_most_one_hundredth_from_its_own_rounding():
    from accounting.services import round_to_total

    values = [D("12.2549"), D("4.6451"), D("2.9949"), D("3.6349"), D("6.2551"), D("25.7749")]
    out = round_to_total(values)
    assert sum(out) == sum(values).quantize(D("0.01"), rounding="ROUND_HALF_UP")
    for value, cell in zip(values, out):
        own = value.quantize(D("0.01"), rounding="ROUND_HALF_UP")
        assert abs(cell - own) <= D("0.01")


def test_round_to_total_keeps_zeros_and_an_empty_list():
    from accounting.services import round_to_total

    assert round_to_total([]) == []
    assert round_to_total([D("0"), D("0")]) == [D("0.00"), D("0.00")]


def test_the_crop_et_cells_add_to_the_foot_and_the_foot_is_the_lead_figure():
    rp = water_year()
    parcel = use_area()
    for month in MONTHS[:3]:
        run(parcel, month, et="0.0050", precip="0.0050")
    head = card(parcel, rp)
    for index in (1, 3):
        rows, total = column(head, index)
        shown = [D(r) for r in rows if r]
        assert total == "0.02"
        assert sum(shown) == D(total)
    lead = re.findall(r'<div class="budget-seg-value">([^<]*)<span', head)
    assert lead[0].strip() == "0.02"
    assert lead[-1].strip() == "0.02"


# ------------------------------------------------------------------ (f) the unmet demand line
def unmet(parcel, month, af, et="5.0000"):
    return run(
        parcel, month, et=et, residual_disposition="unmet_demand", unmet_demand_af=D(af)
    )


def test_several_months_of_unmet_demand_give_the_count_in_words_and_the_popout():
    rp = water_year()
    parcel = use_area()
    unmet(parcel, NOV, "1.5000")
    unmet(parcel, DEC, "2.0000")
    unmet(parcel, JAN, "3.0000")
    head = card(parcel, rp)
    assert (
        "Crop ET exceeded the supplies on record in three months, 6.50 AF in all. OpenH2O "
        "records the difference as water use recorded, no supply reported."
    ) in words(head)
    assert 'aria-label="Explain: Water use recorded, no supply reported"' in head
    assert "never counts this water as pumping" in head


def test_a_count_above_nine_is_still_in_words_to_twelve():
    rp = water_year()
    parcel = use_area()
    for month in MONTHS:
        unmet(parcel, month, "1.0000")
    assert "in twelve months, 12.00 AF in all." in words(card(parcel, rp))


def test_one_month_of_unmet_demand_names_the_month_and_the_amount():
    rp = water_year()
    parcel = use_area()
    unmet(parcel, JAN, "2.5000")
    run(parcel, NOV, et="4.0000")
    assert (
        "Crop ET exceeded the supplies on record in January 2026 by 2.50 AF. OpenH2O records "
        "the difference as water use recorded, no supply reported."
    ) in words(card(parcel, rp))


def test_no_unmet_demand_means_no_line():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    head = card(parcel, rp)
    assert "Crop ET exceeded" not in words(head)
    assert "no supply reported" not in words(head)


# ------------------------------------------------------------------ (g) the fallow line
def fallow_world(fallow_months, record_months=(NOV, DEC, JAN)):
    rp = water_year()
    pod, (parcel, _b, _c) = one_canal()
    for month in record_months:
        canal_water(pod, rp, month)
    for start, end in fallow_months:
        make_fallow(parcel, start, end)
    run(parcel, NOV, et="1.0000")
    return rp, pod, parcel


def test_several_fallow_months_say_so_and_name_the_headgate():
    rp, pod, parcel = fallow_world([(NOV, JAN)])
    assert (
        "In the fallow months OpenH2O counted crop ET as 0 and divided Le Grand Canal "
        "Headgate's water among the other use areas on it."
    ) in words(card(parcel, rp))


def test_one_fallow_month_reads_fallow_month_in_the_singular():
    rp, pod, parcel = fallow_world([(DEC, DEC)])
    assert (
        "In the fallow month OpenH2O counted crop ET as 0 and divided Le Grand Canal "
        "Headgate's water among the other use areas on it."
    ) in words(card(parcel, rp))


def test_fallow_months_that_are_not_next_to_each_other_use_the_same_words():
    rp, pod, parcel = fallow_world([(NOV, NOV), (JAN, JAN)])
    assert (
        "In the fallow months OpenH2O counted crop ET as 0 and divided Le Grand Canal "
        "Headgate's water among the other use areas on it."
    ) in words(card(parcel, rp))


def test_two_headgates_are_both_named_with_their_possessives():
    rp = water_year()
    parcel = use_area()
    names = ("North Headgate", "South Headgate")
    for name in names:
        pod = PointOfDiversionFactory(
            name=name, evaporation_fraction=D("0"), seepage_fraction=D("0"),
            spill_fraction=D("0"), division_method="shares",
        )
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
        PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=ParcelFactory())
        canal_water(pod, rp, NOV)
    make_fallow(parcel, NOV, NOV)
    run(parcel, DEC, et="1.0000")
    assert (
        "In the fallow month OpenH2O counted crop ET as 0 and divided North Headgate's and "
        "South Headgate's water among the other use areas on them."
    ) in words(card(parcel, rp))


def test_a_fallow_month_with_no_canal_water_to_divide_has_no_headgate_clause():
    rp, pod, parcel = fallow_world([(NOV, JAN)], record_months=())
    text = words(card(parcel, rp))
    assert "In the fallow months OpenH2O counted crop ET as 0." in text
    assert "divided" not in text


def test_a_use_area_never_fallow_has_no_fallow_line():
    rp, pod, parcel = fallow_world([])
    assert "fallow month" not in words(card(parcel, rp)).replace("Fallow", "")
    assert "counted crop ET as 0" not in words(card(parcel, rp))


# ------------------------------------------------------------------ (h) the estimated groundwater line
def calculated_row(parcel, rp, month, af="2.0000"):
    return ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="calculated",
        amount_acre_feet=-D(af), transaction_date=month, effective_date=month,
    )


def test_a_well_field_with_an_estimate_and_no_meter_says_so():
    rp = water_year()
    parcel = use_area()
    WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, NOV, et="4.0000")
    calculated_row(parcel, rp, NOV)
    assert (
        "OpenH2O estimated the groundwater extraction, because no meter readings are on "
        "record for the water year."
    ) in words(card(parcel, rp))


def test_a_well_field_with_some_meter_readings_says_which_months_were_estimated():
    rp = water_year()
    parcel = use_area()
    WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, NOV, et="4.0000")
    run(parcel, DEC, et="4.0000")
    calculated_row(parcel, rp, NOV)
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=D("-3.0000"), transaction_date=dt.date(2025, 12, 20),
        effective_date=dt.date(2025, 12, 20),
    )
    assert (
        "OpenH2O estimated the groundwater extraction in the months with no meter reading on "
        "record."
    ) in words(card(parcel, rp))


def test_a_metered_well_field_has_no_estimate_line():
    rp = water_year()
    parcel = use_area()
    WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, DEC, et="4.0000", residual_disposition="metered")
    ParcelLedgerFactory(
        parcel=parcel, reporting_period=rp, source_type="meter_reading",
        amount_acre_feet=D("-3.0000"), transaction_date=dt.date(2025, 12, 20),
        effective_date=dt.date(2025, 12, 20),
    )
    assert "OpenH2O estimated the groundwater extraction" not in words(card(parcel, rp))


def test_the_excess_surface_water_line_appears_only_when_delivery_settings_show_it():
    rp = water_year()
    parcel = use_area("APN-D1")
    run(
        parcel, NOV, et="4.0000", over_delivery_af=D("1.2500"),
        over_delivery_treatment="named_line",
    )
    text = words(card(parcel, rp))
    assert (
        "Surface water in excess of ETAW came to 1.25 AF. OpenH2O neither credits it to the "
        "landowner nor charges it to APN-D1."
    ) in text
    other = use_area("APN-D9")
    run(other, NOV, et="4.0000", over_delivery_af=D("1.2500"))
    assert "Surface water in excess of ETAW" not in words(card(other, rp))


# ------------------------------------------------------------------ (i) no calculation in the period
def test_a_period_with_no_calculation_keeps_the_head_and_says_crop_et_was_not_calculated():
    rp = water_year()
    earlier = ReportingPeriodFactory(
        name="WY 2024-2025", start_date=dt.date(2024, 10, 1), end_date=dt.date(2025, 9, 30)
    )
    parcel = use_area()
    run(parcel, dt.date(2025, 1, 1), et="4.0000")
    delivery(parcel, rp, NOV, "2.0000")
    head = card(parcel, rp)
    text = words(head)
    assert "Water use" in text and "All ledger entries" in text
    assert 'name="period"' in head
    assert "OpenH2O has not calculated crop ET for this use area in this water year." in text
    assert "so there is no balance yet" not in text
    assert "Recorded supplies: surface 2.00 · groundwater 0.00 AF." in text
    assert "<table" not in head
    assert earlier.pk != rp.pk


# ------------------------------------------------------------------ (j) the turnout page
def test_the_turnout_page_names_the_use_area_the_month_and_the_headgate():
    rp = water_year()
    pod, (parcel, _b, _c) = one_canal()
    canal_water(pod, rp, DEC)
    make_fallow(parcel, DEC, DEC)
    user, _ = User.objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    body = client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    assert (
        "Use area APN-D1 was fallow in December 2025. OpenH2O divided this month's water among "
        "the other use areas on Le Grand Canal Headgate."
    ) in html_lib.unescape(body)
    assert "gave it no share" not in html_lib.unescape(body)


def test_the_old_no_share_words_are_nowhere_in_the_product_code():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for folder in ("parcels", "surface", "accounting"):
        for path in (root / folder).rglob("*.py"):
            if "migrations" in path.parts:
                continue
            text = " ".join(path.read_text().split())
            assert "gave it no share" not in text, path
            assert "gave it no share" not in text.replace('" f"', ""), path
            assert "so OpenH2O gave it" not in text, path


# ------------------------------------------------------------------ (k) the foot
def delivered_run(parcel, month, efficiency="0.750", af="4.0000"):
    return run(
        parcel, month, et="4.0000", surface_delivered_af=D(af),
        surface_water_af=D(af) * D(efficiency), surface_efficiency=D(efficiency),
    )


def test_the_foot_names_the_irrigation_efficiency_on_delivery_settings():
    rp = water_year()
    parcel = use_area()
    delivered_run(parcel, NOV)
    delivery(parcel, rp, NOV, "4.0000")
    text = words(card(parcel, rp))
    assert (
        "Acre-feet. Surface water counts toward crop ET at the 75% irrigation efficiency on "
        "Delivery Settings. A month opens its ledger entries. An empty cell is a month with "
        "nothing on record."
    ) in text
    assert "Methods behind the numbers" in text


def test_the_foot_keeps_a_half_percent_and_names_a_use_area_s_own_efficiency():
    from parcels.models import IrrigationMethod

    rp = water_year()
    parcel = use_area()
    method = IrrigationMethod.objects.order_by('sort_order').first()
    assert method is not None
    ParcelIrrigationMethod.objects.create(parcel=parcel, method=method)
    delivered_run(parcel, NOV, efficiency=str(method.assigned_efficiency))
    delivery(parcel, rp, NOV, "4.0000")
    percent = (method.assigned_efficiency * 100).normalize()
    text = words(card(parcel, rp))
    assert f"at this use area's {format(percent, 'f')}% irrigation efficiency." in text


def test_the_foot_says_each_month_s_efficiency_when_the_months_differ():
    rp = water_year()
    parcel = use_area()
    delivered_run(parcel, NOV, efficiency="0.750")
    delivered_run(parcel, DEC, efficiency="0.600")
    delivery(parcel, rp, NOV, "4.0000")
    delivery(parcel, rp, DEC, "4.0000")
    text = words(card(parcel, rp))
    assert "Surface water counts toward crop ET at each month's irrigation efficiency." in text


def test_the_foot_leaves_the_surface_sentence_out_when_nothing_was_delivered():
    rp = water_year()
    parcel = use_area()
    run(parcel, NOV, et="4.0000")
    text = words(card(parcel, rp))
    assert "Surface water counts toward crop ET" not in text
    assert text.count("Acre-feet. A month opens its ledger entries.") == 1


def test_the_estimated_groundwater_receipt_links_stay_between_the_table_and_the_foot():
    rp = water_year()
    parcel = use_area()
    WellIrrigatedParcelFactory(parcel=parcel)
    run(parcel, NOV, et="4.0000", residual_disposition="groundwater")
    head = card(parcel, rp)
    table_end = head.index("</table>")
    links = head.index("Estimated groundwater extraction, month by month:")
    foot = head.index("statement-foot")
    assert table_end < links < foot
