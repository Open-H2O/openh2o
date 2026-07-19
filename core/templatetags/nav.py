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
