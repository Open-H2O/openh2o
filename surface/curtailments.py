# SPDX-License-Identifier: AGPL-3.0-or-later
"""The curtailment matching rule (146-02 Task 4, ISS-180 D6).

`orders_that_may_apply` is the rule the right's page calls to decide which
curtailment orders belong on its "Curtailment orders that may apply" panel.
It is a lookup, not a legal determination -- the order's own text governs, and
the panel says so in its footer.

The rule was written on an observation, not memory: `146-02-EVIDENCE.md` Task 4
step 1 verified on a real shape-1 instance, before this module existed, that
the previous filter (`priority_date_cutoff__gte=priority_date`) flagged the
SENIOR right and ignored the order's watershed -- the opposite direction from
the one order read in step 2 (one order, not a survey). Task 4 step 2 read
one such order (State Water Board, August 20, 2021, "INITIAL ORDER IMPOSING
WATER RIGHT CURTAILMENT AND REPORTING REQUIREMENTS IN THE SACRAMENTO-SAN
JOAQUIN DELTA WATERSHED", https://www.waterboards.ca.gov/drought/delta/docs/082021_order_sm.pdf)
and quoted its item 3: pre-1914 claims in the Sacramento River watershed and
the Legal Delta are curtailed "with a priority date of 1883 or later" -- the
JUNIOR side of the cutoff. See `146-02-EVIDENCE.md` Task 4 section 2 for the
full quotation and section "The rule" for the derivation.

An active order applies to a right when all three hold:
  (a) the order's `effective_date` is on or before today, its `end_date` is
      null or on or after today, and its `status` is "active";
  (b) the order's `watershed` is blank (meaning "as stated on the order"), OR
      it matches the right's `watershed` or `source_name` case-insensitively;
  (c) the right's `priority_date` is on or after the order's
      `priority_date_cutoff` (the junior side) -- an order with no cutoff
      matches on (a) and (b) alone.
A right with no priority date on record can never be tested against (c), so
it is never silently dropped: it is returned separately, under every order
that passes (a) and (b), so the panel can say plainly that the right cannot be
matched for want of a date.
"""
from datetime import date

from django.db.models import Q

from surface.models import CurtailmentOrder


def orders_that_may_apply(water_right, today=None):
    """Return `(matched, unmatched_for_want_of_a_date)` for `water_right`.

    `matched` is the list of active `CurtailmentOrder` rows the right's own
    priority date falls under, newest effective date first. `unmatched` is
    the list of active, watershed-matching orders that could not be tested
    because the right carries no priority date -- always empty when the right
    has one.
    """
    if today is None:
        today = date.today()

    candidates = (
        CurtailmentOrder.objects.filter(status="active", effective_date__lte=today)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .order_by("-effective_date")
    )

    right_watershed = (water_right.watershed or "").strip().lower()
    right_source = (water_right.source_name or "").strip().lower()

    def watershed_matches(order):
        order_watershed = (order.watershed or "").strip().lower()
        if not order_watershed:
            return True
        return order_watershed in (right_watershed, right_source)

    passing_watershed = [c for c in candidates if watershed_matches(c)]

    if water_right.priority_date is None:
        return [], passing_watershed

    matched = [
        order
        for order in passing_watershed
        if order.priority_date_cutoff is None
        or water_right.priority_date >= order.priority_date_cutoff
    ]
    return matched, []
