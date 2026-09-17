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
from django.shortcuts import redirect, render
from django.urls import reverse


def list_response(request, *, page_template, results_template, context):
    """Full workspace page on a normal load; the results partial on an HTMX swap."""
    template = results_template if request.headers.get("HX-Request") else page_template
    return render(request, template, context)


def redirect_to_selected(request, url_name, pk):
    """Where a finder's old ``?selected=<pk>`` deep link lands (143-13).

    Use Areas, Wells and Water accounts were master-detail workspaces
    (`workspace.html`) whose ``?selected=<pk>`` pre-rendered the record's
    detail INTO the same page. Candidate A ("the list is the page") removed
    that shell, so the same query param now redirects straight to the
    record's own detail page instead: old links keep working, they just
    land on a full page rather than a pane.

    Every OTHER query param carries forward (minus ``selected`` itself), so a
    link like ``?selected=12&period=7`` still opens use area 12 on period 7:
    the detail views already read ``?period=`` themselves, and dropping it
    here would silently reset a reader's chosen period on every old link.
    """
    query = request.GET.copy()
    query.pop("selected", None)
    url = reverse(url_name, kwargs={"pk": pk})
    if query:
        url = f"{url}?{query.urlencode()}"
    return redirect(url)


def detail_response(request, *, pane_template, page_template, context):
    """Standalone detail page on a normal load; the pane fragment on an HTMX swap."""
    template = pane_template if request.headers.get("HX-Request") else page_template
    return render(request, template, context)
