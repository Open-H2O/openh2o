"""150-04, the CLASS class (ISS-166): four classes the templates named and nothing defined.
`font-semibold`, `text-primary` and `row-clickable` now have rules at the end of
static/css/app.css; `form-stack` is gone from the templates, because every block it wrapped
already spaces itself with `.form-group`. The general guard (every template class is defined or
allowlisted) is tests/test_template_hygiene.py::TestEveryTemplateClassIsDefined; these pin the
four rows themselves.
"""
import re
from pathlib import Path

import pytest
from django.conf import settings

BASE = Path(settings.BASE_DIR)
TEMPLATES = BASE / "templates"
APP_CSS = (BASE / "static" / "css" / "app.css").read_text()

ROW_CLICKABLE_TEMPLATES = [
    "wells/partials/_list_results.html",
    "parcels/partials/_list_results.html",
    "recharge/partials/_list_results.html",
    "surface/partials/_list_results.html",
    "surface/partials/_pod_list_results.html",
    "geography/partials/_zone_list_results.html",
    "datasync/partials/_station_list_results.html",
    "reporting/partials/_report_history.html",
]


def _rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", APP_CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_c1_font_semibold_is_weight_600():
    assert "font-weight: 600" in _rule(".font-semibold")


def test_c4_text_primary_is_the_primary_text_token():
    assert "color: var(--color-text-primary)" in _rule(".text-primary")


def test_c3_row_clickable_carries_the_pointer():
    assert "cursor: pointer" in _rule(".row-clickable")


@pytest.mark.parametrize("name", ROW_CLICKABLE_TEMPLATES)
def test_c3_a_clickable_row_takes_its_pointer_from_the_class_not_an_inline_style(name):
    """RED before: each of the eight rows was `<tr class="row-clickable" style="cursor: pointer;"`."""
    text = (TEMPLATES / name).read_text()
    rows = re.findall(r"<tr\b[^>]*\brow-clickable\b[^>]*>", text, re.S)
    assert rows, f"{name} has no row-clickable row"
    for row in rows:
        assert "style=" not in row, f"{name}: {row}"
        assert "onclick=" in row, f"{name}: the row lost its link"


@pytest.mark.parametrize("name", ["infrastructure/add.html", "geography/zone_create.html"])
def test_c2_form_stack_is_gone_and_the_fields_keep_their_form_group(name):
    """RED before: add.html carried `form-stack` seven times, zone_create.html twice."""
    text = (TEMPLATES / name).read_text()
    assert "form-stack" not in text
    assert text.count('class="form-group"') >= 5
