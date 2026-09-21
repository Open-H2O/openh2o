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
from accounting.ledger_words import sign_rule_sentence as _sign_rule_sentence

register = template.Library()


@register.filter
def ledger_row_words(entry):
    """``{{ entry|ledger_row_words }}`` -- the merged Water column's text."""
    return _ledger_row_words(entry)


@register.simple_tag
def sign_rule_sentence(recharge_enabled=True, surface_enabled=True):
    """``{% sign_rule_sentence recharge_enabled surface_enabled %}`` -- the
    one sign rule, quoted verbatim.

    ISS-196: every door that shows a ledger figure says this sentence, not
    its own version of it. The words themselves live in
    ``accounting.ledger_words``, this is only the bridge into a template.
    The two flags (pass the view's own ``is_enabled("recharge")`` /
    ``is_enabled("surface")`` context values) drop "recharge credits" /
    "surface diversions" from the sentence on a deployment without that
    module, the same module-neutral move the page description one line
    above already makes.
    """
    return _sign_rule_sentence(
        recharge_enabled=recharge_enabled, surface_enabled=surface_enabled
    )
