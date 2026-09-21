# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-180 D6: the curtailment matching rule (146-02 Task 4).

RED first (quoted in `146-02-EVIDENCE.md` Task 4 step 1): on the unfixed tree
(`surface/views.py:820-826`, `priority_date_cutoff__gte=priority_date`, no
watershed term), the real shape-1 instance flagged A005724 -- the SENIOR
right, priority 1927 against a 1930 cutoff -- and left A007012, the JUNIOR
right (priority 1931), unflagged. That is backwards from every State Water
Board curtailment order, and this module's fixture is that same observation:
four rights, tested here against the rule this task derives from an order's
own text.

The direction is grounded in `146-02-EVIDENCE.md` Task 4 section 2: the State
Water Board's August 20, 2021 order imposing curtailment in the
Sacramento-San Joaquin Delta watershed
(https://www.waterboards.ca.gov/drought/delta/docs/082021_order_sm.pdf)
curtails, at item 3, pre-1914 claims in the Sacramento River watershed and
Legal Delta "with a priority date of 1883 or later" -- the JUNIOR side of a
cutoff, not the senior side the old filter used.

The fixture matches `146-02-EVIDENCE.md` Task 4 step 1's before-observation
table exactly: A001885 (no priority date, Merced River), A005724 (priority
1927-10-17, Owens Creek), A006111 (no priority date, Arena Spillway), A007012
(priority 1931-07-20, Arena Spillway), all on watershed "SAN JOAQUIN VALLEY
FLOOR", against order TEST-2026-01 (watershed MERCED RIVER, cutoff
1930-01-01) and a second order with a blank watershed and the same cutoff.
"""
from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse

from surface.curtailments import orders_that_may_apply
from surface.models import CurtailmentOrder
from tests.factories import WaterRightFactory, WaterRightTypeFactory
import factory
from django.contrib.auth.hashers import make_password

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"matchinguser{n}")
    email = factory.Sequence(lambda n: f"matchinguser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


@pytest.fixture
def right_type():
    return WaterRightTypeFactory(name="Post-1914 Appropriative", code="POST14X")


@pytest.fixture
def a001885(right_type):
    """No priority date, Merced River -- the same river TEST-2026-01 names."""
    return WaterRightFactory(
        right_id="A001885", right_type=right_type, source_name="MERCED RIVER",
        watershed="SAN JOAQUIN VALLEY FLOOR", priority_date=None,
    )


@pytest.fixture
def a005724(right_type):
    """Priority 1927-10-17, Owens Creek -- senior to the 1930 cutoff."""
    return WaterRightFactory(
        right_id="A005724", right_type=right_type, source_name="OWENS CREEK",
        watershed="SAN JOAQUIN VALLEY FLOOR", priority_date=date(1927, 10, 17),
    )


@pytest.fixture
def a006111(right_type):
    """No priority date, Arena Spillway."""
    return WaterRightFactory(
        right_id="A006111", right_type=right_type, source_name="ARENA SPILLWAY",
        watershed="SAN JOAQUIN VALLEY FLOOR", priority_date=None,
    )


@pytest.fixture
def a007012(right_type):
    """Priority 1931-07-20, Arena Spillway -- junior to the 1930 cutoff."""
    return WaterRightFactory(
        right_id="A007012", right_type=right_type, source_name="ARENA SPILLWAY",
        watershed="SAN JOAQUIN VALLEY FLOOR", priority_date=date(1931, 7, 20),
    )


@pytest.fixture
def merced_order():
    """TEST-2026-01: watershed MERCED RIVER, cutoff 1930-01-01."""
    return CurtailmentOrder.objects.create(
        order_id="TEST-2026-01",
        title="Test order for the 146-02 observation",
        effective_date=date(2026, 1, 1),
        watershed="MERCED RIVER",
        priority_date_cutoff=date(1930, 1, 1),
        status="active",
    )


@pytest.fixture
def blank_watershed_order():
    """A second order, same cutoff, no named watershed."""
    return CurtailmentOrder.objects.create(
        order_id="TEST-2026-03",
        title="Test order with no named watershed",
        effective_date=date(2026, 1, 1),
        watershed="",
        priority_date_cutoff=date(1930, 1, 1),
        status="active",
    )


# ---------------------------------------------------------------------------
# The four branches the plan names
# ---------------------------------------------------------------------------


def test_junior_right_is_flagged(a007012, blank_watershed_order):
    """A007012 (1931) is junior to the 1930 cutoff; the blank-watershed order
    reaches it regardless of its watershed."""
    matched, unmatched = orders_that_may_apply(a007012)
    assert blank_watershed_order in matched
    assert unmatched == []


def test_senior_right_is_not_flagged(a005724, merced_order, blank_watershed_order):
    """A005724 (1927) predates the 1930 cutoff -- backwards from the old
    filter, which flagged exactly this right."""
    matched, unmatched = orders_that_may_apply(a005724)
    assert merced_order not in matched
    assert blank_watershed_order not in matched
    assert matched == []


def test_wrong_watershed_right_is_not_flagged(a007012, merced_order):
    """A007012 is junior to the cutoff but sits on Arena Spillway, not the
    Merced River TEST-2026-01 names, so that order does not reach it."""
    matched, unmatched = orders_that_may_apply(a007012)
    assert merced_order not in matched


def test_no_date_rights_are_listed_as_unmatched(a001885, a006111, merced_order, blank_watershed_order):
    """A001885 sits on the order's own named river (Merced) but carries no
    priority date, so it can never be matched, only listed as unmatched.
    A006111 (Arena Spillway) is unmatched only under the blank-watershed
    order, which reaches every watershed."""
    matched_1885, unmatched_1885 = orders_that_may_apply(a001885)
    assert matched_1885 == []
    assert merced_order in unmatched_1885
    assert blank_watershed_order in unmatched_1885

    matched_6111, unmatched_6111 = orders_that_may_apply(a006111)
    assert matched_6111 == []
    assert merced_order not in unmatched_6111  # Arena Spillway != Merced River
    assert blank_watershed_order in unmatched_6111


def test_expired_order_end_date_in_the_past_is_not_listed(a007012):
    expired = CurtailmentOrder.objects.create(
        order_id="TEST-2026-04",
        title="Expired order",
        effective_date=date(2020, 1, 1),
        end_date=date.today() - timedelta(days=1),
        watershed="",
        priority_date_cutoff=date(1930, 1, 1),
        status="active",
    )
    matched, unmatched = orders_that_may_apply(a007012)
    assert expired not in matched
    assert expired not in unmatched


def test_order_with_no_cutoff_matches_on_date_and_watershed_alone(a001885, a005724):
    """An order naming no cutoff at all reaches every priority date on its
    watershed (146-02-EVIDENCE.md's item 1: "All post-1914 appropriative
    water rights in the Delta watershed" -- no cutoff, a whole class)."""
    order = CurtailmentOrder.objects.create(
        order_id="TEST-2026-05",
        title="No-cutoff order",
        effective_date=date(2026, 1, 1),
        watershed="MERCED RIVER",
        priority_date_cutoff=None,
        status="active",
    )
    # a005724 is on Owens Creek, not Merced River -- still excluded by (b).
    matched_5724, _ = orders_that_may_apply(a005724)
    assert order not in matched_5724
    # a001885 has no priority date -- listed as unmatched, not matched, even
    # with no cutoff to test it against.
    matched_1885, unmatched_1885 = orders_that_may_apply(a001885)
    assert matched_1885 == []
    assert order in unmatched_1885


# ---------------------------------------------------------------------------
# The footer sentence, on the rendered page
# ---------------------------------------------------------------------------


def test_footer_sentence_present_on_the_rights_page(auth_client, a007012, blank_watershed_order):
    resp = auth_client.get(reverse("surface:detail", args=[a007012.pk]))
    content = resp.content.decode()
    assert "Curtailment orders that may apply" in content
    assert "order's own text governs; this list is a lookup by date and watershed" in content


def test_no_date_right_shows_the_unmatched_line_and_edit_link(auth_client, a001885, merced_order):
    resp = auth_client.get(reverse("surface:detail", args=[a001885.pk]))
    content = resp.content.decode()
    assert "cannot be matched: no priority date on record" in content.lower()
    assert reverse("surface:water_right_edit", args=[a001885.pk]) in content
