# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every page stops at one standard content width unless it asks for a narrower one.

The width is 1,220 CSS px inside the content pane, which `.app-content` enlarges by its zoom
factor, so it is 1,296 px on screen. A page that names no width class must still stop there:
26 of 100 full pages once carried none and ran to the window's edge on a wide screen.

Two halves. The stylesheet: the zoom factor and the measure are each declared once, the default
rule caps every direct child of the pane except the three narrower classes, and the page head
sits on the same measure. The pages: rendered pages with no width class put every element of
their content directly under a pane that has not opted out, which is exactly what the default
rule's selector matches; only the map opts out. The geometry itself is measured in the browser
at six window widths by the width sweep, not here.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import factory
import pytest
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import PointOfDiversionFactory, ReportingPeriodFactory, WellFactory

pytestmark = pytest.mark.django_db

BASE = Path(settings.BASE_DIR)
APP_CSS = re.sub(r"/\*.*?\*/", "", (BASE / "static" / "css" / "app.css").read_text(), flags=re.S)

NARROWER = ("page-narrow", "page-medium", "page-help")
OPT_OUT = "page-full"
DEFAULT_SELECTOR = f".app-content:not(.{OPT_OUT}) > :not(.page-narrow, .page-medium, .page-help)"


def _rule(selector):
    # The selector opens a rule (at a line's start or after the last rule's brace), alone or first in a list.
    m = re.search(r"(?:^|\})[ \t]*" + re.escape(selector) + r"\s*(?:,\s*\n[^{]*)?\{([^}]*)\}", APP_CSS, flags=re.M)
    assert m, f"no rule for {selector}"
    return m.group(1)


def _declarations(selector):
    return {k.strip(): v.strip() for k, v in (d.split(":", 1) for d in _rule(selector).split(";") if ":" in d)}


# -- The stylesheet ---------------------------------------------------------------------------


def test_the_zoom_factor_and_the_measure_are_each_declared_once():
    assert re.findall(r"--content-zoom:\s*([\d.]+)\s*;", APP_CSS) == ["1.0625"]
    assert re.findall(r"--page-measure:\s*(\d+px)\s*;", APP_CSS) == ["1220px"]
    # Nowhere else does a rule carry the factor as a literal.
    assert "1.0625" not in APP_CSS.replace("--content-zoom: 1.0625", "")


def test_the_pane_zooms_by_the_factor():
    assert _declarations(".app-content")["zoom"] == "var(--content-zoom)"


def test_every_direct_child_of_the_pane_stops_at_the_measure_and_centres():
    rule = _declarations(DEFAULT_SELECTOR)
    assert rule["max-width"] == "var(--page-measure)"
    assert rule["margin-inline"] == "auto"


def test_the_wide_class_takes_the_default_value():
    assert _declarations(".page-wide")["max-width"] == "var(--page-measure)"


def test_the_narrower_widths_are_kept():
    assert _declarations(".page-narrow")["max-width"] == "640px"
    assert _declarations(".page-medium")["max-width"] == "800px"
    assert _declarations(".page-help")["max-width"] == "1100px"


def test_the_page_head_sits_on_the_same_measure():
    """The head is outside the zoomed pane, so its measure is the body's times the factor."""
    rule = _declarations(".page-head > *")
    assert rule["max-width"] == "calc(var(--page-measure) * var(--content-zoom))"
    assert rule["margin-inline"] == "auto"


# -- The pages --------------------------------------------------------------------------------


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"widthreader{n}")
    email = factory.Sequence(lambda n: f"widthreader{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True
    is_superuser = True


@pytest.fixture
def client_in():
    c = Client()
    c.force_login(_UserFactory())
    return c


class _Pane(HTMLParser):
    """The <main class="app-content"> element's classes and the classes of its direct element children."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.main_depth = None
        self.main_classes = None
        self.children = []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "main" and "app-content" in classes and self.main_depth is None:
            self.main_depth = self.depth
            self.main_classes = classes
        elif self.main_depth is not None and self.depth == self.main_depth + 1 and tag not in ("script", "style", "template"):
            self.children.append((tag, classes))
        if tag not in self.VOID:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self.depth -= 1
            if self.main_depth is not None and self.depth == self.main_depth and tag == "main":
                self.main_depth = -1  # closed; ignore any later <main>


def _pane(client, url):
    resp = client.get(url)
    assert resp.status_code == 200, url
    p = _Pane()
    p.feed(resp.content.decode())
    assert p.main_classes is not None, f"{url} has no content pane"
    return p


def _pages_with_no_width_class():
    period = ReportingPeriodFactory()
    return {
        "home": reverse("index"),
        "dashboard": reverse("accounting:dashboard") + f"?period={period.pk}",
        "well": reverse("wells:detail", args=[WellFactory().pk]),
        "point of diversion": reverse("surface:pod_detail", args=[PointOfDiversionFactory().pk]),
    }


def test_a_page_with_no_width_class_still_stops_at_the_default(client_in):
    for name, url in _pages_with_no_width_class().items():
        p = _pane(client_in, url)
        assert OPT_OUT not in p.main_classes, f"{name} opts out of the standard width"
        assert p.children, f"{name} has no content"
        for tag, classes in p.children:
            # The default rule's selector matches exactly these: a direct child of a pane that has
            # not opted out, carrying none of the narrower classes.
            assert not set(classes) & set(NARROWER), f"{name}: <{tag} class={classes}> would leave the default"


def test_a_help_page_keeps_its_own_width(client_in):
    p = _pane(client_in, reverse("methods"))
    assert OPT_OUT not in p.main_classes
    assert any("page-help" in classes for _tag, classes in p.children)


def test_only_the_map_runs_full_width(client_in):
    p = _pane(client_in, reverse("geography:map"))
    assert OPT_OUT in p.main_classes
