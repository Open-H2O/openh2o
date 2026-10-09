# SPDX-License-Identifier: AGPL-3.0-or-later
"""150-04 class FORM: a form is a two-track grid, not a column of bars (rule B).

`static/css/app.css` (the 150-04 block) defines `.form-grid` (two tracks),
`.form-span-2` (a group across both), `.form-grid--row` (a one-line form) and
`.card-columns` (one-control cards two or three across). This file pins that
the pages the layout inventory named carry them:

- F1, S4 and every other form page that sat at the 640 px measure: the form is
  on `.form-grid` and the page at the medium measure (`.page-medium`,
  `page-head--medium`); the old `.form-row-2col` / `.form-grid-2col` rows are
  gone so the form has one rhythm. A page of one or two fields may keep the
  narrow measure; it is named in `_NARROW_ALLOWED` with its reason.
- F7: the two diversion record forms are on the grid, the undefined
  `form-stack` class is gone, and their wrapper no longer caps them at 640 px.
- F2, F3: the methodology step forms (a step with no options is one row).
- S16: the wizard's two boundary cards were paired and then unpaired on the read (stacked).
- S5: the delivery setting cards were tried in columns and stay one column (the read).

It pins CLASSES and element ids, never a reader-facing string (the ISS-129
line: a test may not mandate words). Every test was RED against the pre-change
tree; the red assertion is named in each docstring.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

User = get_user_model()

_TEMPLATES = Path(settings.BASE_DIR) / "templates"

#: The form pages moved from the narrow to the medium measure (rule B). They
#: are the pages `grep -l page-narrow templates -r | xargs grep -l '<form'`
#: listed on 2026-10-09, less the one in `_NARROW_ALLOWED`.
_GRID_FORM_PAGES = [
    "accounting/ledger_create.html",
    "accounting/account_create.html",
    "accounting/account_edit.html",
    "accounting/allocation_create.html",
    "accounting/period_create.html",
    "core/user_form.html",
    "core/profile.html",
    "datasync/station_add.html",
    "geography/zone_edit.html",
    "surface/right_form.html",
    "surface/device_form.html",
    "surface/curtailment_form.html",
    "surface/pod_form.html",
    "drinking/production_form.html",
    "drinking/facility_form.html",
    "drinking/schedule_form.html",
]

#: Form pages that keep the 640 px measure, each with why (DESIGN.md: "the
#: 640 px measure is for a page of one or two fields").
_NARROW_ALLOWED = {
    # Two selects (report type, water year) above a stack of validation
    # warnings; the warnings read better at the narrow measure.
    "reporting/report_generate.html",
}

_FORM_TAG = re.compile(r"<form\b[^>]*>", re.S)
_CLASS_ATTR = re.compile(r'\bclass="([^"]*)"')


def _form_classes(text):
    """The class tokens of every <form> tag in a template, one set per tag."""
    out = []
    for tag in _FORM_TAG.findall(text):
        match = _CLASS_ATTR.search(tag)
        out.append(set(match.group(1).split()) if match else set())
    return out


@pytest.mark.parametrize("name", _GRID_FORM_PAGES)
def test_form_page_is_a_grid_at_the_medium_measure(name):
    """RED before: no form carried `form-grid` (the first assertion) and every
    page sat at `page-narrow`."""
    text = (_TEMPLATES / name).read_text()
    assert any("form-grid" in classes for classes in _form_classes(text)), (
        f"{name}: the form is not on .form-grid"
    )
    assert "page-narrow" not in text, f"{name}: still at the 640 px measure"
    assert "page-medium" in text, f"{name}: the body is not at the medium measure"
    assert "{% block page_head_class %}page-head--medium{% endblock %}" in text, (
        f"{name}: the head is not at the medium measure"
    )
    for old in ("form-row-2col", "form-grid-2col"):
        assert old not in text, f"{name}: a {old} row survives inside the grid"


def test_every_narrow_page_with_a_form_is_allowed():
    """A new form page lands at the medium measure unless it is a page of one
    or two fields named above. RED before: 17 templates matched, 16 of them
    not allowed."""
    narrow_forms = {
        str(p.relative_to(_TEMPLATES))
        for p in _TEMPLATES.rglob("*.html")
        if "page-narrow" in p.read_text() and "<form" in p.read_text()
    }
    assert narrow_forms - _NARROW_ALLOWED == set()


# ---------------------------------------------------------------------------
# F7: the diversion record forms
# ---------------------------------------------------------------------------

_DIVERSION_FORMS = [
    "surface/partials/_diversion_form.html",
    "surface/partials/_diversion_record_edit_form.html",
]


@pytest.mark.parametrize("name", _DIVERSION_FORMS)
def test_diversion_record_form_is_a_grid(name):
    """RED before: the form's class was the undefined `form-stack` (the first
    assertion) and its fields sat in `.form-row-2col` rows."""
    text = (_TEMPLATES / name).read_text()
    (classes,) = _form_classes(text)
    assert "form-grid" in classes
    assert "form-stack" not in classes
    assert "form-row-2col" not in text


def test_diversion_record_form_is_at_the_cards_width():
    """ISS-201 ("the add-record form at 45% width"): the wrapper around the two
    forms capped them at 640 px inside a full-width card. RED before."""
    text = (_TEMPLATES / "surface/partials/_diversion_records.html").read_text()
    assert "max-width: 640px" not in text


# ---------------------------------------------------------------------------
# Rendered pages
# ---------------------------------------------------------------------------

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "source", "track", "wbr",
}


class _Region(HTMLParser):
    """The first element whose class carries `cls`: its direct children's
    (tag, class tokens) and the ids of every element inside it."""

    def __init__(self, cls):
        super().__init__()
        self.cls = cls
        self.depth = None
        self.done = False
        self.root_tag = None
        self.root_classes = set()
        self.children = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if self.depth is None:
            if self.cls in classes:
                self.depth = 0
                self.root_tag = tag
                self.root_classes = classes
            return
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if self.depth == 0:
            self.children.append((tag, classes))
        if tag not in _VOID:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.done or self.depth is None or tag in _VOID:
            return
        if self.depth == 0:
            self.done = True
        else:
            self.depth -= 1


def _region(html, cls):
    parser = _Region(cls)
    parser.feed(html)
    return parser


def _superuser_client():
    user = User.objects.create_user(
        username="form-grid-admin", email="form-grid-admin@example.com",
        password="x", is_active=True, is_staff=True, is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_ledger_create_renders_the_grid_with_its_pairs():
    """F1, the proving page: the use area and the description span both tracks,
    and Source type sits beside the water year (149.1-05's last fault: two
    half-width selects each alone on a row). RED before: no `form-grid`, and
    the description rendered between source type and water year."""
    resp = _superuser_client().get(reverse("accounting:ledger_create"))
    assert resp.status_code == 200
    html = resp.content.decode()
    form = _region(html, "form-grid")
    assert form.root_tag == "form"
    spanning = [classes for tag, classes in form.children if "form-span-2" in classes]
    assert len(spanning) == 2  # the use area and the description
    assert (
        html.index('id="id_source_type"')
        < html.index('id="id_reporting_period"')
        < html.index('id="id_description"')
    )
    assert 'class="page-stack page-medium"' in html


def _step_form(html, step):
    """The config form of one methodology step: its opening tag and its body."""
    url = reverse("accounting:methodology_step_config", args=[step.pk])
    start = html.rindex("<form", 0, html.index(f'hx-post="{url}"'))
    end = html.index("</form>", start)
    return html[start:html.index(">", start) + 1], html[start:end]


def _classes_of(tag):
    match = _CLASS_ATTR.search(tag)
    return set(match.group(1).split()) if match else set()


@pytest.mark.django_db
def test_methodology_step_forms_are_on_the_grid():
    """F2, F3: a step with options is `.form-grid` with its step-name group
    across both tracks; a step with no options is one row (`.form-grid--row`).
    The inline 12rem auto-fit grid is gone. RED before: the inline grid's
    `minmax(12rem` was on the page (the first assertion), and the form tag
    carried no class at all."""
    from accounting.models import CalculationPlan

    call_command("seed_calculation_plan")
    html = _superuser_client().get(reverse("accounting:methodology_settings")).content.decode()
    assert "minmax(12rem" not in html
    steps = list(CalculationPlan.active().steps.order_by("order"))
    with_options = {"subtract_effective_precip", "clamp_floor"}
    assert {s.step_type for s in steps} >= with_options | {"et_gross"}
    for step in steps:
        tag, body = _step_form(html, step)
        classes = _classes_of(tag)
        assert "form-grid" in classes, step.step_type
        name_at = body.index('name="label"')
        group = body[body.rindex("<div", 0, name_at):]
        group_classes = _classes_of(group[:group.index(">") + 1])
        if step.step_type in with_options:
            assert "form-grid--row" not in classes, step.step_type
            assert "form-span-2" in group_classes, step.step_type
        else:
            assert "form-grid--row" in classes, step.step_type
            assert "form-span-2" not in group_classes, step.step_type
    # The precipitation step's live-field hooks are untouched: three elements
    # carry the class (the script at the partial's end names it a fourth time).
    assert len(re.findall(r'class="[^"]*\bjs-precip-field\b', html)) == 3
    assert re.search(r'class="[^"]*\bjs-precip-method\b', html)
    for method in ("fraction", "usda_scs", "raw"):
        assert f'data-precip-method="{method}"' in html


@pytest.mark.django_db
def test_wizard_boundary_cards_stay_stacked():
    """S16, after the read: side by side the two cards read DO NOT SHIP 3 on their
    mismatched heights, so they stack as before (VERDICTS-150-04.md). Pins the
    absence of the `.card-columns` wrapper and the several-polygons line on the page."""
    html = _superuser_client().get(reverse("setup:wizard")).content.decode()
    assert "card-columns" not in html
    assert "When the file holds several polygons" in html


@pytest.mark.django_db
def test_delivery_settings_stay_one_column_at_the_medium_measure():
    """S5, after the read: three across read DO NOT SHIP 2 on unequal heights; the
    single column at the medium measure stays."""
    html = _superuser_client().get(reverse("accounting:delivery_settings")).content.decode()
    assert "card-columns" not in html
    assert 'class="page-stack page-medium"' in html
    assert "page-head--medium" in html
