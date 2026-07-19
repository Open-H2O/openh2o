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

Two axes are covered, because they fail in different ways:

* **Visibility** — every combination of ``nav_mode`` x ``user_is_admin`` x
  ``access_enforced`` (8), rendered at ``/``. These pin the four predicates the
  registry loop has to reproduce.
* **Active state** — one representative path per nav entry (22), rendered at a
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

from core.modules import enabled_modules, nav_sections_for

GOLDEN_DIR = Path(__file__).parent / "golden"

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
    (nav_mode, user_is_admin, access_enforced)
    for nav_mode in ("operations", "admin")
    for user_is_admin in (True, False)
    for access_enforced in (True, False)
]

#: One representative request path per nav entry, plus the two static-page paths
#: that drive the Help section's auto-open. Rendered at nav_mode=admin /
#: user_is_admin=True / access_enforced=False, the permutation that shows every
#: link at once.
ACTIVE_PATHS = [
    "/",
    "/accounting/dashboard/",
    "/map/",
    "/accounting/ledger/",
    "/parcels/",
    "/wells/",
    "/surface/",
    "/surface/rights/",
    "/recharge/",
    "/datasync/stations/",
    "/accounting/accounts/",
    "/accounting/reporting-periods/",
    "/accounting/allocations/",
    "/map/zones/",
    "/users/",
    "/accounting/methodology/",
    "/accounting/delivery-settings/",
    "/health/",
    "/setup/",
    "/reporting/",
    "/help/getting-started/",
    "/about/",
]


def render_sidebar(path="/", nav_mode="operations", user_is_admin=False,
                   access_enforced=False):
    """Render the sidebar with an explicit context.

    Deliberately does NOT go through RequestContext/context processors: the
    fixture should pin what the *template* does with a given context, not what
    the processors happen to supply that day. `nav_sections` and
    `enabled_modules` are passed from the start so this helper is unchanged
    before and after the registry rewrite.
    """
    specs = enabled_modules()
    return render_to_string(
        SIDEBAR,
        {
            "request": RequestFactory().get(path),
            "nav_mode": nav_mode,
            "user_is_admin": user_is_admin,
            "access_enforced": access_enforced,
            "enabled_modules": [spec.name for spec in specs],
            "nav_sections": nav_sections_for(specs),
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


@pytest.mark.parametrize("nav_mode,user_is_admin,access_enforced", VISIBILITY_CASES)
def test_sidebar_visibility_permutations(nav_mode, user_is_admin, access_enforced):
    name = (
        f"sidebar_visibility_{nav_mode}"
        f"_admin-{str(user_is_admin).lower()}"
        f"_enforced-{str(access_enforced).lower()}"
    )
    check(name, render_sidebar(
        path="/",
        nav_mode=nav_mode,
        user_is_admin=user_is_admin,
        access_enforced=access_enforced,
    ))


@pytest.mark.parametrize("path", ACTIVE_PATHS)
def test_sidebar_active_state_by_path(path):
    slug = path.strip("/").replace("/", "_") or "root"
    check(f"sidebar_active_{slug}", render_sidebar(
        path=path,
        nav_mode="admin",
        user_is_admin=True,
        access_enforced=False,
    ))


def test_diversions_not_active_on_water_rights_page():
    """The compound active-match, asserted directly rather than only via fixture.

    Surface Diversions is active on `/surface/` and must not be on
    `/surface/rights/`. Stated as its own test so a regression names itself
    instead of surfacing as an opaque byte diff.
    """
    on_surface = render_sidebar(path="/surface/", nav_mode="admin", user_is_admin=True)
    on_rights = render_sidebar(path="/surface/rights/", nav_mode="admin", user_is_admin=True)

    def link_classes(html, url):
        match = re.search(
            r'<a href="' + re.escape(url) + r'"\s*\n?\s*class="([^"]*)"', html
        )
        assert match, f"No sidebar link found for {url}"
        return match.group(1)

    assert "active" in link_classes(on_surface, "/surface/")
    assert "active" not in link_classes(on_rights, "/surface/")
    assert "active" in link_classes(on_rights, "/surface/rights/")


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


def test_every_nav_entry_is_rendered():
    """All 19 module-owned entries appear when every gate is open.

    Guards the failure mode a byte-diff cannot: if the registry loop silently
    drops an entry AND the fixture were regenerated, this still fails.
    """
    html = render_sidebar(path="/", nav_mode="admin", user_is_admin=True,
                          access_enforced=False)
    expected = [e for spec in enabled_modules() for e in spec.nav]
    assert len(expected) == 19
    for entry in expected:
        assert f">{entry.label}</span>" in html, (
            f"Nav entry {entry.url_name!r} ({entry.label}) is missing from the sidebar"
        )
