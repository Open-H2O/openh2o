# SPDX-License-Identifier: AGPL-3.0-or-later
"""How measured: pills on balance figures (Phase 151.6, plan 02), worked by hand.

A Surface or Groundwater figure says how it was measured, with three pills under a
small "How measured" heading: green "Metered", amber "Estimated", grey "Unknown".

* Groundwater: a meter reading is Metered, a shared well's reading divided among
  its use areas included; OpenH2O's calculated pumping is Estimated; any other
  row (typed or uploaded) is Unknown.
* Surface: a delivery takes the measurement method of the diversion record behind
  it. A use area's share of a point's month takes that point's month records'
  methods, split by their volumes where they differ. A measuring device or a
  measurement methodology is Metered; an outage estimate or an estimate from crop
  water use is Estimated; no method stated, an alternative compliance plan,
  apportioned or under 10 acre-feet is Unknown. A delivery with no record behind
  it (a use area's own delivery, or a share written before shares named their
  point) is Unknown.

Crop ET, effective precipitation, pumped water not consumed, balance, available
and remaining carry no pill. Where a figure holds two or more kinds it becomes one
line per kind and the lines add exactly to the figure shown.

The district is ``tests.ledger_districts.build_d1`` plus more use areas, each a
different case. Every expected figure is a literal worked with a calculator from
the inputs below, never recomputed in a test.

Groundwater, WY 2024-2025 (July to September 2025):

* F1, F2 (account A): meter readings, 70.0000 + 35.0000 = 105.0000. F1 also has a
  zero-amount ``calculated`` row beside its readings (the MER-APN-039 shape).
* F3, F4 (account B): no meter. Crop water use over efficiency charges
  66.6667 and 50.0000 = 116.6667.
* F5 (account M): July estimated 26.6667 (20 AF of crop use over 0.75), August
  metered 4.0000, and a July share of 3.0000 written with no point named.
* F6 (account W): a September meter reading of 9.0000 that the calculation wrote
  by dividing a shared well's reading (its description starts with
  ``WELL_METER_SHARE_WORDS``).
* F7 (account O): a typed August entry of 5.0000.

Surface, July 2025 unless named; every point has no canal losses and divides by
the shares entered:

* S1 (account S1): Device Canal serves S1 alone; its record, 12.5000 by a
  measuring device.
* S2 (account S2): its own August delivery record, 7.2500.
* S3 (account S3): Outage Canal serves S3 alone; its record, 8.0000, an outage
  estimate.
* S4 (account X4) and S5 (no account): Mixed Canal serves both at 0.5 each. Two
  July records, 30.0000 by a measuring device on the 1st and 10.0000 with no
  method on the 15th, so S4 receives 15.0000 + 5.0000 = 20.0000 and that share
  splits 30 : 10 by volume, Metered 15.0000 and Unknown 5.0000.
* S6 (account S6): Old Canal's August record, 6.0000, estimated from crop water
  use (a record only a finalized year still holds), with its share written by
  hand after the runs.

The Dashboard therefore reads
Surface 56.75 = 27.50 Metered + 14.00 Estimated + 15.25 Unknown and
Groundwater 266.33 = 118.00 Metered + 143.33 Estimated + 5.00 Unknown.
The group's zone (F1 to F7) reads Used 266.33 the same way.
"""
import re
from decimal import Decimal as D
from html.parser import HTMLParser

import pytest
from django.test import Client
from django.urls import reverse

from accounting.management.commands.run_calculations import WELL_METER_SHARE_WORDS
from accounting.models import ReportingPeriod, WaterAccount, WaterAccountParcel
from accounting.services import supply_kind_terms
from core.models import User
from geography.views import _zone_budget_captions
from parcels.models import ParcelLedger
from surface.models import DiversionRecord, WaterRight, WaterRightType

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
def _record(point, month, af, method):
    return DiversionRecord.objects.create(
        point_of_diversion=point, reporting_period=ld.period_of(month), month=month,
        volume_acre_feet=D(af), returned_af=D("0"), diversion_type="direct_use", method=method)


def _right(right_id):
    return WaterRight.objects.create(
        right_id=right_id, right_type=WaterRightType.objects.get(code="POST14"), holder_name="Pill district",
        face_value_acre_feet=D("500.0000"), direct_season_start_month=4, direct_season_start_day=1,
        direct_season_end_month=10, direct_season_end_day=31)


def _point(name, right, served):
    return ld.make_point(name, -120.42, 37.15, right, "0", "0", "0", served)


