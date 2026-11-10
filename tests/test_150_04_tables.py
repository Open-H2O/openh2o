"""150-04, the TABLE class: the rules that let a table header pin to the document and keep a wide
table inside its card (ISS-167, fault 4, the ledger at 1,024). Static checks on the stylesheet and
the templates; the geometry itself was measured in the browser (LAYOUT-INVENTORY-150-04.md).
"""
import re
from pathlib import Path

import pytest
from django.conf import settings

BASE = Path(settings.BASE_DIR)
# Comments go before matching: a `{ ... }` quoted inside a comment would end a rule early.
APP_CSS = re.sub(r"/\*.*?\*/", "", (BASE / "static" / "css" / "app.css").read_text(), flags=re.S)
BASE_HTML = (BASE / "templates" / "base.html").read_text()


def _rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", APP_CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_the_content_pane_is_not_a_scroll_container():
    body = _rule(".app-content")
    assert "overflow-y: visible" in body
    assert "overflow-x: clip" in body
    assert "overflow-y: auto" not in body


def test_the_table_header_still_asks_to_pin():
    assert "position: sticky" in _rule(".data-table thead th")


def test_the_base_layout_loads_the_table_scroll_script():
    assert "js/table-scroll.js" in BASE_HTML
    assert (BASE / "static" / "js" / "table-scroll.js").exists()


def test_a_fitting_wrapper_is_not_a_scroll_container_and_an_overflowing_one_holds_its_first_column():
    assert "overflow-x: visible" in _rule('.table-scroll[data-overflow="false"]')
    assert 'position: sticky' in _rule(
        '.table-scroll[data-overflow="true"] .data-table th:first-child,\n'
        '.table-scroll[data-overflow="true"] .data-table td:first-child'
    )


def test_the_ledger_padding_rule_from_phase_75_is_gone():
    assert ".app-content:has(#ledger-filters)" not in APP_CSS


def test_no_badge_colour_is_hard_coded():
    for selector in (".badge-red", ".badge-grey"):
        body = _rule(selector)
        assert "oklch(" not in body and "rgba(" not in body, selector


def test_the_onboarding_review_table_takes_its_widths_from_a_colgroup():
    # 152-03.4 row 11: a fifth, a quarter and the rest, not equal thirds.
    html = (BASE / "templates" / "drinking" / "partials" / "_onboard_review.html").read_text()
    assert "help-cases-table--even" not in html
    assert "onboard-cases-table" in html
    colgroup = html.split("<colgroup>", 1)[1].split("</colgroup>", 1)[0]
    assert re.findall(r"width:\s*(\d+)%", colgroup) == ["18", "26", "56"]
    assert "table-layout: fixed" in _rule(".onboard-cases-table")


def test_the_even_columns_class_is_still_used_by_the_onboarding_page():
    html = (BASE / "templates" / "drinking" / "onboard.html").read_text()
    assert "help-cases-table--even" in html
    assert ".help-cases-table--even" in APP_CSS


@pytest.mark.parametrize(
    "path",
    sorted(str(p.relative_to(BASE)) for p in (BASE / "templates").rglob("*.html")),
)
def test_no_table_wrapper_carries_an_inline_overflow(path):
    html = (BASE / path).read_text()
    for m in re.finditer(r'class="[^"]*\btable-scroll\b[^"]*"[^>]*>', html):
        assert "overflow" not in m.group(0), f"{path}: {m.group(0)[:80]}"
