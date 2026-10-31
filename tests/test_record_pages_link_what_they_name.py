# SPDX-License-Identifier: AGPL-3.0-or-later
"""151.8-02: a record page links the records it names (no dead ends).

A reader who sees "Halvern Valley GSA" on a use area page, or "Alder Ditch
Headgate" in a water right's diversion records, expects the name to open that
record. Each test renders the real page through the test client and parses the
HTML with the stdlib parser (this suite has no BeautifulSoup), then asserts the
record's name is the text of an `<a>` whose href is `reverse()` of the record's
own page. The decided list is
`.planning/phases/151.8-finding-your-way/151.8-work/dead-ends-measured.md`:

- the use area page links each zone it belongs to, for a viewer too;
- the recharge site page links its zone and its water account inside the
  sentences that name them, and the sentences still read the same;
- the water right page links the point of diversion in each diversion record
  and in the "Recorded, by point of diversion" breakdown, one row per point
  even when two points share a name, and costs no extra query per row;
- the sampling point and sample result pages link the water system's name
  (never its PWSID) to the Water Systems page;
- Water Systems step 1 offers "Refresh from EPA's record" in place of "Add
  another system", a link that led to a refusal, and the add-a-system result
  drops the same button.

Water years are not tested here: whether they link is still an open question.
"""
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounting.models import ReportingPeriod
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelZoneFactory,
    PointOfDiversionFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    SampleResultFactory,
    SamplingPointFactory,
    WaterAccountFactory,
    WaterRightFactory,
    WaterSystemFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

_VOID = {"br", "hr", "img", "input", "meta", "link", "source", "col", "area", "base", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []  # _Node or str

    def text(self):
        return "".join(
            c if isinstance(c, str) else c.text() for c in self.children
        )

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, _Node):
                yield from c.walk()

    def inside_anchor(self):
        node = self.parent
        while node is not None:
            if node.tag == "a":
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {}, None)
        self._cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self._cur)
        self._cur.children.append(node)
        if tag not in _VOID:
            self._cur = node

    def handle_startendtag(self, tag, attrs):
        self._cur.children.append(_Node(tag, attrs, self._cur))

    def handle_endtag(self, tag):
        node = self._cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._cur = node.parent

    def handle_data(self, data):
        self._cur.children.append(data)


def _parse(html):
    tree = _Tree()
    tree.feed(html)
    return tree.root


def _anchors(root):
    return [n for n in root.walk() if n.tag == "a"]


def _squash(text):
    return " ".join(text.split())


def _links_to(root, name, url):
    """The anchors whose text is exactly ``name`` and whose href is ``url``."""
    return [
        a
        for a in _anchors(root)
        if _squash(a.text()) == name and a.attrs.get("href") == url
    ]


def _field_value(root, label):
    """The `.field-value` div of the `.field-group` whose label reads ``label``."""
    for group in root.walk():
        classes = (group.attrs.get("class") or "").split()
        if group.tag != "div" or "field-group" not in classes:
            continue
        kids = [c for c in group.children if isinstance(c, _Node)]
        label_node = next(
            (k for k in kids if "field-label" in (k.attrs.get("class") or "").split()),
            None,
        )
        if label_node is not None and _squash(label_node.text()) == label:
            for k in kids:
                if "field-value" in (k.attrs.get("class") or "").split():
                    return k
    raise AssertionError(f"no field {label!r} on the page")


_n = 0


def _client(read_only=False):
    global _n
    _n += 1
    user = User.objects.create_user(
        username=f"namelinks{_n}",
        email=f"namelinks{_n}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        read_only=read_only,
    )
    client = Client()
    client.force_login(user)
    return client


def _get(client, url_name, *args):
    response = client.get(reverse(url_name, args=args))
    assert response.status_code == 200
    return _parse(response.content.decode())


# -- 1. use area page ---------------------------------------------------------


class TestUseAreaPageLinksItsZones:
    def _parcel_in_zone(self):
        zone = ZoneFactory(name="Halvern Valley GSA")
        parcel = ParcelFactory()
        ParcelZoneFactory(parcel=parcel, zone=zone)
        return parcel, zone

    def test_zone_membership_name_opens_the_zone(self):
        parcel, zone = self._parcel_in_zone()
        page = _get(_client(), "parcels:detail", parcel.pk)
        url = reverse("geography:zone_detail", args=[zone.pk])
        assert len(_links_to(page, "Halvern Valley GSA", url)) == 1

    def test_a_viewer_sees_the_same_link(self):
        parcel, zone = self._parcel_in_zone()
        page = _get(_client(read_only=True), "parcels:detail", parcel.pk)
        url = reverse("geography:zone_detail", args=[zone.pk])
        assert len(_links_to(page, "Halvern Valley GSA", url)) == 1