def _share_row(parcel, date, amount, point):
    """A share written by hand: ``point`` None is a share from before shares named their point."""
    row = ld.ledger(parcel, date, amount, "surface_diversion", "SW", "headgate share (test input)")
    ParcelLedger.objects.filter(pk=row.pk).update(
        divided_from_headgate=True, divided_from_point_pk=point.pk if point else None)
    return row


def _own_delivery(parcel, date, amount):
    return ld.ledger(parcel, date, amount, "surface_diversion", "SW", "own delivery (test input)")


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
    f7 = ld.add_field("F7", 100, None, None, [gsa], -120.44, 37.2, [], ld.make_well("W7P", -120.395, 37.21))
    s = {}
    for i, name in enumerate(("S1", "S2", "S3", "S4", "S5", "S6")):
        s[name] = ld.add_field(name, 100, "Alfalfa", None, [], -120.43 + i * 0.01, 37.2, [{"2025-07": 30.48}])
    right = _right("RP")
    _record(_point("Device Canal", right, [(s["S1"], "1")]), JUL, "12.5000", "device")
    _record(_point("Outage Canal", right, [(s["S3"], "1")]), JUL, "8.0000", "outage_estimate")
    mixed = _point("Mixed Canal", right, [(s["S4"], "0.5"), (s["S5"], "0.5")])
    _record(mixed, JUL, "30.0000", "device")
    _record(mixed, JUL.replace(day=15), "10.0000", "")
    for month in ("2025-07", "2025-08", "2025-09"):
        ld.run_months([month])
    # Hand-entered rows go in after the runs, so no month's recalculation can replace them.
    ld.ledger(f5, AUG, "-4.0000", "meter_reading", "GW", "meter reading entered on the use area")
    _share_row(f5, JUL, "-3.0000", None)
    ld.ledger(f6, SEP, "-9.0000", "meter_reading", "GW",
              f"{WELL_METER_SHARE_WORDS} W6P pumped 18.0000 AF this month, this use area's share is 50%")
    ld.ledger(f7, AUG, "-5.0000", "manual_entry", "GW", "typed on the ledger (test input)")
    ld.ledger(d1["F1"], AUG, "0", "calculated", "GW", "calculated, nothing to estimate")
    _own_delivery(s["S2"], AUG, "-7.2500")
    # A run deletes a record estimated from crop water use, so this one goes in after them.
    old = _point("Old Canal", right, [(s["S6"], "1")])
    _record(old, AUG, "6.0000", "estimated_from_use")
    _share_row(s["S6"], AUG, "-6.0000", old)
    accounts = {
        "A": WaterAccount.objects.get(account_number="D1-A"),
        "B": WaterAccount.objects.get(account_number="D1-B"),
        "M": _account("Mixed account", "M-1", f5),
        "W": _account("Well share account", "W-1", f6),
        "O": _account("Typed entry account", "O-1", f7),
        "S1": _account("Device account", "S-1", s["S1"]),
        "S2": _account("Own delivery account", "S-2", s["S2"]),
        "S3": _account("Outage account", "S-3", s["S3"]),
        "X4": _account("Two methods account", "S-4", s["S4"]),
        "S6": _account("Old estimate account", "S-6", s["S6"]),
    }
    return {**d1, "F5": f5, "F6": f6, "F7": f7, **s, "accounts": accounts}


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


def _heading(group):
    """The words of the group's "How measured" heading, or None."""
    found = group.select(".kind-heading")
    assert len(found) <= 1, "one heading per breakdown"
    return _words(found[0]) if found else None


# ---------------------------------------------------------------- (a) the groundwater rule
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


def test_a_shared_wells_divided_reading_is_metered(district, client):
    page = _account_page(client, district["accounts"]["W"])
    assert _supply_lines(page, "Groundwater") == [("Metered", "9.00")]


def test_a_typed_groundwater_entry_is_unknown(district, client):
    page = _account_page(client, district["accounts"]["O"])
    assert _supply_lines(page, "Groundwater") == [("Unknown", "5.00")]


# ---------------------------------------------------------------- (a) the surface rule
def test_a_share_of_a_device_record_is_metered(district, client):
    page = _account_page(client, district["accounts"]["S1"])
    assert _supply_lines(page, "Surface") == [("Metered", "12.50")]


def test_a_share_of_an_outage_estimate_is_estimated(district, client):
    page = _account_page(client, district["accounts"]["S3"])
    assert _supply_lines(page, "Surface") == [("Estimated", "8.00")]


def test_a_share_of_a_record_estimated_from_crop_water_use_is_estimated(district, client):
    page = _account_page(client, district["accounts"]["S6"])
    assert _supply_lines(page, "Surface") == [("Estimated", "6.00")]


