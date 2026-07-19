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


#: Database-assigned primary keys leak into the markup (account detail links,
#: the period <option> values) and they depend on how many rows earlier tests
#: created. Left in, the fixture passes when this file runs alone and fails
#: inside the full suite — a flake that teaches everyone to distrust the gate.
#: Structure is what we are pinning, so identity gets scrubbed.
_URL_PK = re.compile(r"/\d+/")
_VALUE_PK = re.compile(r'value="\d+"')


def normalize(html: str) -> str:
    html = _BETWEEN_TAGS.sub("><", html.strip())
    html = _URL_PK.sub("/<pk>/", html)
    return _VALUE_PK.sub('value="<pk>"', html)


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
    """The card list reaches the template, carrying drinking's card.

    Was `== []` through Phase 77, when no module shipped one. 78-02 makes
    `drinking` the first real user of the hook.
    """
    client = Client()
    client.force_login(UserFactory())
    response = client.get(reverse("accounting:dashboard"))
    assert response.status_code == 200
    assert "module_dashboard_cards" in response.context
    assert list(response.context["module_dashboard_cards"]) == [
        "drinking/partials/_dashboard_card.html"
    ]


def test_dashboard_renders_a_supplied_module_card():
    """The include loop itself, fed a real partial through the same context key.

    Renders `accounting/dashboard.html` rather than the content partial: 78-02
    moved the block up out of `_dashboard_content.html` so a module's card does
    not depend on an accounting reporting period existing.
    """
    from django.template.loader import render_to_string

    html = render_to_string(
        "accounting/dashboard.html",
        {"module_dashboard_cards": ["partials/_demo_marker.html"]},
    )
    assert 'id="module-dashboard-cards"' in html


def test_module_card_renders_without_any_reporting_period():
    """The regression 78-02 fixed, stated plainly.

    No `periods`, so the template takes its no-periods branch — the state a
    drinking-only deployment is permanently in. The card must still render.
    """
    from django.template.loader import render_to_string

    html = render_to_string(
        "accounting/dashboard.html",
        {"module_dashboard_cards": ["partials/_demo_marker.html"], "periods": []},
    )
    assert 'id="module-dashboard-cards"' in html


def test_dashboard_card_wrapper_absent_when_no_module_supplies_one():
    """The no-cards case still emits nothing at all.

    Rendered directly with an empty card list rather than through the live
    dashboard, because `drinking` now supplies one on a default deployment. The
    branch still matters: it is what a deployment that drops `drinking` gets.
    """
    from django.template.loader import render_to_string

    html = render_to_string(
        "accounting/dashboard.html", {"module_dashboard_cards": []}
    )
    assert 'id="module-dashboard-cards"' not in html


def test_drinking_card_renders_nothing_until_a_system_exists(dashboard_html):
    """An unused module must not put a panel of zeroes on the dashboard.

    The wrapper is present (drinking supplies a card path) but the card itself
    renders empty, so a deployment carrying the module without using it sees the
    dashboard it had before.
    """
    main = main_region(dashboard_html)
    assert 'id="module-dashboard-cards"' in main
    # Scoped to <main>: the sidebar legitimately carries a "Drinking Water" nav
    # link now, so a whole-page check would test the wrong thing.
    assert "Drinking Water" not in main


@pytest.mark.django_db
def test_drinking_card_renders_counts_once_a_system_exists():
    """The card's actual content, with data behind it."""
    from datetime import date as _date

    from tests.factories import (
        SampleEventFactory,
        SampleResultFactory,
        SamplingPointFactory,
        SystemFacilityFactory,
        WaterSystemFactory,
    )

    system = WaterSystemFactory(pwsid="CA1910067", name="Cedar Grove Water District")
    facility = SystemFacilityFactory(system=system)
    point = SamplingPointFactory(facility=facility)
    event = SampleEventFactory(sampling_point=point, sample_date=_date(2025, 4, 2))
    SampleResultFactory(event=event)

    client = Client()
    client.force_login(UserFactory())
    main = main_region(client.get(reverse("accounting:dashboard")).content.decode())

    # No ReportingPeriod is created here on purpose: a drinking-only deployment
    # does no groundwater accounting, and its card must still render.
    assert "Cedar Grove Water District" in main
    assert "CA1910067" in main
    assert "2025-04-02" in main
    # Counts only. The card must never grow a verdict.
    for verdict in ("exceed", "violation", "compliant"):
        assert verdict not in main.lower()


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


def test_drinking_is_the_only_module_shipping_a_dashboard_card(db):
    """Pins the honest answer for the default deployment.

    Was `== {}` through Phase 77. 78-02 makes `drinking` the first and only
    module with a card; the next one to add one lands here rather than slipping
    onto the dashboard unreviewed.
    """
    from core.modules import enabled_modules

    with_cards = {s.name: s.dashboard_cards for s in enabled_modules() if s.dashboard_cards}
    assert with_cards == {
        "drinking": ("drinking/partials/_dashboard_card.html",)
    }, (
        f"The set of modules shipping a dashboard card changed: {with_cards}. "
        f"Update this test and regenerate the dashboard golden fixture."
    )


def test_dropping_drinking_removes_its_card(db):
    """The card disappears with the module, like everything else it owns."""
    from core.modules import ALL_MODULE_NAMES, dashboard_cards_for, enabled_modules

    kept = [n for n in ALL_MODULE_NAMES if n != "drinking"]
    assert dashboard_cards_for(enabled_modules(kept)) == []
