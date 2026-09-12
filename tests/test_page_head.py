# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every page has one title, and a person can see it (Phase 143-02, R-058).

Before this phase ``base.html`` rendered the per-page ``{% block page_title %}``
as ``<h1 class="sr-only">``: present for a screen reader, invisible to everyone
else, so the only title a reader had was the last breadcrumb at 13px. Two pages
(About, Site health) carried a second, visible ``<h1>`` of their own, so they
had two.

The guard is rendered, not source: it rides the same crawl
``tests/test_platform_readability.py`` uses (every argument-free route, signed
in as a superuser), and asserts on the markup a browser receives. Observed RED
against the pre-change tree: every crawled page reported ``0 visible`` (the
``sr-only`` h1) and About and Site health reported two h1s.

It pins a COUNT and a CLASS, never a string (the ISS-129 line: a test may not
mandate words).
"""

import re

import pytest

from tests.test_platform_readability import crawled  # noqa: F401 — the fixture

_H1_OPEN = re.compile(r"<h1\b([^>]*)>", re.I)


def _h1_attribute_strings(html):
    return _H1_OPEN.findall(html)


@pytest.mark.django_db
def test_every_page_has_exactly_one_h1_and_it_is_visible(crawled):  # noqa: F811
    rendered, _ = crawled
    assert rendered, "the crawl rendered nothing; the guard did not engage"
    faults = {}
    for url, page in rendered.items():
        h1s = _h1_attribute_strings(page["html"])
        hidden = [attrs for attrs in h1s if "sr-only" in attrs]
        if len(h1s) != 1 or hidden:
            faults[url] = f"{len(h1s)} h1, {len(hidden)} screen-reader-only"
    assert faults == {}, (
        "a page's title is missing, doubled, or hidden from sight "
        f"({len(faults)} of {len(rendered)} pages): {faults}"
    )


@pytest.mark.django_db
def test_the_visible_title_is_the_page_title_block(crawled):  # noqa: F811
    """The one h1 is the head's `.page-title`, i.e. the block every template
    already declares, not some page's own hand-made heading.

    Scoped to pages on OUR two shells: `base.html` (the app shell, `.page-head`)
    and `base_auth.html` (the signed-out card, `.auth-title`). allauth's own
    templates under `/accounts/` that this platform does not override
    (`3rdparty/`, `email/`, `inactive/`, `password/change/`, `reauthenticate/`)
    render allauth's layout with a bare `<h1>`; they never had our head and are
    not asserted here. Observed RED on the pre-change tree: every app-shell page
    reported ` class="sr-only"`.
    """
    rendered, _ = crawled
    off_pattern = {
        url: attrs
        for url, page in rendered.items()
        if 'class="app-shell"' in page["html"] or "auth-title" in page["html"]
        for attrs in _h1_attribute_strings(page["html"])
        if "page-title" not in attrs and "auth-title" not in attrs
    }
    assert off_pattern == {}, f"an h1 that is not the page head's title: {off_pattern}"


# ---------------------------------------------------------------------------
# Source half: a template that declares a breadcrumb strip declares its own
# title too, or the visible h1 says "Open Water Accounting Platform" on it.
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from django.conf import settings  # noqa: E402

_TEMPLATES = Path(settings.BASE_DIR) / "templates"
_DEFAULT_TITLE = "Open Water Accounting Platform"


def _declares(path, block):
    return f"{{% block {block} %}}" in path.read_text()


def test_every_template_with_a_breadcrumb_strip_declares_its_own_title():
    """Observed RED against the pre-change tree: delivery_settings.html and
    methodology_settings.html declared breadcrumbs and no page_title, so the
    visible title on those two pages was the platform's name. (About declares
    neither block but is caught by the rendered guard above.)"""
    missing = sorted(
        str(p.relative_to(_TEMPLATES))
        for p in _TEMPLATES.rglob("*.html")
        if _declares(p, "breadcrumbs") and not _declares(p, "page_title")
    )
    assert missing == [], f"a page with a breadcrumb strip and no title of its own: {missing}"


def test_no_page_template_declares_the_default_title():
    """The base default is the fallback for a page that forgot; a template that
    declares it on purpose has no title."""
    offenders = sorted(
        str(p.relative_to(_TEMPLATES))
        for p in _TEMPLATES.rglob("*.html")
        if p.name != "base.html"
        and f"{{% block page_title %}}{_DEFAULT_TITLE}{{% endblock %}}" in p.read_text()
    )
    assert offenders == [], f"a template titles itself with the platform's name: {offenders}"
