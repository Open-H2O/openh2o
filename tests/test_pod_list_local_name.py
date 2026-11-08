# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-368: the Surface Diversions list shows a point's local name first.

The first cell's link reads the local name with the state's name under it in
smaller grey text (``text-secondary text-sm``); a point with no local name shows
its name alone. The search also finds a local name. Placeholder: row 75 of
``152-03.1-ROWS.md``.

Test data is INVENTED: points X000001_01 ("North Headgate") and X000001_02
("South Headgate") of "Example Ditch Company", and X000002_01 with no local name.
"""
from html.parser import HTMLParser

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import PointOfDiversionFactory

pytestmark = pytest.mark.django_db

ROW_75 = "Name, local name or stream..."


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"podlistuser{n}")
    email = factory.Sequence(lambda n: f"podlistuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.fixture
def points(db):
    return {
        "north": PointOfDiversionFactory(name="X000001_01", local_name="North Headgate"),
        "south": PointOfDiversionFactory(name="X000001_02", local_name="South Headgate"),
        "plain": PointOfDiversionFactory(name="X000002_01", local_name=""),
    }


class _FirstCells(HTMLParser):
    """For each table-body row: the first cell's link text and its small grey lines."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_tbody = False
        self._cell = None  # None, or index of the td within the current row
        self._td_index = -1
        self._link = None
        self._small = []  # stack of [tag, text list] for text-secondary text-sm elements
        self._depth_in_cell = 0

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        if tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self.rows.append({"link": "", "small": [], "pk": None})
            self._td_index = -1
        elif tag == "td" and self._in_tbody:
            self._td_index += 1
            self._depth_in_cell = 0
        if self._in_tbody and self._td_index == 0 and self.rows:
            if tag == "a" and "data-table-link" in classes:
                self._link = []
            if {"text-secondary", "text-sm"} <= classes:
                self._small.append([tag, []])

    def handle_endtag(self, tag):
        if tag == "tbody":
            self._in_tbody = False
        if self._in_tbody and self._td_index == 0 and self.rows:
            if tag == "a" and self._link is not None:
                self.rows[-1]["link"] = " ".join("".join(self._link).split())
                self._link = None
            if self._small and self._small[-1][0] == tag:
                text = " ".join("".join(self._small.pop()[1]).split())
                self.rows[-1]["small"].append(text)

    def handle_data(self, data):
        if self._link is not None:
            self._link.append(data)
        for _, texts in self._small:
            texts.append(data)


def _first_cells(response):
    parser = _FirstCells()
    parser.feed(response.content.decode())
    return parser.rows


def _by_link(rows, text):
    matches = [r for r in rows if r["link"] == text]
    assert len(matches) == 1, f"expected one row whose link reads {text!r}, rows were {rows!r}"
    return matches[0]


@pytest.mark.parametrize("partial", [False, True], ids=["full-page", "htmx-partial"])
def test_a_point_with_a_local_name_leads_with_it_and_shows_the_state_name_under_it(
    auth_client, points, partial
):
    extra = {"HTTP_HX_REQUEST": "true"} if partial else {}
    rows = _first_cells(auth_client.get(reverse("surface:pod_list"), **extra))

    assert _by_link(rows, "North Headgate")["small"] == ["X000001_01"]
    assert _by_link(rows, "South Headgate")["small"] == ["X000001_02"]


@pytest.mark.parametrize("partial", [False, True], ids=["full-page", "htmx-partial"])
def test_a_point_without_one_leads_with_its_name_and_has_no_second_line(
    auth_client, points, partial
):
    extra = {"HTTP_HX_REQUEST": "true"} if partial else {}
    rows = _first_cells(auth_client.get(reverse("surface:pod_list"), **extra))

    assert _by_link(rows, "X000002_01")["small"] == []


@pytest.mark.parametrize("partial", [False, True], ids=["full-page", "htmx-partial"])
def test_searching_a_local_name_finds_that_point_and_not_the_other(auth_client, points, partial):
    extra = {"HTTP_HX_REQUEST": "true"} if partial else {}
    rows = _first_cells(auth_client.get(reverse("surface:pod_list"), {"q": "South"}, **extra))

    assert [r["link"] for r in rows] == ["South Headgate"]


def test_the_search_box_placeholder_is_row_75(auth_client, points):
    body = auth_client.get(reverse("surface:pod_list")).content.decode()

    assert f'placeholder="{ROW_75}"' in body