# -- 2. recharge site page ----------------------------------------------------


class TestRechargeSitePageLinksZoneAndAccount:
    ZONE_SENTENCE = "Recharge here is recorded in the basin recharge pool of Halvern Valley GSA."
    ACCOUNT_SENTENCE = "Recharge here is credited to Halvern Irrigation District."

    def _site(self):
        zone = ZoneFactory(name="Halvern Valley GSA")
        account = WaterAccountFactory(name="Halvern Irrigation District")
        site = RechargeSiteFactory(zone=zone, water_account=account)
        return site, zone, account

    def test_zone_name_in_its_sentence_opens_the_zone(self):
        site, zone, _ = self._site()
        page = _get(_client(), "recharge:detail", site.pk)
        value = _field_value(page, "Zone")
        assert _squash(value.text()) == self.ZONE_SENTENCE
        url = reverse("geography:zone_detail", args=[zone.pk])
        links = [
            a for a in _anchors(value)
            if _squash(a.text()) == "Halvern Valley GSA" and a.attrs.get("href") == url
        ]
        assert len(links) == 1

    def test_account_name_in_its_sentence_opens_the_account(self):
        site, _, account = self._site()
        page = _get(_client(), "recharge:detail", site.pk)
        value = _field_value(page, "Credited to")
        assert _squash(value.text()) == self.ACCOUNT_SENTENCE
        url = reverse("accounting:account_detail", args=[account.pk])
        links = [
            a for a in _anchors(value)
            if _squash(a.text()) == "Halvern Irrigation District"
            and a.attrs.get("href") == url
        ]
        assert len(links) == 1

    def test_a_site_with_neither_keeps_its_plain_sentences(self):
        site = RechargeSiteFactory(zone=None, water_account=None)
        page = _get(_client(), "recharge:detail", site.pk)
        zone_value = _field_value(page, "Zone")
        account_value = _field_value(page, "Credited to")
        assert _squash(zone_value.text()) == (
            "This site has no zone, so recharge here is not deposited to a basin recharge pool."
        )
        assert _squash(account_value.text()) == (
            "Recharge here is not credited to a water account."
        )
        assert _anchors(zone_value) == []
        assert _anchors(account_value) == []


# -- 3 and 4. water right page ------------------------------------------------

_WY = dict(name="WY 2025-2026", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30))


