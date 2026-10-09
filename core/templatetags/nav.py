# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sidebar helpers.

``nav_active`` marks the one lit link. Since 150-03 the decision is made once
per request, for the whole sidebar, by ``core.modules.lit_entry`` (the longest
owning prefix wins), and reaches templates as ``nav_lit``, the winning entry's
url_name, from the ``modules`` context processor. Deciding per entry, as
``NavEntry.is_active`` did, let two entries light at once (Map and Zones on
``/map/zones/``, R-098) and left pages with no entry of their own dark (R-028).
This module is only the bridge that lets a template ask "is this the one".
"""
from django import template

register = template.Library()


@register.filter
def nav_active(entry, lit):
    """``{% if entry|nav_active:nav_lit %}``: is this entry the page's lit one?"""
    return bool(lit) and entry.url_name == lit


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
