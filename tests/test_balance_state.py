# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-237: a water balance is judged on the two decimals the page prints.

A field with no meter closes at zero by construction, but its monthly figures
are stored to four places, so a year's sum lands at a few ten-thousandths of an
acre-foot either side of zero. On staging (2026-10-12) MER-ACCT-002 summed to
+0.0001 AF and MER-ACCT-006 to -0.0003 AF; both printed 0.00, and the Dashboard
counted one in surplus and the other in deficit. Such a balance is "Balanced":
a balance that prints 0.00 is neither.
"""
from decimal import Decimal

import pytest
from django.template import Context, Template

from accounting.services import balance_state


@pytest.mark.parametrize("value, state", [
    (Decimal("0.0001"), "balanced"),
    (Decimal("-0.0003"), "balanced"),
    (Decimal("0"), "balanced"),
    (Decimal("-0.0049"), "balanced"),
    (Decimal("0.005"), "surplus"),
    (Decimal("-0.005"), "deficit"),
    (Decimal("47.42"), "surplus"),
    (Decimal("-1799.84"), "deficit"),
])
def test_balance_state_follows_the_printed_figure(value, state):
    assert balance_state(value) == state


def test_no_measurement_has_no_state():
    assert balance_state(None) is None


def test_the_two_staging_accounts_print_the_same_and_take_the_same_colour():
    t = Template("{% load accounting_extras %}[{{ a|balance_class }}][{{ b|balance_class }}][{{ c|balance_class }}][{{ d|balance_class }}]")
    out = t.render(Context({
        "a": Decimal("0.0001"), "b": Decimal("-0.0003"),
        "c": Decimal("47.42"), "d": Decimal("-24.40"),
    }))
    assert out == "[][][text-surplus][text-deficit]"
