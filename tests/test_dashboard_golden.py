# SPDX-License-Identifier: AGPL-3.0-or-later
"""Golden-HTML contract for the overview dashboard.

Same gate as `tests/test_nav_golden.py`, aimed at the other surface 77-02
touches. Task 4 adds a registry-driven card area to the dashboard so Phase 78's
`drinking` module can contribute a tile without anyone editing this template.
Under the default module list that area is empty — no module ships a dashboard
card today — so the rendered dashboard must not move.

The fixture is captured through the real view with the real template chain
(`accounting/dashboard.html` -> `_dashboard_content.html` -> the partials), so
it covers the whole rendered page and not just an isolated fragment. Only the
`<main>` region is compared: the surrounding shell carries the sidebar, which
already has its own fixtures, plus a CSRF token and a build stamp that change
between runs.

As with the nav fixtures: if this fails, fix the template. Regenerating
(`GOLDEN_UPDATE=1`) is for a deliberate, reviewed dashboard change only.
"""
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterTypeFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"golden{n}")
    email = factory.Sequence(lambda n: f"golden{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("GOLDEN_UPDATE") == "1"

_BETWEEN_TAGS = re.compile(r">\s+<")
_MAIN = re.compile(r"<main\b.*?</main>", re.S)


def normalize(html: str) -> str:
    return _BETWEEN_TAGS.sub("><", html.strip())


def main_region(html: str) -> str:
    match = _MAIN.search(html)
    assert match, "No <main> element in the rendered dashboard"
    return normalize(match.group(0))


@pytest.fixture
def dashboard_html(db):
    """Render the dashboard over a small, fully deterministic dataset.

    Deliberately builds the populated path — allocations present, one account,
    one zone — because the empty-state branch renders none of the structure this
    fixture is meant to protect.
    """
    period = ReportingPeriodFactory(
        name="Water Year 2025-2026",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )
    zone = ZoneFactory(name="Golden Fixture Zone")
    water_type = WaterTypeFactory()
    parcel = ParcelFactory()
    ParcelZoneFactory(parcel=parcel, zone=zone)
    account = WaterAccountFactory(account_number="GF-0001", name="Golden Fixture Account")
    WaterAccountParcelFactory(water_account=account, parcel=parcel)
    AllocationPlanFactory(
        zone=zone,
        water_type=water_type,
        reporting_period=period,
        allocation_acre_feet=Decimal("100.0000"),
    )

    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard") + f"?period={period.pk}")
    assert response.status_code == 200
    return response.content.decode()


def test_dashboard_main_region_unchanged(dashboard_html):
    fixture = GOLDEN_DIR / "dashboard_main.html"
    actual = main_region(dashboard_html)

    if UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        fixture.write_text(actual + "\n", encoding="utf-8")
        return

    assert fixture.exists(), (
        f"Missing golden fixture {fixture}. Generate it with GOLDEN_UPDATE=1 "
        f"against the UNMODIFIED dashboard."
    )
    assert actual == fixture.read_text(encoding="utf-8").strip(), (
        "The dashboard drifted from its golden fixture. Fix the template — do "
        "NOT edit the fixture."
    )


def test_dashboard_context_exposes_module_cards(db):
    """The card list reaches the template, even though it is empty today.

    Asserted on the context rather than the HTML on purpose: the wrapper is
    deliberately not rendered when there are no cards, so the default page stays
    byte-identical. That means the rendered page cannot distinguish "wired up
    and empty" from "never wired up" — this can.
    """
    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard"))
    assert response.status_code == 200
    assert "module_dashboard_cards" in response.context
    assert list(response.context["module_dashboard_cards"]) == []


def test_dashboard_renders_a_supplied_module_card():
    """Prove the loop actually renders, without waiting for Phase 78.

    Feeds the template a real existing partial through the same context key a
    ModuleSpec would populate. If the include loop were wrong, this is where it
    shows up — a year before anyone ships a card would otherwise be a long time
    to carry a broken hook.
    """
    from django.template.loader import render_to_string

    html = render_to_string(
        "accounting/partials/_dashboard_content.html",
        {
            "selected_period": type("P", (), {"name": "Water Year 2025-2026"})(),
            "module_dashboard_cards": ["partials/_demo_marker.html"],
        },
    )
    assert 'id="module-dashboard-cards"' in html


def test_dashboard_card_wrapper_absent_when_no_cards(dashboard_html):
    """The empty case emits nothing at all — that is what keeps the diff clean."""
    assert 'id="module-dashboard-cards"' not in dashboard_html


def test_dashboard_cards_for_concatenates_in_registry_order():
    """Unit-level check on the resolver, independent of any template."""
    from core.modules import ModuleSpec, dashboard_cards_for

    specs = (
        ModuleSpec(name="a", label="A", apps=("a",), dashboard_cards=("a/one.html",)),
        ModuleSpec(name="b", label="B", apps=("b",), dashboard_cards=()),
        ModuleSpec(name="c", label="C", apps=("c",),
                   dashboard_cards=("c/one.html", "c/two.html")),
    )
    assert dashboard_cards_for(specs) == ["a/one.html", "c/one.html", "c/two.html"]


def test_no_module_ships_a_dashboard_card_yet(db):
    """Pins the honest answer for the default deployment.

    Every ModuleSpec.dashboard_cards is empty today. Phase 78 adds the first
    real one; when it does, this test names itself as the thing to update rather
    than silently passing on a stale assumption.
    """
    from core.modules import enabled_modules

    with_cards = {s.name: s.dashboard_cards for s in enabled_modules() if s.dashboard_cards}
    assert with_cards == {}, (
        f"A module now ships a dashboard card: {with_cards}. Update this test "
        f"and add a golden fixture covering the new tile."
    )
