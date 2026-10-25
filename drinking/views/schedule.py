# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sampling schedule: the operator's checklist and its add and edit forms."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from drinking.forms import SamplingScheduleForm
from drinking.models import SamplingSchedule, WaterSystem


# ---------------------------------------------------------------------------
# The sampling schedule (146-04 Task 4, D8)
# ---------------------------------------------------------------------------


@login_required
def schedule(request):
    """The operator's sampling checklist, by the date they set.

    Earliest date first (the model's ordering), so a date that has passed
    leads the list; rows with no date last. A passed date is worded as the
    operator's own ("past the date you set") and never as a verdict: the
    platform holds the schedule and does not judge it.
    """
    system = WaterSystem.objects.order_by("pwsid").first()
    rows = (
        SamplingSchedule.objects.filter(system=system)
        .select_related("analyte", "sampling_point")
        if system is not None
        else SamplingSchedule.objects.none()
    )
    return render(
        request,
        "drinking/schedule.html",
        {"system": system, "rows": rows, "today": timezone.localdate()},
    )


@login_required
def schedule_add(request):
    """Add one row to the schedule; no system yet says Onboard first."""
    system = WaterSystem.objects.order_by("pwsid").first()
    if system is None:
        return render(request, "drinking/schedule_form.html", {"system": None})

    if request.method == "POST":
        form = SamplingScheduleForm(request.POST, system=system)
        if form.is_valid():
            form.save()
            return redirect("drinking:schedule")
    else:
        form = SamplingScheduleForm(system=system)
    return render(
        request,
        "drinking/schedule_form.html",
        {"form": form, "system": system, "row": None},
    )


@login_required
def schedule_edit(request, pk):
    """Edit one schedule row: typically the two dates, after a sample is taken."""
    row = get_object_or_404(SamplingSchedule.objects.select_related("system"), pk=pk)
    if request.method == "POST":
        form = SamplingScheduleForm(request.POST, instance=row, system=row.system)
        if form.is_valid():
            form.save()
            return redirect("drinking:schedule")
    else:
        form = SamplingScheduleForm(instance=row, system=row.system)
    return render(
        request,
        "drinking/schedule_form.html",
        {"form": form, "system": row.system, "row": row},
    )
