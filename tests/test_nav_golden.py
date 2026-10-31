# SPDX-License-Identifier: AGPL-3.0-or-later
"""Golden-HTML contract for the sidebar.

Phase 77-02 rewrites `templates/partials/_sidebar.html` from 337 lines of
hand-written markup into a loop over the module registry. The promise is that a
default deployment's rendered nav does not change by a single byte. A promise
that nobody checks is a wish, so this module freezes today's output as fixtures
and re-renders against them.

**The fixtures are the contract, not a convenience.** If a test here fails, the
template is wrong — fix the template. Never regenerate a fixture to match a
template you just changed; that turns the gate into a rubber stamp. Regeneration
(``GOLDEN_UPDATE=1``) exists only for a *deliberate*, reviewed nav change, and
the resulting fixture diff must be read line by line before it is committed.

Three axes are covered, because they fail in different ways:

* **Visibility**: every combination of ``user_is_admin`` x ``access_enforced``
  (4), rendered at ``/``. These pin the predicates the registry loop applies.
  There is no sidebar mode: the Operations/Admin switch is gone (151.8-01).
* **Drinking water state**: the collapsible Drinking water group rendered open
  and rendered closed (2), because the ``open`` attribute is the one thing the
  group's three conditions change.
* **Active state** — one representative path per nav entry (24), rendered at a
  fixed permutation that shows every link. These pin the ``active`` class. The
  pair ``/surface/`` and ``/surface/rights/`` is the whole reason this axis
  exists: Surface Diversions matches on ``/surface/`` but must NOT light up on
  the Water Rights page, and dropping that exclusion is the single easiest way
  to regress this refactor invisibly.

Only whitespace *between* tags is normalised. Class attributes are compared
verbatim, since an active-state regression would hide there.
"""
import os
import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from core.modules import (
    enabled_modules,
    lit_entry,
    nav_sections_for,
    sidebar_entries,
)

GOLDEN_DIR = Path(__file__).parent / "golden"

#: Any valid section key; the is_active unit tests never look at the section.
SECTION_FOR_TEST = "sources_monitoring"

#: Set GOLDEN_UPDATE=1 to rewrite the fixtures. See the module docstring — this
#: is for a deliberate nav change, never for making a red test go green.
UPDATE = os.environ.get("GOLDEN_UPDATE") == "1"

SIDEBAR = "partials/_sidebar.html"

# Collapse runs of whitespace that sit BETWEEN tags. Text content and attribute
# values are left exactly as rendered.
_BETWEEN_TAGS = re.compile(r">\s+<")


def normalize(html: str) -> str:
    return _BETWEEN_TAGS.sub("><", html.strip())


# -- Permutations ------------------------------------------------------------

VISIBILITY_CASES = [
    (user_is_admin, access_enforced)
    for user_is_admin in (True, False)
    for access_enforced in (True, False)
]

#: The Drinking water group's two renders: fixture name, `drinking_group_open`.
DRINKING_STATES = [
    ("sidebar_drinking-group_open", True),
    ("sidebar_drinking-group_closed", False),
]

#: One representative request path per nav entry, plus the two static-page paths
#: that drive the Help section's auto-open. Rendered at user_is_admin=True /
#: access_enforced=False, the permutation that shows every link at once.
ACTIVE_PATHS = [
    "/",
    "/accounting/dashboard/",
    # 150-03: the calculation receipt has no entry of its own and lights
    # Dashboard through `also_matches`.
    "/accounting/calculation-run/1/2024-06/",
    "/map/",
    "/accounting/ledger/",
    "/parcels/",
    "/wells/",
    "/surface/",
    "/surface/rights/",
    "/recharge/",
    # Phase 78's three, plus 100-01's Facilities. The overview's prefix is a
    # prefix of every sub-page, so all of them are listed for the same reason
    # /surface/ and /surface/rights/ both are: the exclusion is the easy thing
    # to regress invisibly.
    "/drinking/",
    "/drinking/facilities/",
    "/drinking/sampling-points/",
    "/drinking/results/",
    # The onboarding pages light Water Systems (151.8-01): no exclusion for them.
    "/drinking/onboard/",
    "/drinking/import/",
    # 146-04 Task 2's production door. Same trap again: `/drinking/` is a
    # prefix of it too.
    "/drinking/production/",
    # 146-04 Task 4's schedule door, and the same trap once more.
    "/drinking/schedule/",
    "/datasync/stations/",
    "/accounting/accounts/",
    "/accounting/reporting-periods/",
    "/accounting/allocations/",
    "/map/zones/",
    # A settings page lights no sidebar link; its fixture is the sidebar with
    # nothing lit (the header button carries the state, tested elsewhere).
    "/settings/",
    "/users/",
    "/accounting/methodology/",
    "/accounting/delivery-settings/",
    "/health/",
    "/setup/",
    "/reporting/",
    "/help/getting-started/",
    "/about/",
]


