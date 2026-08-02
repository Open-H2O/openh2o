# SPDX-License-Identifier: AGPL-3.0-or-later
"""An empty field says what it means, and says it the same way everywhere.

Phase 105's copy half. Ninety-two templates rendered ``default:"—"`` for a
missing value, which tells a reader nothing: a dash cannot distinguish "nobody
recorded this" from "this does not apply" from "the page broke". The
``blank`` filter (``core/templatetags/placeholders.py``) replaced all of them
with wording in a ``.value-empty`` span.

Two kinds of assertion live here, and the split is deliberate. The first three
tests pin the filter's *contract* -- pass-through, placeholder, escaping --
because a filter that silently stopped escaping would be a vulnerability nobody
would notice by looking at a page. The last one is a repo guard: it greps the
templates and fails if a bare em-dash placeholder comes back. Sweeps do not
stay swept on their own, and the next person to copy-paste a detail-pane row
should be told by the suite rather than by a reviewer six months later.
"""

from pathlib import Path

from django.conf import settings
from django.template import Context, Template


def _render(template_string, **context):
    return Template("{% load placeholders %}" + template_string).render(
        Context(context)
    )


class TestTheFilterContract:
    def test_a_present_value_passes_through_unchanged(self):
        assert _render("{{ v|blank }}", v="Domestic") == "Domestic"

    def test_a_present_value_is_still_escaped(self):
        """The filter returns a plain string, so Django autoescapes it exactly
        as it did before the filter existed. A regression here would turn every
        converted field into a stored-XSS sink."""
        out = _render("{{ v|blank }}", v="<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_an_empty_value_renders_wording_in_a_quiet_span(self):
        assert (
            _render("{{ v|blank }}", v="")
            == '<span class="value-empty">Not recorded</span>'
        )

    def test_none_renders_the_placeholder_too(self):
        assert "Not recorded" in _render("{{ v|blank }}", v=None)

    def test_a_caller_may_supply_its_own_wording(self):
        out = _render('{{ v|blank:"No expiry recorded" }}', v=None)
        assert out == '<span class="value-empty">No expiry recorded</span>'

    def test_a_caller_supplied_label_is_escaped(self):
        out = _render('{{ v|blank:"<b>x</b>" }}', v=None)
        assert "<b>" not in out


class TestTheSweepHolds:
    def test_no_template_renders_a_bare_em_dash_placeholder(self):
        """``default:"—"`` is the pattern this phase retired. It is easy to
        reintroduce by copying a neighbouring row, and it looks correct in a
        diff, so the suite is the only thing that will catch it."""
        root = Path(settings.BASE_DIR) / "templates"
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.html")
            if 'default:"—"' in path.read_text()
        ]
        assert not offenders, (
            "these templates still use a bare em dash for an empty value; use "
            f"the `blank` filter instead: {offenders}"
        )

    def test_the_empty_style_exists(self):
        """The filter emits `.value-empty`. If the class is not in the
        stylesheet the placeholder renders at full body weight and reads as a
        real value -- the exact confusion this phase set out to remove."""
        css = (Path(settings.BASE_DIR) / "static/css/app.css").read_text()
        assert ".value-empty" in css
