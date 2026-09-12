# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bridges ``accounting/ledger_words.py``'s pure function into templates.

The decision itself lives in ``ledger_row_words()`` -- pure, unit-testable
without rendering anything. This module is only the bridge that lets a
template pass a ``ParcelLedger`` row into it. Both
``templates/accounting/partials/_ledger_list_results.html`` and
``templates/parcels/partials/_detail_pane.html`` load this filter, which is
the whole point of it living here rather than being computed twice: the two
pages cannot say the same row two different ways.
"""
from django import template

from accounting.ledger_words import ledger_row_words as _ledger_row_words

register = template.Library()


@register.filter
def ledger_row_words(entry):
    """``{{ entry|ledger_row_words }}`` -- the merged Water column's text."""
    return _ledger_row_words(entry)