def render_sidebar(path="/", user_is_admin=False, access_enforced=False,
                   module_names=None, drinking_group_open=None):
    """Render the sidebar with an explicit context.

    Deliberately does NOT go through RequestContext/context processors: the
    fixture should pin what the *template* does with a given context, not what
    the processors happen to supply that day. `nav_sections` and
    `enabled_modules` are passed from the start so this helper is unchanged
    before and after the registry rewrite.

    150-03: the lit link is decided once per request by `lit_entry`, which the
    `modules` processor runs; it is computed here from the same entries and
    passed as `nav_lit` / `nav_lit_section`, the two values the template reads.
    `drinking_group_open` is what the `modules` processor computes (D8); when
    not given it is the lit section rule only, so a drinking path opens the
    group and any other path leaves it closed.
    """
    specs = enabled_modules(module_names)
    lit = lit_entry(path, sidebar_entries(specs))
    if drinking_group_open is None:
        drinking_group_open = lit is not None and lit.section == "drinking_water"
    return render_to_string(
        SIDEBAR,
        {
            "request": RequestFactory().get(path),
            "user_is_admin": user_is_admin,
            "access_enforced": access_enforced,
            "enabled_modules": [spec.name for spec in specs],
            "nav_sections": nav_sections_for(specs),
            "nav_lit": lit.url_name if lit is not None else None,
            "nav_lit_section": lit.section if lit is not None else "",
            "drinking_group_open": drinking_group_open,
        },
    )