def test_a_share_of_a_month_with_two_methods_splits_by_the_records_volumes(district, client):
    # 20.0000 received; the month's records are 30 by device and 10 with no method.
    page = _account_page(client, district["accounts"]["X4"])
    assert _supply_lines(page, "Surface") == [("Metered", "15.00"), ("Unknown", "5.00")]


def test_a_use_areas_own_delivery_with_no_record_behind_it_is_unknown(district, client):
    page = _account_page(client, district["accounts"]["S2"])
    assert _supply_lines(page, "Surface") == [("Unknown", "7.25")]


def test_a_share_that_names_no_point_is_unknown(district, client):
    page = _account_page(client, district["accounts"]["M"])
    assert _supply_lines(page, "Surface") == [("Unknown", "3.00")]


@pytest.mark.parametrize(("method", "kind"), [
    ("device", "metered"),
    ("methodology", "metered"),
    ("outage_estimate", "estimated"),
    ("estimated_from_use", "estimated"),
    ("", "unknown"),
    ("alternative_compliance", "unknown"),
    ("apportioned", "unknown"),
    ("below_threshold", "unknown"),
])
def test_every_measurement_method_gives_its_kind(method, kind):
    ld.seed_reference()
    parcel = ld.add_field("P1", 100, None, None, [], -120.5, 37.2, [])
    point = _point("Method Canal", _right("RM"), [(parcel, "1")])
    _record(point, JUL, "4.0000", method)
    _share_row(parcel, JUL, "-4.0000", point)
    period = ReportingPeriod.objects.get(name=WY)
    assert supply_kind_terms([parcel.pk], period)["surface"] == [(kind, D("4.0000"))]


def test_every_method_a_diversion_record_offers_has_a_kind():
    from accounting.services import SURFACE_METHOD_KINDS

    methods = {code for code, _ in DiversionRecord.METHOD_CHOICES} | {""}
    assert set(SURFACE_METHOD_KINDS) == methods
    assert set(SURFACE_METHOD_KINDS.values()) == {"metered", "estimated", "unknown"}


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
    assert _supply_lines(page, "Surface") == [("Estimated", "14.00"), ("Metered", "27.50"), ("Unknown", "15.25")]
    assert _supply_lines(page, "Groundwater") == [("Estimated", "143.33"), ("Metered", "118.00"), ("Unknown", "5.00")]


def test_the_dashboard_lines_add_exactly_to_the_figures_in_the_panel(district, client):
    page = _dashboard(client)
    rows = [_row(r) for r in _group(page, "Supplies by source").select(".budget-breakdown-row")]
    total = _seg(page, "Supplies").select_one(".budget-seg-value").get_text(strip=True).removesuffix("AF")
    assert total == "323.08"
    assert sum(_money(r["figure"]) for r in rows) == _money(total)


def test_the_dashboard_supplies_carry_the_how_measured_heading(district, client):
    group = _group(_dashboard(client), "Supplies by source")
    assert _heading(group) == "How measured"
    html = str(group)
    assert html.index("kind-heading") < html.index("budget-breakdown-row")


def test_the_dashboard_puts_a_pill_on_no_other_line(district, client):
    page = _dashboard(client)
    panel = _group(page, "Supplies by source").find_parent(class_="budget-panel")
    assert len(panel.select(".kind-pill")) == 6  # three Surface lines and three Groundwater lines
    precip = [_row(r) for r in _group(page, "Supplies by source").select(".budget-breakdown-row")
              if _row(r)["label"] == "Effective precipitation"]
    assert [(r["pills"], r["figure"]) for r in precip] == [([], "0.00")]
    for title in ("Uses by destination", "Estimate coverage", "Balance by account"):
        assert _group(page, title).select(".kind-pill") == []
        assert _heading(_group(page, title)) is None
    for label in ("Uses", "Balance"):
        assert _seg(page, label).select(".kind-pill") == []


def test_no_pill_reads_headgate_or_well_share(district, client):
    for page in (_dashboard(client), _account_page(client, district["accounts"]["M"]),
                 _zone_page(client, district["gsa"]), _use_area_page(client, district["F5"])):
        words = {_words(p) for p in page.select(".kind-pill")}
        assert words <= {"Metered", "Estimated", "Unknown"}, words
        classes = {c for p in page.select(".kind-pill") for c in p.classes}
        assert classes <= {"kind-pill", "kind-pill--metered", "kind-pill--estimated", "kind-pill--unknown"}, classes


