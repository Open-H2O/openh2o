# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keep the reading on a link to a page that reads a date.

The account page, the use area page and the Use Ledger each read ``?as_of=<day>``. While
the current page is a reading, a link to one of them carries the same day, so the reader
arrives on a reading and not on today's page. ``as_of_value`` comes from
:func:`core.context_processors.as_of_flags` and is empty when the page is not a reading;
then both tags print nothing and the link is exactly as it was.

* ``{% as_of_first %}`` goes after an href with no query string: ``?as_of=2026-11-03``.
* ``{% as_of_more %}`` goes after an href that already has one: ``&amp;as_of=2026-11-03``.
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def as_of_first(context):
    day = context.get("as_of_value")
    return f"?as_of={day}" if day else ""


@register.simple_tag(takes_context=True)
def as_of_more(context):
    day = context.get("as_of_value")
    return f"&as_of={day}" if day else ""
