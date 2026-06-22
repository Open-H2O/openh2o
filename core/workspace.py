# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared rendering helpers for the master-detail workspace screens (v2.0).

Every workspace screen answers the same two HTMX questions with the same logic:

  * the LIST view returns just the results partial for an in-place list refresh
    (search / filter / pagination, which target ``#results``) and the full
    workspace page otherwise; and
  * the DETAIL view returns just the detail-pane fragment for an in-place row
    swap (target ``#detail-body``) and the standalone page otherwise (deep
    links, no-JS clients).

These two helpers collapse that ``if request.headers.get("HX-Request")`` branch
so each screen's views stay declarative and consistent. The signal is HTMX's
``HX-Request`` header, which it sets on every request it issues.
"""
from django.shortcuts import render


def list_response(request, *, page_template, results_template, context):
    """Full workspace page on a normal load; the results partial on an HTMX swap."""
    template = results_template if request.headers.get("HX-Request") else page_template
    return render(request, template, context)


def detail_response(request, *, pane_template, page_template, context):
    """Standalone detail page on a normal load; the pane fragment on an HTMX swap."""
    template = pane_template if request.headers.get("HX-Request") else page_template
    return render(request, template, context)