def test_the_account_page_puts_a_pill_on_no_other_line(district, client):
    page = _account_page(client, district["accounts"]["M"])
    group = _group(page, "Supplies by source")
    panel = group.find_parent(class_="budget-panel")
    assert len(panel.select(".kind-pill")) == 3  # one Surface line and two Groundwater lines
    assert _heading(group) == "How measured"
    assert _group(page, "Uses by destination").select(".kind-pill") == []
    assert _seg(page, "Balance").select(".kind-pill") == []


def test_the_zone_used_cell_lists_its_kinds_as_lines_with_pills(district, client):
    page = _zone_page(client, district["gsa"])
    used = _seg(page, "Used")
    lines = sorted((_words(r.select_one(".kind-pill")), r.find("b").get_text(strip=True))
                   for r in used.select(".budget-breakdown-row") if r.select_one(".kind-pill"))
    assert lines == [("Estimated", "143.33"), ("Metered", "118.00"), ("Unknown", "5.00")]
    assert used.select_one(".budget-seg-value").get_text(strip=True).removesuffix("AF") == "266.33"
    assert _heading(used) == "How measured"


def test_the_zone_available_and_remaining_cells_carry_no_pill(district, client):
    page = _zone_page(client, district["gsa"])
    for label in ("Available", "Remaining"):
        assert _seg(page, label).select(".kind-pill") == []
        assert _heading(_seg(page, label)) is None


def _lead_cells(page):
    lead = page.select_one(".statement-lead")
    cells = {}
    for cell in lead.find_all("div", recursive=False):
        label = cell.select_one(".budget-seg-label").get_text(strip=True)
        cells[label] = cell
    return cells


def _cell_pills(cell):
    return sorted(_words(p) for p in cell.select(".kind-pill"))


def _cell_value(cell):
    return cell.select_one(".budget-seg-value").get_text(strip=True)


def _how_measured(cell):
    """The words of the cell's pill line: "How measured" and then its pills, or None."""
    line = cell.select_one(".figure-kind")
    return _words(line) if line is not None else None


def test_a_metered_use_area_page_reads_how_measured_metered(district, client):
    cells = _lead_cells(_use_area_page(client, district["F1"]))
    assert _cell_value(cells["Groundwater extraction"]) == "70.00AF"
    assert _how_measured(cells["Groundwater extraction"]) == "How measured Metered"
    # The pill line sits above the link note to the well.
    html = str(cells["Groundwater extraction"])
    assert html.index("kind-pill") < html.index("prose-link")
    # A figure with no water has no pill and no words before one.
    assert _how_measured(cells["Surface water delivered"]) is None


def test_an_estimated_use_area_page_reads_how_measured_estimated(district, client):
    cells = _lead_cells(_use_area_page(client, district["F4"]))
    assert _cell_value(cells["Groundwater extraction"]) == "50.00AF"
    assert _how_measured(cells["Groundwater extraction"]) == "How measured Estimated"


def test_a_use_area_page_with_both_kinds_shows_both_pills_after_one_heading(district, client):
    cells = _lead_cells(_use_area_page(client, district["F5"]))
    assert _cell_value(cells["Groundwater extraction"]) == "30.67AF"
    assert _cell_pills(cells["Groundwater extraction"]) == ["Estimated", "Metered"]
    assert _how_measured(cells["Groundwater extraction"]).count("How measured") == 1
    assert _cell_value(cells["Surface water delivered"]) == "3.00AF"
    assert _how_measured(cells["Surface water delivered"]) == "How measured Unknown"


@pytest.mark.parametrize(("key", "figure", "pills"), [
    ("S1", "12.50AF", ["Metered"]),
    ("S2", "7.25AF", ["Unknown"]),
    ("S3", "8.00AF", ["Estimated"]),
    ("S4", "20.00AF", ["Metered", "Unknown"]),
    ("S6", "6.00AF", ["Estimated"]),
])
def test_a_use_area_page_names_how_its_delivery_was_measured(district, client, key, figure, pills):
    cells = _lead_cells(_use_area_page(client, district[key]))
    assert _cell_value(cells["Surface water delivered"]) == figure
    assert _cell_pills(cells["Surface water delivered"]) == pills


def test_a_use_area_page_puts_no_pill_on_crop_et_or_effective_precipitation(district, client):
    for key in ("F1", "F4", "F5", "S1"):
        cells = _lead_cells(_use_area_page(client, district[key]))
        assert _cell_pills(cells["Crop ET"]) == [], key
        assert _cell_pills(cells["Effective precipitation"]) == [], key
        assert _how_measured(cells["Crop ET"]) is None, key


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