def check(name: str, html: str):
    """Compare against the fixture, or write it under GOLDEN_UPDATE=1."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    fixture = GOLDEN_DIR / f"{name}.html"
    actual = normalize(html)

    if UPDATE:
        fixture.write_text(actual + "\n", encoding="utf-8")
        return

    assert fixture.exists(), (
        f"Missing golden fixture {fixture}. Generate the baseline with "
        f"GOLDEN_UPDATE=1 against the UNMODIFIED templates."
    )
    expected = fixture.read_text(encoding="utf-8").strip()
    assert actual == expected, (
        f"Rendered sidebar drifted from golden fixture {fixture.name}. "
        f"Fix the template to match the fixture — do NOT edit the fixture."
    )


# -- Tests -------------------------------------------------------------------


@pytest.mark.parametrize("user_is_admin,access_enforced", VISIBILITY_CASES)
def test_sidebar_visibility_permutations(user_is_admin, access_enforced):
    name = (
        f"sidebar_visibility_admin-{str(user_is_admin).lower()}"
        f"_enforced-{str(access_enforced).lower()}"
    )
    check(name, render_sidebar(
        path="/",
        user_is_admin=user_is_admin,
        access_enforced=access_enforced,
    ))


@pytest.mark.parametrize("name,is_open", DRINKING_STATES)
def test_sidebar_drinking_group_states(name, is_open):
    check(name, render_sidebar(
        path="/",
        user_is_admin=True,
        access_enforced=False,
        drinking_group_open=is_open,
    ))


@pytest.mark.parametrize("path", ACTIVE_PATHS)
def test_sidebar_active_state_by_path(path):
    slug = path.strip("/").replace("/", "_") or "root"
    check(f"sidebar_active_{slug}", render_sidebar(
        path=path,
        user_is_admin=True,
        access_enforced=False,
    ))


def test_diversions_not_active_on_water_rights_page():
    """The compound active-match, asserted directly rather than only via fixture.

    Surface Diversions is active on `/surface/` and must not be on
    `/surface/rights/`. Stated as its own test so a regression names itself
    instead of surfacing as an opaque byte diff.
    """
    on_surface = render_sidebar(path="/surface/", user_is_admin=True)
    on_rights = render_sidebar(path="/surface/rights/", user_is_admin=True)

    def link_classes(html, url):
        match = re.search(
            r'<a href="' + re.escape(url) + r'"\s*\n?\s*class="([^"]*)"', html
        )
        assert match, f"No sidebar link found for {url}"
        return match.group(1)

    assert "active" in link_classes(on_surface, "/surface/")
    assert "active" not in link_classes(on_rights, "/surface/")
    assert "active" in link_classes(on_rights, "/surface/rights/")


def test_water_systems_is_active_on_its_own_pages_and_not_on_the_sub_pages():
    """The exclude case, asserted directly rather than only via fixture.

    Same failure mode as Surface Diversions: `/drinking/` is a prefix of EVERY
    sub-page, so a missing exclusion leaves Water Systems lit while the reader
    is somewhere else. The onboarding and import pages are the exception: they
    belong to Water Systems (151.8-01), so it stays lit there and no exclusion
    names them.

    The facility DETAIL path is included on purpose. It is not a nav entry of
    its own, so no golden fixture covers it; it must light Facilities.
    """
    pages = {
        p: render_sidebar(path=p, user_is_admin=True)
        for p in (
            "/drinking/",
            "/drinking/facilities/",
            "/drinking/facilities/12/",
            "/drinking/sampling-points/",
            "/drinking/results/",
            "/drinking/production/",
            "/drinking/schedule/",
            "/drinking/onboard/",
            "/drinking/import/",
        )
    }

    def link_classes(html, url):
        match = re.search(
            r'<a href="' + re.escape(url) + r'"\s*\n?\s*class="([^"]*)"', html
        )
        assert match, f"No sidebar link found for {url}"
        return match.group(1)

    for lit_here in ("/drinking/", "/drinking/onboard/", "/drinking/import/"):
        assert "active" in link_classes(pages[lit_here], "/drinking/"), lit_here
    for sub in (
        "/drinking/facilities/", "/drinking/facilities/12/", "/drinking/sampling-points/",
        "/drinking/results/", "/drinking/production/", "/drinking/schedule/",
    ):
        assert "active" not in link_classes(pages[sub], "/drinking/"), sub

    # And each sub-page lights up its own entry.
    assert "active" in link_classes(
        pages["/drinking/facilities/"], "/drinking/facilities/"
    )
    assert "active" in link_classes(
        pages["/drinking/facilities/12/"], "/drinking/facilities/"
    ), "the facility detail page lights no entry at all"
    assert "active" in link_classes(
        pages["/drinking/sampling-points/"], "/drinking/sampling-points/"
    )
    assert "active" in link_classes(pages["/drinking/results/"], "/drinking/results/")
    assert "active" in link_classes(pages["/drinking/production/"], "/drinking/production/")
    assert "active" in link_classes(pages["/drinking/schedule/"], "/drinking/schedule/")


def test_nav_entry_is_active_handles_multiple_excludes():
    """The resolver itself, independent of any template."""
    from core.modules import NavEntry

    entry = NavEntry(
        url_name="x:y", label="X", icon="x", section=SECTION_FOR_TEST, order=10,
        active_match="/drinking/",
        active_excludes=("/drinking/sampling-points", "/drinking/results"),
    )
    assert entry.is_active("/drinking/") is True
    assert entry.is_active("/drinking/sampling-points/") is False
    assert entry.is_active("/drinking/results/") is False
    assert entry.is_active("/wells/") is False

    # A no-exclude entry is a plain substring match, exactly as before 78-02.
    plain = NavEntry(
        url_name="x:y", label="X", icon="x", section=SECTION_FOR_TEST, order=10,
        active_match="/wells/",
    )
    assert plain.is_active("/wells/") is True
    assert plain.is_active("/wells/3/") is True
    assert plain.is_active("/parcels/") is False


def test_disabling_a_module_removes_only_its_own_nav():
    """The point of the whole phase: omit a module, lose exactly its links.

    Uses `reporting`, `health` and `setup` because those are genuinely droppable
    today (see OPTIONAL_MODULE_NAMES). Site Health and the Setup Wizard are rows
    of the Settings page now, so the sidebar test is about `reporting`; the
    other two leave `settings_entries_for`.

    `reporting` is the interesting one: it is the ONLY entry in its section.
    Since 2026-10-12, dropping it leaves its heading over one
    greyed, unlinked "Reports" marked "Under development", and no link into
    /reporting/.
    """
    from core.modules import ALL_MODULE_NAMES, settings_entries_for

    dropped = {"reporting", "health", "setup"}
    kept = [n for n in ALL_MODULE_NAMES if n not in dropped]

    full = render_sidebar(path="/", user_is_admin=True, access_enforced=False)
    trimmed = render_sidebar(path="/", user_is_admin=True, access_enforced=False,
                             module_names=kept)

    assert ">Reports</span>" in full
    # The greyed entry that stands in its place is not the linked one.
    assert ">Reports</span>" not in trimmed

    # Reporting stays as a greyed, unlinked entry; nothing links into it.
    assert "sidebar-section-label\">Reporting</span>" in full
    assert "sidebar-link-disabled" not in full
    assert 'href="/reporting/' not in trimmed
    assert 'aria-disabled="true" title="Under development"' in trimmed
    assert '<span class="sidebar-link-note">Under development</span>' in trimmed

    # The settings rows leave with their modules.
    full_settings = [e.label for e in settings_entries_for(enabled_modules())]
    trimmed_settings = [e.label for e in settings_entries_for(enabled_modules(kept))]
    for label in ("Site Health", "Setup Wizard"):
        assert label in full_settings
        assert label not in trimmed_settings
        assert f">{label}</span>" not in trimmed

    # Sections that still have entries keep their headings.
    for label in ("Water accounting", "Sources and monitoring", "Drinking water"):
        assert f"sidebar-section-label\">{label}</span>" in trimmed

    # Nothing else moved: every other entry survives, in the same order.
    # Compare only module-owned labels on both sides; Home and the Help links
    # are hand-written and belong to neither module.
    survivors = {e.label for spec in enabled_modules(kept) for e in spec.nav}

    def keep_only(html):
        return [label for label in _labels_in_order(html) if label in survivors]

    assert keep_only(trimmed) == keep_only(full)


def _labels_in_order(html):
    return re.findall(r'<span class="sidebar-link-text">([^<]+)</span>', html)


def test_every_registry_icon_key_has_a_partial():
    """A missing icon file must fail here, not render an empty slot.

    `_nav_icon.html` resolves its target by string-building the path from the
    entry's `icon` key. Django raises TemplateDoesNotExist for a missing file,
    so the real risk is not silence — it is a 500 on a page nobody tested. This
    turns that into a named failure at suite time.
    """
    icon_dir = Path(__file__).parent.parent / "templates" / "partials" / "icons"
    missing = [
        entry.icon
        for spec in enabled_modules()
        for entry in spec.nav
        if not (icon_dir / f"_{entry.icon}.html").exists()
    ]
    assert not missing, f"Registry icon keys with no partial: {sorted(set(missing))}"


def test_every_sidebar_entry_is_rendered_and_no_settings_entry_is():
    """All 20 sidebar entries appear when every gate is open; the 5 settings
    entries (Methodology, Delivery Settings, Users, Site Health, Setup Wizard)
    are the Settings page's rows and never appear here.

    Guards the failure mode a byte-diff cannot: if the registry loop silently
    drops an entry AND the fixture were regenerated, this still fails.
    """
    html = render_sidebar(path="/", user_is_admin=True, access_enforced=False)
    every = [e for spec in enabled_modules() for e in spec.nav]
    assert len(every) == 25
    settings_rows = [e for e in every if e.section == "settings"]
    drawn = [e for e in every if e.section != "settings"]
    assert len(settings_rows) == 5 and len(drawn) == 20
    for entry in drawn:
        assert f">{entry.label}</span>" in html, (
            f"Nav entry {entry.url_name!r} ({entry.label}) is missing from the sidebar"
        )
    for entry in settings_rows:
        assert f">{entry.label}</span>" not in html, (
            f"Settings entry {entry.url_name!r} ({entry.label}) is drawn in the sidebar"
        )


def test_the_sidebar_draws_no_group_divider_because_each_group_has_a_heading():
    """`starts_group` is gone: Drinking water has its own heading, so no hairline
    rule splits the tail of another section.

    The second half keeps the case the old divider guarded: drop the
    accounting/parcels pair and five more sections go with it, leaving drinking
    water alone. Its heading and links must still render, with no rule and no
    "Water accounting" heading.
    """
    full = render_sidebar(path="/", user_is_admin=True, access_enforced=False)
    assert "sidebar-divider" not in full

    from core.modules import ALL_MODULE_NAMES

    from tests.test_droppability_acceptance import drop_closure

    # Not a hand-written list: the closure is what the platform would really
    # drop, so this keeps describing the drinking-water-utility flavor even if
    # the dependency graph moves.
    gone = drop_closure("accounting")
    kept = [n for n in ALL_MODULE_NAMES if n not in gone]
    assert "drinking" in kept

    drinking_only = render_sidebar(path="/", user_is_admin=True, access_enforced=False,
                                   module_names=kept, drinking_group_open=True)
    assert ">Water Systems</span>" in drinking_only
    assert "sidebar-section-label\">Drinking water</span>" in drinking_only
    assert "sidebar-divider" not in drinking_only
    assert "Water accounting" not in drinking_only
    assert ">Zones</span>" in drinking_only
