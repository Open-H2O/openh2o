# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pills on balance figures (Phase 151.6, plan 02), worked by hand.

A groundwater figure says how it was obtained: a green "Metered" pill for a meter
reading, an amber "Estimated" pill for groundwater worked out from crop water
use, a grey "Well share" pill for a meter reading the calculation divided among a
shared well's use areas. A surface figure says "Headgate" (a share of a headgate
total) or "Metered" (a use area's own delivery record). Crop ET, effective
precipitation, pumped water not consumed, balance, available and remaining carry
no pill. Where a figure holds two or more kinds it becomes one line per kind and
the lines add exactly to the figure shown.

The district is ``tests.ledger_districts.build_d1`` plus five more use areas, each
a different case. Every expected figure is a literal worked with a calculator
from the inputs below, never recomputed in a test.

Groundwater, WY 2024-2025 (July to September 2025):

* F1, F2 (account A): meter readings, 70.0000 + 35.0000 = 105.0000. F1 also has a
  zero-amount ``calculated`` row beside its readings (the MER-APN-039 shape).
* F3, F4 (account B): no meter. Crop water use over efficiency charges
  66.6667 and 50.0000 = 116.6667.
* F5 (account M): July estimated 26.6667 (20 AF of crop use over 0.75), August
  metered 4.0000, and a July headgate delivery of 3.0000.
* F6 (account W): a September meter reading of 9.0000 that the calculation wrote
  by dividing a shared well's reading (its description starts with
  ``WELL_METER_SHARE_WORDS``).

Surface:

* S1 (account S1): a July headgate-divided delivery, 12.5000.
* S2 (account S2): its own August delivery record, 7.2500.

