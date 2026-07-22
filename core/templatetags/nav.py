# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sidebar helpers.

One filter, existing for one reason: a nav entry can carry MORE THAN ONE
active-state exclusion, and Django's template language cannot express "none of
these substrings appear in the path". A ``{% for %}`` cannot AND its iterations
together, so the check has to happen in Python.

The decision itself lives on ``NavEntry.is_active`` — pure string work, unit
testable without rendering anything. This module is only the bridge that lets a
template pass ``request.path`` into it.
"""
from django import template

register = template.Library()


@register.filter
def nav_active(entry, path):
    """``{% if entry|nav_active:request.path %}`` — is this the active link?"""
    return entry.is_active(path or "")


@register.simple_tag
def explainer_available(name):
    """``{% explainer_available "methods" as show %}`` — is that Help page served?

    Plan 89-02. The five explainer pages are hidden when the deployment does not
    run the domain they explain, and the view raises ``Http404`` when it is asked
    for one anyway (``config/views.py::EXPLAINER_MODULES``). The sidebar reads the
    SAME predicate rather than repeating the module list, so a link into a hidden
    page cannot be created by editing one of the two and forgetting the other —
    which is the shape of every dead link this milestone has had to chase.

    Imported inside the function because ``config.views`` imports models from
    several apps, and a module-scope import here would drag them into the
    template-tag discovery that runs at app-registry population time.
    """
    from config.views import explainer_is_available

    return explainer_is_available(name)
