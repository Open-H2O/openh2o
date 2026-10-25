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
from accounting.services import balance_state as _balance_state

register = template.Library()


@register.filter
def ledger_row_words(entry):
    """``{{ entry|ledger_row_words }}`` -- the merged Water column's text."""
    return _ledger_row_words(entry)


_BALANCE_CLASS = {"surplus": "text-surplus", "deficit": "text-deficit", "balanced": ""}


@register.filter
def balance_class(value):
    """``{{ balance|balance_class }}`` -- the colour class for a water balance.

    Judged on the two decimals the page prints: a balance that prints
    0.00 is balanced and takes the plain text colour, never green or orange.
    """
    return _BALANCE_CLASS.get(_balance_state(value), "")