The Dashboard therefore reads Surface 22.75 = 15.50 Headgate + 7.25 Metered and
Groundwater 261.33 = 109.00 Metered + 143.33 Estimated + 9.00 Well share. The
group's zone (F1 to F6) reads Used 261.33 the same way.
"""
import re
from decimal import Decimal as D
from html.parser import HTMLParser

import pytest
from django.test import Client
from django.urls import reverse

from accounting.management.commands.run_calculations import WELL_METER_SHARE_WORDS
from accounting.models import ReportingPeriod, WaterAccount, WaterAccountParcel
from core.models import User
from geography.views import _zone_budget_captions

from . import ledger_districts as ld

pytestmark = pytest.mark.django_db

WY = "WY 2024-2025"  # the water year that holds July to September 2025
JUL, AUG, SEP = ld.JUL, ld.AUG, ld.SEP


# ---------------------------------------------------------------- a small page tree
# Stdlib parser on purpose: this suite has no BeautifulSoup (same choice as
# tests/test_home_page.py). Only what these tests read is built: tags, classes,
# text, parents and a class selector.
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "source", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.classes = (self.attrs.get("class") or "").split()
        self.parent = parent
        self.children = []  # Node or str

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def select(self, selector):
        assert selector.startswith("."), selector
        name = selector[1:]
        return [n for n in self.descendants() if name in n.classes]

    def select_one(self, selector):
        found = self.select(selector)
        return found[0] if found else None

    def find(self, tag, recursive=True):
        pool = self.descendants() if recursive else (c for c in self.children if isinstance(c, Node))
        return next((n for n in pool if n.tag == tag), None)

    def find_all(self, tag, recursive=True):
        pool = self.descendants() if recursive else (c for c in self.children if isinstance(c, Node))
        return [n for n in pool if n.tag == tag]

    def find_parent(self, class_):
        node = self.parent
        while node is not None:
            if class_ in node.classes:
                return node
            node = node.parent
        return None

    def _strings(self):
        for child in self.children:
            if isinstance(child, Node):
                yield from child._strings()
            else:
                yield child

    def get_text(self, separator="", strip=False):
        parts = [t.strip() if strip else t for t in self._strings()]
        return separator.join(t for t in parts if t or not strip)

    def __str__(self):
        attrs = "".join(f' {k}="{v}"' for k, v in self.attrs.items())
        inner = "".join(str(c) for c in self.children)
        return f"<{self.tag}{attrs}>{inner}</{self.tag}>"


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("[document]", [], None)
        self._open = self.root
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        node = Node(tag, attrs, self._open)
        self._open.children.append(node)
        if tag not in _VOID:
            self._open = node

    def handle_startendtag(self, tag, attrs):
        if tag not in ("script", "style"):
            self._open.children.append(Node(tag, attrs, self._open))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1
            return
        node = self._open
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._open = node.parent

    def handle_data(self, data):
        if not self._skip:
            self._open.children.append(data)


def _parse(html):
    tree = _Tree()
    tree.feed(html)
    return tree.root


# ---------------------------------------------------------------- the district
def _surface_row(parcel, date, amount, divided):
    row = ld.ledger(parcel, date, amount, "surface_diversion", "SW",
                    "headgate share (test input)" if divided else "own delivery (test input)")
    ld.ParcelLedger.objects.filter(pk=row.pk).update(divided_from_headgate=divided)
    return row


def _account(name, number, *parcels):
    account = WaterAccount.objects.create(name=name, account_number=number, unit_kind="farm_unit")
    for parcel in parcels:
        WaterAccountParcel.objects.create(water_account=account, parcel=parcel)
    return account


@pytest.fixture
def district():
    ld.seed_reference()
    d1 = ld.build_d1()
    gsa = d1["gsa"]
    f5 = ld.add_field("F5", 100, "Alfalfa", None, [gsa], -120.47, 37.2, [{"2025-07": 60.96}],
                      ld.make_well("W5P", -120.425, 37.21))
    f6 = ld.add_field("F6", 100, None, None, [gsa], -120.45, 37.2, [], ld.make_well("W6P", -120.405, 37.21))
    s1 = ld.add_field("S1", 100, "Alfalfa", None, [], -120.43, 37.2, [{"2025-07": 30.48}])
    s2 = ld.add_field("S2", 100, "Alfalfa", None, [], -120.41, 37.2, [{"2025-07": 30.48}])
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    # Hand-entered rows go in after the runs, so no month's recalculation can replace them.
    ld.ledger(f5, AUG, "-4.0000", "meter_reading", "GW", "meter reading entered on the use area")
    _surface_row(f5, JUL, "-3.0000", True)
    ld.ledger(f6, SEP, "-9.0000", "meter_reading", "GW",
              f"{WELL_METER_SHARE_WORDS} W6P pumped 18.0000 AF this month, this use area's share is 50%")
    ld.ledger(d1["F1"], AUG, "0", "calculated", "GW", "calculated, nothing to estimate")
    _surface_row(s1, JUL, "-12.5000", True)
    _surface_row(s2, AUG, "-7.2500", False)
    accounts = {
        "A": WaterAccount.objects.get(account_number="D1-A"),
        "B": WaterAccount.objects.get(account_number="D1-B"),
        "M": _account("Mixed account", "M-1", f5),
        "W": _account("Well share account", "W-1", f6),
        "S1": _account("Headgate account", "S-1", s1),
        "S2": _account("Own delivery account", "S-2", s2),
    }
    return {**d1, "F5": f5, "F6": f6, "S1": s1, "S2": s2, "accounts": accounts}


@pytest.fixture
def client():
    c = Client()
    c.force_login(User.objects.create_user(username="reader-pills", password="x", is_active=True))
    return c


def _period_pk(name=WY):
    return ReportingPeriod.objects.get(name=name).pk


def _soup(response):
    assert response.status_code == 200
    return _parse(response.content.decode())


def _dashboard(client):
    return _soup(client.get(reverse("accounting:dashboard") + f"?period={_period_pk()}"))


def _account_page(client, account):
    return _soup(client.get(reverse("accounting:account_detail", args=[account.pk]) + f"?period={_period_pk()}"))


def _zone_page(client, zone):
    return _soup(client.get(reverse("geography:zone_detail", args=[zone.pk])))


def _use_area_page(client, parcel):
    return _soup(client.get(reverse("parcels:detail", args=[parcel.pk]) + f"?period={_period_pk()}"))


# ---------------------------------------------------------------- readers
def _words(node):
    return " ".join(node.get_text(" ").split())


def _row(row):
    return {
        "label": _words(row.find("span", recursive=False)),
        "pills": [_words(p) for p in row.select(".kind-pill")],
        "figure": row.find("b").get_text(strip=True),
    }


def _group(soup, title):
    for heading in soup.select(".budget-breakdown-title"):
        if heading.get_text(strip=True) == title:
            return heading.parent
    raise AssertionError(f"no breakdown group titled {title!r}")


def _supply_lines(soup, label):
    """(pill, figure) for each line of the Supplies breakdown with this label, sorted."""
    rows = [_row(r) for r in _group(soup, "Supplies by source").select(".budget-breakdown-row")]
    lines = []
    for r in rows:
        if r["label"] == label:
            assert len(r["pills"]) <= 1, f"one pill per line, got {r['pills']}"
            lines.append((r["pills"][0] if r["pills"] else "", r["figure"]))
    return sorted(lines)


def _seg(soup, label):
    for seg in soup.select(".budget-seg"):
        head = seg.select_one(".budget-seg-label")
        if head is not None and head.get_text(" ", strip=True).startswith(label):
            return seg
    raise AssertionError(f"no segment labelled {label!r}")


def _money(text):
    return D(text.replace(",", ""))


# ---------------------------------------------------------------- (a) the pill rules
def test_a_metered_use_area_shows_one_metered_line(district, client):
    # F1 and F2: meter readings 70.00 + 35.00. The zero-amount calculated row on F1
    # beside its readings adds no Estimated line and no pill.
    page = _account_page(client, district["accounts"]["A"])
    assert _supply_lines(page, "Groundwater") == [("Metered", "105.00")]
    assert _supply_lines(page, "Surface") == [("", "0.00")]


def test_an_estimated_use_area_shows_one_estimated_line(district, client):
    page = _account_page(client, district["accounts"]["B"])
    assert _supply_lines(page, "Groundwater") == [("Estimated", "116.67")]


def test_a_use_area_with_both_kinds_shows_a_line_for_each(district, client):
    page = _account_page(client, district["accounts"]["M"])
    assert _supply_lines(page, "Groundwater") == [("Estimated", "26.67"), ("Metered", "4.00")]


def test_a_headgate_divided_delivery_shows_the_headgate_pill(district, client):
    page = _account_page(client, district["accounts"]["S1"])
    assert _supply_lines(page, "Surface") == [("Headgate", "12.50")]


def test_a_use_areas_own_delivery_shows_the_metered_pill(district, client):
    page = _account_page(client, district["accounts"]["S2"])
    assert _supply_lines(page, "Surface") == [("Metered", "7.25")]


def test_a_well_share_meter_row_shows_the_well_share_pill(district, client):
    page = _account_page(client, district["accounts"]["W"])
    assert _supply_lines(page, "Groundwater") == [("Well share", "9.00")]


def test_a_mixed_account_names_its_surface_kind_beside_its_groundwater_kinds(district, client):
    page = _account_page(client, district["accounts"]["M"])
    assert _supply_lines(page, "Surface") == [("Headgate", "3.00")]


# ---------------------------------------------------------------- (b) the lines add to the figure
def test_the_lines_of_a_mixed_account_add_exactly_to_its_supplies(district, client):
    page = _account_page(client, district["accounts"]["M"])
    lines = [_row(r) for r in _group(page, "Supplies by source").select(".budget-breakdown-row")]
    total = _seg(page, "Supplies").select_one(".budget-seg-value").get_text(strip=True).removesuffix("AF")
    assert total == "33.67"
    assert sum(_money(r["figure"]) for r in lines) == D("33.67")


@pytest.fixture
def rounding_district():
    """One use area whose two kinds, rounded one by one, would add to a cent more than the figure.

    Metered 1.0070 and Estimated 2.0060 are 3.0130 together, which shows as 3.01.
    Rounded alone they are 1.01 and 2.01, which add to 3.02. With no calculation
    run behind the calculated row it charges its recorded amount.
    """
    ld.seed_reference()
    parcel = ld.add_field("R1", 100, None, None, [], -120.5, 37.2, [])
    ld.ledger(parcel, JUL, "-1.0070", "meter_reading", "GW", "meter reading entered on the use area")
    ld.ledger(parcel, AUG, "-2.0060", "calculated", "GW", "calculated test input")
    return _account("Rounding account", "R-1", parcel)


def test_plain_rounding_would_be_a_cent_off_so_the_account_lines_are_adjusted(rounding_district, client):
    page = _account_page(client, rounding_district)
    assert _supply_lines(page, "Groundwater") == [("Estimated", "2.00"), ("Metered", "1.01")]
    total = _seg(page, "Supplies").select_one(".budget-seg-value").get_text(strip=True).removesuffix("AF")
    assert total == "3.01"


def test_plain_rounding_would_be_a_cent_off_so_the_dashboard_lines_are_adjusted(rounding_district, client):
    page = _dashboard(client)
    assert _supply_lines(page, "Groundwater") == [("Estimated", "2.00"), ("Metered", "1.01")]


# ---------------------------------------------------------------- (c) the rendered pages
def test_the_dashboard_water_balance_panel_shows_each_kind_with_its_pill(district, client):
    page = _dashboard(client)
    assert _supply_lines(page, "Surface") == [("Headgate", "15.50"), ("Metered", "7.25")]
    assert _supply_lines(page, "Groundwater") == [
        ("Estimated", "143.33"), ("Metered", "109.00"), ("Well share", "9.00")]


def test_the_dashboard_lines_add_exactly_to_the_figures_in_the_panel(district, client):
    page = _dashboard(client)
    rows = [_row(r) for r in _group(page, "Supplies by source").select(".budget-breakdown-row")]
    total = _seg(page, "Supplies").select_one(".budget-seg-value").get_text(strip=True).removesuffix("AF")
    assert total == "284.08"
    assert sum(_money(r["figure"]) for r in rows) == _money(total)


def test_the_dashboard_puts_a_pill_on_no_other_line(district, client):
    page = _dashboard(client)
    panel = _group(page, "Supplies by source").find_parent(class_="budget-panel")
    assert len(panel.select(".kind-pill")) == 5  # two Surface lines and three Groundwater lines
    precip = [_row(r) for r in _group(page, "Supplies by source").select(".budget-breakdown-row")
              if _row(r)["label"] == "Effective precipitation"]
    assert [(r["pills"], r["figure"]) for r in precip] == [([], "0.00")]
    for title in ("Uses by destination", "Estimate coverage", "Balance by account"):
        assert _group(page, title).select(".kind-pill") == []
    for label in ("Uses", "Balance"):
        assert _seg(page, label).select(".kind-pill") == []


def test_the_account_page_puts_a_pill_on_no_other_line(district, client):
    page = _account_page(client, district["accounts"]["M"])
    panel = _group(page, "Supplies by source").find_parent(class_="budget-panel")
    assert len(panel.select(".kind-pill")) == 3  # one Surface line and two Groundwater lines
    assert _group(page, "Uses by destination").select(".kind-pill") == []
    assert _seg(page, "Supplies").select(".kind-pill") != []
    assert _seg(page, "Balance").select(".kind-pill") == []


def test_the_zone_used_cell_lists_its_kinds_as_lines_with_pills(district, client):
    page = _zone_page(client, district["gsa"])
    used = _seg(page, "Used")
    lines = sorted((_words(r.select_one(".kind-pill")), r.find("b").get_text(strip=True))
                   for r in used.select(".budget-breakdown-row") if r.select_one(".kind-pill"))
    assert lines == [("Estimated", "143.33"), ("Metered", "109.00"), ("Well share", "9.00")]
    assert used.select_one(".budget-seg-value").get_text(strip=True).removesuffix("AF") == "261.33"


def test_the_zone_available_and_remaining_cells_carry_no_pill(district, client):
    page = _zone_page(client, district["gsa"])
    assert _seg(page, "Available").select(".kind-pill") == []
    assert _seg(page, "Remaining").select(".kind-pill") == []


def _lead_cells(page):
    lead = page.select_one(".statement-lead")
    cells = {}
    for cell in lead.find_all("div", recursive=False):
        label = cell.select_one(".budget-seg-label").get_text(strip=True)
        cells[label] = cell
    return cells


def _cell_pills(cell):
    return sorted(_words(p) for p in cell.select(".kind-pill"))


def test_a_metered_use_area_page_puts_the_metered_pill_under_its_extraction(district, client):
    cells = _lead_cells(_use_area_page(client, district["F1"]))
    assert cells["Groundwater extraction"].select_one(".budget-seg-value").get_text(strip=True) == "70.00AF"
    assert _cell_pills(cells["Groundwater extraction"]) == ["Metered"]
    # The pill sits above the link note to the well.
    html = str(cells["Groundwater extraction"])
    assert html.index("kind-pill") < html.index("prose-link")
    assert _cell_pills(cells["Surface water delivered"]) == []


def test_an_estimated_use_area_page_puts_the_estimated_pill_under_its_extraction(district, client):
    cells = _lead_cells(_use_area_page(client, district["F4"]))
    assert cells["Groundwater extraction"].select_one(".budget-seg-value").get_text(strip=True) == "50.00AF"
    assert _cell_pills(cells["Groundwater extraction"]) == ["Estimated"]


def test_a_use_area_page_with_both_kinds_shows_both_pills(district, client):
    cells = _lead_cells(_use_area_page(client, district["F5"]))
    assert cells["Groundwater extraction"].select_one(".budget-seg-value").get_text(strip=True) == "30.67AF"
    assert _cell_pills(cells["Groundwater extraction"]) == ["Estimated", "Metered"]
    assert cells["Surface water delivered"].select_one(".budget-seg-value").get_text(strip=True) == "3.00AF"
    assert _cell_pills(cells["Surface water delivered"]) == ["Headgate"]


def test_a_use_area_page_shows_the_headgate_pill_under_a_divided_delivery(district, client):
    cells = _lead_cells(_use_area_page(client, district["S1"]))
    assert cells["Surface water delivered"].select_one(".budget-seg-value").get_text(strip=True) == "12.50AF"
    assert _cell_pills(cells["Surface water delivered"]) == ["Headgate"]


def test_a_use_area_page_shows_the_metered_pill_under_its_own_delivery(district, client):
    cells = _lead_cells(_use_area_page(client, district["S2"]))
    assert cells["Surface water delivered"].select_one(".budget-seg-value").get_text(strip=True) == "7.25AF"
    assert _cell_pills(cells["Surface water delivered"]) == ["Metered"]


def test_a_use_area_page_puts_no_pill_on_crop_et_or_effective_precipitation(district, client):
    for key in ("F1", "F4", "F5", "S1"):
        cells = _lead_cells(_use_area_page(client, district[key]))
        assert _cell_pills(cells["Crop ET"]) == [], key
        assert _cell_pills(cells["Effective precipitation"]) == [], key


# ---------------------------------------------------------------- (d) the zone caption
def test_the_zone_groundwater_caption_reads_pumped_and_the_period_name():
    assert _zone_budget_captions(True, WY)["used"] == f"pumped, {WY}"


def test_the_zone_surface_caption_is_unchanged():
    assert _zone_budget_captions(False, WY)["used"] == f"delivered, {WY}"


def test_the_zone_page_prints_the_pumped_caption_under_used(district, client):
    page = _zone_page(client, district["gsa"])
    caption = _seg(page, "Used").select_one(".budget-seg-caption").get_text(strip=True)
    assert caption == f"pumped, {WY}"
    assert re.search(r"metered or estimated", page.get_text(" ")) is None
