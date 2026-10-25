# SPDX-License-Identifier: AGPL-3.0-or-later
"""The water system overview: identity card, published aggregates and links to the lists."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone
from drinking.models import (
    SampleResult,
    SamplingPoint,
    SamplingSchedule,
    WaterSystem,
)


_POPULATION_SPLIT_FIELDS = (
    "population_residential",
    "population_non_transient",
    "population_transient",
)


_CONNECTION_SPLIT_FIELDS = (
    "connections_agricultural",
    "connections_combined",
    "connections_commercial",
    "connections_industrial",
    "connections_residential",
)


@login_required
def overview(request):
    """The water system's front door: who it is, what EPA publishes, where to go.

    Not an inventory. The 61-row facility table that used to live at the bottom
    of this page moved to :func:`facilities`, where it can be searched; what is
    left is the identity card, EPA's two published aggregates, and three counts
    that route to the three lists.

    Usually one system row, like SiteConfig — but a table, so a wholesaler or a
    consecutive system can be carried alongside.
    """
    systems = list(
        WaterSystem.objects
        .annotate(facility_count=Count("facilities", distinct=True))
        .order_by("pwsid")
    )

    # Two aggregate queries keyed by system id, zipped on in Python. NOT a
    # per-system .count() inside the loop (which grows with the row count), and
    # NOT a second Count() annotation on the queryset above: multiple joins on
    # one queryset multiply each other's counts, which is the exact bug the
    # sampling-points view's own comment warns about. Three queries total, at
    # one system or at thirty.
    point_counts = {
        row["facility__system"]: row["n"]
        for row in SamplingPoint.objects
        .values("facility__system")
        .annotate(n=Count("id"))
    }
    result_counts = {
        row["event__sampling_point__facility__system"]: row["n"]
        for row in SampleResult.objects
        .values("event__sampling_point__facility__system")
        .annotate(n=Count("id"))
    }

    # The one "next due" line. One query for every
    # system's dated rows, earliest first, and the first per system kept in
    # Python -- the same no-per-system-query rule as the two aggregates above.
    next_due = {}
    for row in (
        SamplingSchedule.objects.filter(next_due__isnull=False)
        .select_related("analyte")
        .order_by("next_due", "pk")
    ):
        next_due.setdefault(row.system_id, row)

    today = timezone.localdate()
    for system in systems:
        system.next_due_row = next_due.get(system.pk)
        # Worded the way the schedule page words it: the operator's date,
        # passed, and never a verdict on it.
        system.next_due_passed = bool(
            system.next_due_row and system.next_due_row.next_due < today
        )
        system.sampling_point_count = point_counts.get(system.pk, 0)
        system.result_count = result_counts.get(system.pk, 0)
        # One boolean each, computed here rather than as eight chained {% if %}s
        # in the template. The splits render only when the deployment actually
        # holds one; otherwise the page says where they come from, because a
        # sentence naming the missing source is information and a column of
        # em-dashes is not.
        system.has_population_splits = any(
            getattr(system, name) is not None for name in _POPULATION_SPLIT_FIELDS
        )
        system.has_connection_splits = any(
            getattr(system, name) is not None for name in _CONNECTION_SPLIT_FIELDS
        )
        # The state each step of the sequence is in, computed here and
        # NEVER written into the template. The demonstration happens to hold 61
        # facilities, 27 points and 22,367 results; an onboarded system holds
        # none of those, and a numeral typed into the eyebrow would be a
        # sentence that is right on exactly one deployment.
        #
        # Derived from the three counts already gathered above — no fourth
        # aggregate query. Step 1 is done by definition inside the loop: this
        # system exists, so it was onboarded (or admin-created, which is the
        # same evidence).
        system.step_onboard_done = True
        system.step_points_done = system.sampling_point_count > 0
        system.step_results_done = system.result_count > 0

    return render(request, "drinking/overview.html", {"systems": systems})
