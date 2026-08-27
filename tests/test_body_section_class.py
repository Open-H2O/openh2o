# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `<body>` tag names the nav section the current page belongs to.

**Why this file exists at all.** Phase 122 added `page_section` to
`core/context_processors.py` and rendered it as `class="section-…"` on
`<body>`. Nothing already in the suite can see that value:

- `tests/test_nav_golden.py:111-120` renders the sidebar partial from a
  hand-built context that deliberately bypasses context processors, so the
  processor never runs.
- `tests/test_dashboard_golden.py:59` captures `<main>…</main>` only, and
  `<body>` is outside it.

A value computed in a context processor is invisible to both. Every assertion
below therefore renders a **real page through the test client**, which is the
only path that actually runs the processor.

The six fixtures are **hard-coded on purpose**. Importing `core.modules` and
recomputing the expected section would let the test and the code share a bug
and agree with each other.
"""
import re

import pytest
from django.test import Client

# Verified against the running application, 2026-08-26 (122-01-EVIDENCE.md 17.4).
SECTION_FIXTURES = [
    ("/wells/", "water_data"),
    ("/accounting/accounts/", "administration"),
    ("/surface/rights/", "administration"),
    ("/drinking/results/", "water_data"),
    ("/setup/", "administration"),
    ("/reporting/reports/", "reporting"),
]

BODY_TAG = re.compile(rb"<body[^>]*>")

# What `<body>` looked like before Phase 122, and must still look like on any
# page outside the sidebar. The CSRF token is the only part that ever varied.
UNCLASSED_BODY = re.compile(
    r"""^<body hx-headers='\{"X-CSRFToken": "[^"]*"\}'>$"""
)


@pytest.fixture
def client_admin(db, django_user_model):
    """A superuser, so every fixture path renders its own page rather than
    redirecting to login — a redirect would render the login screen's `<body>`
    and quietly test nothing."""
    user = django_user_model.objects.create_superuser(
        username="section-probe",
        email="section-probe@example.gov",
        password="pw-not-a-secret-12345",
    )
    client = Client()
    client.force_login(user)
    return client


def body_tag(response) -> str:
    match = BODY_TAG.search(response.content)
    assert match, "response carried no <body> tag"
    return match.group(0).decode()


@pytest.mark.parametrize("path,section", SECTION_FIXTURES)
def test_page_carries_its_nav_section_on_body(client_admin, path, section):
    """Each sidebar-reachable page names the section it lives under."""
    tag = body_tag(client_admin.get(path, follow=True))
    assert f'class="section-{section}"' in tag, (
        f"{path} should carry section-{section}, got: {tag}"
    )


def test_a_path_outside_the_sidebar_carries_no_class_at_all(client_admin):
    """The login screen's `<body>` is byte-identical to its pre-122 form.

    This is what stops a future "helpful" default — `section-overview` on every
    unmatched page — from silently appearing on screens that have no section.
    """
    tag = body_tag(client_admin.get("/accounts/login/", follow=True))
    assert "class=" not in tag, f"login page grew a class attribute: {tag}"
    assert UNCLASSED_BODY.match(tag), f"login <body> is not its pre-122 form: {tag}"


@pytest.mark.parametrize("path,_section", SECTION_FIXTURES)
def test_body_carries_at_most_one_section_token(client_admin, path, _section):
    """An ambiguous path must never emit two section classes."""
    tag = body_tag(client_admin.get(path, follow=True))
    assert tag.count("section-") <= 1, f"{path} emitted more than one section: {tag}"


def test_the_section_keeps_the_platforms_own_spelling(client_admin):
    """`section-water_data`, underscore and all.

    `core/modules.py` spells the section keys `water_data`, `administration`,
    `reporting`, `help`, `overview`. Kebab-casing them in the template would
    mint a second spelling of one identifier that nothing enforces — the exact
    defect Phase 122 exists to remove.
    """
    tag = body_tag(client_admin.get("/wells/", follow=True))
    assert "section-water_data" in tag, tag
    assert "section-water-data" not in tag, f"kebab-cased second spelling: {tag}"
