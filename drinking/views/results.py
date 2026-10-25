# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sample-result list and the detail page for one result."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from core.workspace import list_response
from drinking.models import Analyte, SampleResult, SamplingPoint
from drinking.views.common import group_results_by_event


@login_required
def results(request):
    """The sample-result log — the workhorse surface.

    Filters are plain GET params (analyte, sampling point, date range) so a
    filtered view is a shareable URL. Every result is rendered through its
    ``result_kind``: a presence/absence row can never appear as a number, which
    is the whole reason that discriminator exists.
    """
    analyte_id = request.GET.get("analyte", "").strip()
    point_id = request.GET.get("sampling_point", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    queryset = (
        SampleResult.objects
        .select_related(
            "analyte",
            "event",
            "event__sampling_point",
            "event__sampling_point__facility",
            "event__sampling_point__facility__system",
        )
        # An event IS one date at one point (R-070/R-071): ordering by point
        # and event id after the date keeps a whole event's rows contiguous,
        # so two points sampled the same day render as two groups rather than
        # interleaving by analyte the way the old `analyte__name`-only
        # tiebreak did.
        .order_by(
            "-event__sample_date",
            "event__sampling_point__ps_code",
            "event_id",
            "analyte__name",
        )
    )

    if analyte_id.isdigit():
        queryset = queryset.filter(analyte_id=analyte_id)
    if point_id.isdigit():
        queryset = queryset.filter(event__sampling_point_id=point_id)
    # Parsed, not passed through. An unparseable date reaching the ORM raises
    # ValidationError -> 500; a hand-edited or truncated URL should degrade to
    # the unfiltered list instead of an error page.
    parsed_from = parse_date(date_from) if date_from else None
    parsed_to = parse_date(date_to) if date_to else None
    if parsed_from:
        queryset = queryset.filter(event__sample_date__gte=parsed_from)
    if parsed_to:
        queryset = queryset.filter(event__sample_date__lte=parsed_to)

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return list_response(
        request,
        page_template="drinking/results.html",
        results_template="drinking/partials/_result_results.html",
        context={
            "page_obj": page_obj,
            "total_count": paginator.count,
            "result_groups": group_results_by_event(page_obj.object_list),
            "analyte_id": analyte_id,
            "point_id": point_id,
            "date_from": date_from,
            "date_to": date_to,
            "analytes": Analyte.objects.filter(results__isnull=False).distinct(),
            "sampling_points": SamplingPoint.objects.order_by("ps_code"),
            "has_any": SampleResult.objects.exists(),
        },
    )


#: The State Water Board's Consumer Confidence Report viewer.
#:
#: Verified live 2026-07-27: returns HTTP 200 ``application/pdf``. It is a
#: CALIFORNIA service, which is why ``_ccr_url`` gates on the PWSID's prefix —
#: a New Mexico or federal PWSID would compose a link that 404s while looking
#: authoritative, and an authoritative-looking dead link is worse than none.
CCR_VIEWER_URL = "https://ear.waterboards.ca.gov/Home/ViewCCR?PwsID={pwsid}&Year={year}"


def _ccr_is_published(year, today):
    """Has the CCR covering ``year`` been delivered yet?

    40 CFR 141.155(a): a community water system delivers its Consumer Confidence
    Report **by July 1 annually**, and that report covers the **previous**
    calendar year. So the report for year Y does not exist until July 1 of Y+1 —
    a sample taken this year has no annual report at all, and one taken last year
    has none until this July.

    Measured against the live viewer for CA2410009 on 2026-07-28, which this rule
    reproduces exactly: 2020-2024 and 2025 all answer 200, and 2026 answers 404.
    """
    return (today.year, today.month) >= (year + 1, 7)


def _ccr_url(system, sample_date, today=None):
    """The system's annual CCR for the year this sample was taken, or None.

    **This is not the sample's own lab sheet**, and the page must not imply it
    is. Per-sample analytical PDFs are published by nobody: Envirofacts is
    tabular REST with no document endpoint, and California labs submit through
    CLIP as data. The system's annual report for that year is the nearest
    published document that exists, so it is offered as exactly that.

    Two gates, and both exist to avoid the same failure — an authoritative-looking
    link that 404s:

    * **The state.** The viewer is a California State Water Board service, so a
      New Mexico or federal PWSID would compose a link to a report that service
      never held.
    * **The year.** See ``_ccr_is_published``. The demonstration data runs to
      2026-05-21, so without this gate the newest samples on the busiest surface
      in the module all link to a 404.
    """
    pwsid = (system.pwsid or "").strip().upper()
    if not pwsid.startswith("CA") or sample_date is None:
        return None
    if not _ccr_is_published(sample_date.year, today or timezone.localdate()):
        return None
    return CCR_VIEWER_URL.format(pwsid=pwsid, year=sample_date.year)


@login_required
def result_detail(request, pk):
    """One lab result, whole.

    The results log shows six columns of a record that carries far more — method,
    laboratory, ELAP certification, reporting level, analysis date, collector,
    chain of custody. This is the page those columns were hidden behind.

    **No RegulatoryLimit is loaded or rendered here.** A one-record page is
    exactly where a limit beside a value would look most natural, and showing one
    is a verdict in everything but the wording. See the module docstring.
    """
    result = get_object_or_404(
        SampleResult.objects.select_related(
            "analyte",
            "analyte__observed_property",
            "event",
            "event__sampling_point",
            "event__sampling_point__facility",
            "event__sampling_point__facility__system",
        ),
        pk=pk,
    )
    system = result.event.sampling_point.facility.system

    # 143-08 Task 3 (R-055): the lead panel's third peer. The most recent
    # earlier finding of the SAME analyte at the SAME point -- never a
    # different point or a different analyte, which would compare findings
    # that answer different questions. `sample_date__lte` plus `exclude(pk=)`
    # rather than a strict `<` catches two results filed under the same date
    # (a re-run, a duplicate row) and still resolves to one deterministic row,
    # ordered by pk so the tie always favors the later-written one.
    previous_finding = (
        SampleResult.objects
        .filter(
            analyte=result.analyte,
            event__sampling_point=result.event.sampling_point,
            event__sample_date__lte=result.event.sample_date,
        )
        .exclude(pk=result.pk)
        .select_related("event")
        .order_by("-event__sample_date", "-pk")
        .first()
    )
    finding_count = SampleResult.objects.filter(
        analyte=result.analyte,
        event__sampling_point=result.event.sampling_point,
    ).count()

    return render(
        request,
        "drinking/result_detail.html",
        {
            "result": result,
            "event": result.event,
            "point": result.event.sampling_point,
            "facility": result.event.sampling_point.facility,
            "system": system,
            "previous_finding": previous_finding,
            "finding_count": finding_count,
            "ccr_url": _ccr_url(system, result.event.sample_date),
            "ccr_year": result.event.sample_date.year if result.event.sample_date else "",
        },
    )
