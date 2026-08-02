# SPDX-License-Identifier: AGPL-3.0-or-later
"""One wording for "this field is empty", instead of ninety-two bare em dashes.

``{{ well.well_type|default:"—" }}`` was the house habit, and a dash is not
wording -- it is the absence of wording. A reader looking at a detail pane full
of dashes cannot tell apart "the agency never recorded this", "this does not
apply to this kind of record", and "the page failed to load it". The Supply vs.
Use panel already showed the better answer by saying "Not calculated" in
tertiary gray, and this filter makes that the pattern everywhere else::

    {{ well.well_type|blank }}                  -> "Not recorded"
    {{ right.expiry_date|blank:"No expiry" }}   -> a caller-supplied wording

**Falsy, not None** -- deliberately the same trigger Django's own ``default``
filter uses, because every call site this replaced was a ``default:"—"`` and
changing *when* the placeholder appears while changing *what it says* would
hide a rendering change inside a copy change. The known wart rides along: a
literal ``0`` is falsy, so a numeric field showing zero renders the placeholder.
No call site converted here is numeric (they are names, identifiers, type
labels, and dates); a numeric one should use ``default_if_none`` instead, and
this docstring is the reason why.

The markup, not just the string, is the point: the placeholder ships wrapped in
``.value-empty`` so an empty field is visibly quieter than a filled one, and so
the whole platform's empty styling lives in one CSS rule rather than in ninety-
two templates.
"""

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def blank(value, label="Not recorded"):
    """``value``, or ``label`` styled as an empty field when it is falsy.

    A present value is returned unchanged and untouched -- it is a plain string,
    so Django autoescapes it at render exactly as it did before this filter
    existed. Only the placeholder branch returns marked-safe markup, and the
    label is escaped on the way in so a caller-supplied wording cannot inject.
    """
    if value:
        return value
    return mark_safe(f'<span class="value-empty">{escape(label)}</span>')