def _right_with_records(points, months_each):
    """A right with one record per point per month, all in one water year.

    The right carries a face value: the "Recorded, by point of diversion" rows
    draw only in the face-value panel.
    """
    right = WaterRightFactory(face_value_acre_feet=Decimal("1000.00"))
    period = ReportingPeriod.objects.filter(name=_WY["name"]).first() or ReportingPeriodFactory(**_WY)
    made = []
    for name in points:
        pod = PointOfDiversionFactory(water_right=right, name=name)
        made.append(pod)
        for i in range(months_each):
            month = date(2025 + (9 + i) // 12, (9 + i) % 12 + 1, 1)
            DiversionRecordFactory(
                point_of_diversion=pod,
                reporting_period=period,
                month=month,
                volume_acre_feet=Decimal("10.0000"),
            )
    return right, made


class TestWaterRightPageLinksItsPoints:
    def test_each_diversion_record_row_links_its_own_point(self):
        right, (north, south) = _right_with_records(
            ["Alder Ditch Headgate", "Birch Creek Headgate"], 2
        )
        page = _get(_client(), "surface:detail", right.pk)
        for pod in (north, south):
            url = reverse("surface:pod_detail", args=[pod.pk])
            cells = [
                a for a in _anchors(page)
                if a.attrs.get("href") == url
                and _squash(a.text()) == pod.name
                and a.parent.tag == "td"
            ]
            # two monthly records per point, each row's cell links that point
            assert len(cells) == 2, pod.name

    def test_by_point_breakdown_links_each_point(self):
        right, (north, south) = _right_with_records(
            ["Alder Ditch Headgate", "Birch Creek Headgate"], 2
        )
        page = _get(_client(), "surface:detail", right.pk)
        rows = [
            n for n in page.walk()
            if n.tag == "div" and "budget-breakdown-row" in (n.attrs.get("class") or "").split()
        ]
        assert len(rows) == 2
        for pod, row in zip((north, south), rows):
            url = reverse("surface:pod_detail", args=[pod.pk])
            assert len(_links_to(row, pod.name, url)) == 1

    def test_two_points_sharing_a_name_get_two_rows_each_linked_to_its_own_page(self):
        right, (first, second) = _right_with_records(["Shared Headgate", "Shared Headgate"], 1)
        page = _get(_client(), "surface:detail", right.pk)
        rows = [
            n for n in page.walk()
            if n.tag == "div" and "budget-breakdown-row" in (n.attrs.get("class") or "").split()
        ]
        assert len(rows) == 2
        hrefs = sorted(
            a.attrs.get("href") for row in rows for a in _anchors(row)
            if _squash(a.text()) == "Shared Headgate"
        )
        assert hrefs == sorted(
            reverse("surface:pod_detail", args=[p.pk]) for p in (first, second)
        )

    def test_more_diversion_records_cost_no_more_queries(self):
        client = _client()
        names = ["Alder Ditch Headgate", "Birch Creek Headgate"]
        few_right, _ = _right_with_records(names, 1)
        many_right, _ = _right_with_records(names, 6)
        # a warm-up render of each so one-time caches do not count against either run
        client.get(reverse("surface:detail", args=[few_right.pk]))
        client.get(reverse("surface:detail", args=[many_right.pk]))
        with CaptureQueriesContext(connection) as few:
            assert client.get(reverse("surface:detail", args=[few_right.pk])).status_code == 200
        with CaptureQueriesContext(connection) as many:
            assert client.get(reverse("surface:detail", args=[many_right.pk])).status_code == 200
        assert len(many) <= len(few), (len(few), len(many))


# -- 5 and 6. drinking pages --------------------------------------------------


class TestDrinkingPagesLinkTheirWaterSystem:
    def _point(self):
        system = WaterSystemFactory(name="City of Halvern", pwsid="CA1912345")
        from tests.factories import SystemFacilityFactory

        facility = SystemFacilityFactory(system=system)
        return SamplingPointFactory(facility=facility), system

    def test_sampling_point_links_the_system_name_but_not_the_pwsid(self):
        point, system = self._point()
        page = _get(_client(), "drinking:sampling_point_detail", point.pk)
        value = _field_value(page, "Water system")
        url = reverse("drinking:overview")
        assert len(_links_to(value, "City of Halvern", url)) == 1
        assert "CA1912345" in value.text()
        assert not any("CA1912345" in a.text() for a in _anchors(value))

    def test_sample_result_links_the_system_name_and_leaves_the_pwsid_plain(self):
        point, system = self._point()
        from tests.factories import SampleEventFactory

        result = SampleResultFactory(event=SampleEventFactory(sampling_point=point))
        page = _get(_client(), "drinking:result_detail", result.pk)
        url = reverse("drinking:overview")
        value = _field_value(page, "Water system")
        assert len(_links_to(value, "City of Halvern", url)) == 1
        pwsid_value = _field_value(page, "PWSID")
        assert "CA1912345" in pwsid_value.text()
        assert _anchors(pwsid_value) == []


# -- 7 and 8. the link that led to a refusal ----------------------------------


class TestWaterSystemsStopsOfferingAnotherSystem:
    def test_writer_sees_refresh_not_add_another(self):
        WaterSystemFactory()
        response = _client().get(reverse("drinking:overview"))
        assert response.status_code == 200
        html = response.content.decode()
        assert "Add another system" not in html
        page = _parse(html)
        url = reverse("drinking:onboard")
        refresh = [
            a for a in _anchors(page)
            if _squash(a.text()).removesuffix("→").strip() == "Refresh from EPA's record"
            and a.attrs.get("href") == url
        ]
        assert len(refresh) == 1

    def test_viewer_sees_no_refresh_link(self):
        WaterSystemFactory()
        response = _client(read_only=True).get(reverse("drinking:overview"))
        assert response.status_code == 200
        page = _parse(response.content.decode())
        assert not [
            a for a in _anchors(page) if "Refresh from EPA" in a.text()
        ]
        assert "Add another system" not in response.content.decode()

    def test_add_a_system_result_drops_add_another_and_keeps_the_next_steps(self):
        from types import SimpleNamespace

        system = WaterSystemFactory(name="City of Halvern", pwsid="CA1912345")
        result = SimpleNamespace(
            system=system,
            created=True,
            facilities_created=3,
            facilities_updated=0,
            skipped=[],
            warnings=[],
        )
        html = render_to_string(
            "drinking/partials/_onboard_result.html",
            {"result": result, "pwsid": system.pwsid, "epa_facility_count": 3},
        )
        assert "Add another system" not in html
        assert "Add sampling points" in html
        assert "View the water system" in html
