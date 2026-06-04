# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounting.models import ReportingPeriod
from parcels.models import ParcelLedger
from reporting.forms import ReportGenerateForm
from reporting.generators import (
    SHARED_SUPPLY_DIVERGENCE_THRESHOLD,
    build_shared_supply_comparison,
    generate_calwatrs_csv,
    generate_gears_csv,
)
from reporting.models import ReportingProfile, ReportSubmission, ReportTemplate
from reporting.services import PREFILL_METHOD_BY_REPORT_TYPE, build_openet_prefill
from reporting.validators import validate_report
from surface.models import DiversionRecord


@login_required
def report_list(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = ReportSubmission.objects.select_related(
        "report_template", "reporting_period",
    ).order_by("-created_at")

    if q:
        queryset = queryset.filter(
            Q(report_template__name__icontains=q)
            | Q(reporting_period__name__icontains=q)
        )
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    gears_count = ReportSubmission.objects.filter(
        report_template__report_type__startswith="gears",
    ).count()
    calwatrs_count = ReportSubmission.objects.filter(
        report_template__report_type__startswith="calwatrs",
    ).count()

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "q": q,
        "status": status,
        "gears_count": gears_count,
        "calwatrs_count": calwatrs_count,
        "status_choices": ReportSubmission.STATUS_CHOICES,
    }

    if request.headers.get("HX-Request"):
        return render(request, "reporting/partials/_report_history.html", context)

    return render(request, "reporting/report_list.html", context)


@login_required
def report_generate(request):
    report_type_filter = request.GET.get("type", "").strip()

    if request.method == "POST":
        form = ReportGenerateForm(request.POST, report_type_filter=report_type_filter)
        if form.is_valid():
            template = form.cleaned_data["report_template"]
            period = form.cleaned_data["reporting_period"]
            report_type = template.report_type

            warnings = validate_report(period, report_type)
            errors = [w for w in warnings if w["level"] == "error"]

            if errors and not request.POST.get("force"):
                context = {"form": form, "warnings": warnings, "has_errors": True}
                return render(request, "reporting/report_generate.html", context)

            media_dir = os.path.join(settings.MEDIA_ROOT, "reports")
            os.makedirs(media_dir, exist_ok=True)
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")

            if report_type in ("gears_by_well", "gears_by_et"):
                method = "by_well" if report_type == "gears_by_well" else "by_et"
                csv_output = generate_gears_csv(period, method=method)
                filename = f"{report_type}_{period.name}_{timestamp}.csv"
                filepath = os.path.join(media_dir, filename)
                with open(filepath, "w") as f:
                    f.write(csv_output.getvalue())

            elif report_type in ("calwatrs_a1", "calwatrs_a2"):
                ttype = "a1" if report_type == "calwatrs_a1" else "a2"
                csv_output = generate_calwatrs_csv(period, template_type=ttype)
                filename = f"{report_type}_{period.name}_{timestamp}.csv"
                filepath = os.path.join(media_dir, filename)
                with open(filepath, "w") as f:
                    f.write(csv_output.getvalue())

            else:
                # report_type is none of the four known kinds — without this guard
                # `filename` is never assigned and line below raises
                # UnboundLocalError → 500. Return a handled error instead.
                context = {
                    "form": form,
                    "report_type_filter": report_type_filter,
                    "error": (
                        f"Unknown report type '{report_type}'. This report template "
                        "can't be generated — check its configuration."
                    ),
                }
                return render(request, "reporting/report_generate.html", context)

            rel_path = os.path.join("reports", filename)

            submission = ReportSubmission.objects.create(
                report_template=template,
                reporting_period=period,
                status="draft",
                generated_file=rel_path,
                generated_at=timezone.now(),
                validation_warnings=warnings,
            )

            return redirect("reporting:report_detail", pk=submission.pk)
    else:
        form = ReportGenerateForm(report_type_filter=report_type_filter)

    return render(request, "reporting/report_generate.html", {
        "form": form,
        "report_type_filter": report_type_filter,
    })


@login_required
def report_detail(request, pk):
    submission = get_object_or_404(
        ReportSubmission.objects.select_related("report_template", "reporting_period"),
        pk=pk,
    )
    report_type = submission.report_template.report_type
    context = {
        "submission": submission,
        "report_type": report_type,
        "is_gears": report_type.startswith("gears"),
        "is_calwatrs": report_type.startswith("calwatrs"),
        # Single-tenant: one agency profile carries the GEARS Correspondence ID.
        "profile": ReportingProfile.objects.first(),
    }
    return render(request, "reporting/report_detail.html", context)


@login_required
def shared_supply_check(request):
    """ISS-056: stored split vs. ET-implied split reasonableness check.

    Lists every hand-set shared well / point of diversion with the human split
    beside the split measured ET demand would imply, flagging large divergences
    as a likely data-entry tell. Display only — never writes a fraction back.
    Defaults to the most recent period carrying real activity (where the ET
    signal lives), with a period selector; ``?period=`` overrides.
    """
    periods = ReportingPeriod.objects.order_by("-start_date")
    period_id = request.GET.get("period", "").strip()
    selected_period = None
    if period_id:
        selected_period = ReportingPeriod.objects.filter(pk=period_id).first()
    if selected_period is None:
        activity_period_id = (
            ParcelLedger.objects.filter(reporting_period__isnull=False)
            .exclude(source_type="allocation")
            .order_by("-reporting_period__start_date")
            .values_list("reporting_period_id", flat=True)
            .first()
        )
        if activity_period_id:
            selected_period = ReportingPeriod.objects.filter(
                pk=activity_period_id
            ).first()
        elif periods.exists():
            selected_period = periods.first()

    groups = build_shared_supply_comparison(selected_period)
    context = {
        "periods": periods,
        "selected_period": selected_period,
        "groups": groups,
        "flagged_count": sum(1 for g in groups if g["any_flag"]),
        "divergence_points": int(SHARED_SUPPLY_DIVERGENCE_THRESHOLD * 100),
    }
    return render(request, "reporting/shared_supply_check.html", context)


@login_required
def report_download(request, pk):
    submission = get_object_or_404(ReportSubmission, pk=pk)
    if not submission.generated_file:
        raise Http404("No generated file.")

    filepath = os.path.join(settings.MEDIA_ROOT, submission.generated_file)
    if not os.path.exists(filepath):
        raise Http404("File not found on disk.")

    return FileResponse(open(filepath, "rb"), as_attachment=True, filename=os.path.basename(filepath))


@login_required
@require_POST
def report_transition(request, pk):
    submission = get_object_or_404(
        ReportSubmission.objects.select_related("report_template", "reporting_period"),
        pk=pk,
    )

    action = request.POST.get("action", "")
    filing_error = ""

    if action == "approve_internal" and submission.status == "draft":
        # Internal GSA/agency sign-off. This is NOT a Water Board review —
        # the state never sees this status.
        submission.status = "internally_approved"
        submission.internal_notes = request.POST.get("internal_notes", "")
        submission.save(update_fields=["status", "internal_notes", "updated_at"])

    elif action == "mark_exported" and submission.status == "internally_approved":
        # The user has downloaded the GEARS file / opened the CalWATRS worksheet
        # and is taking it to the state portal. Still nothing sent by OpenH2O.
        submission.status = "exported"
        submission.save(update_fields=["status", "updated_at"])

    elif action == "mark_filed" and submission.status == "exported":
        # The user records that THEY filed and certified this in the state
        # portal. OpenH2O did not submit anything — this is self-reported.
        # A confirmation number is required: it is the only proof a filing
        # actually happened, so we won't record "filed" without it.
        confirmation = request.POST.get("state_confirmation_number", "").strip()
        if not confirmation:
            filing_error = (
                "Enter the confirmation number the state portal gave you "
                "before recording this as filed."
            )
        else:
            submission.status = "filed"
            submission.filed_at = timezone.now()
            submission.certified_by = request.user
            submission.state_confirmation_number = confirmation
            submission.save(update_fields=[
                "status", "filed_at", "certified_by",
                "state_confirmation_number", "updated_at",
            ])

    if request.headers.get("HX-Request"):
        return render(
            request,
            "reporting/partials/_status_section.html",
            {"submission": submission, "filing_error": filing_error},
        )

    return redirect("reporting:report_detail", pk=submission.pk)


@login_required
def calwatrs_worksheet(request, pk):
    """A per-POD transcription worksheet for CalWATRS.

    CalWATRS has no upload — the user types each Point of Diversion's monthly
    values into the state web form by hand. This view lays the same numbers the
    CSV generator produces out as one block per POD, in a top-to-bottom order
    that mirrors the portal, with each right's CalWATRS PIN beside it.
    """
    submission = get_object_or_404(
        ReportSubmission.objects.select_related("report_template", "reporting_period"),
        pk=pk,
    )
    report_type = submission.report_template.report_type
    if report_type not in ("calwatrs_a1", "calwatrs_a2"):
        raise Http404("The transcription worksheet is only for CalWATRS reports.")

    period = submission.reporting_period
    diversion_type = "direct_use" if report_type == "calwatrs_a1" else "to_storage"

    records = (
        DiversionRecord.objects.filter(
            reporting_period=period,
            diversion_type=diversion_type,
        )
        .select_related("point_of_diversion__water_right__right_type")
        .order_by("point_of_diversion__name", "month")
    )

    blocks = {}
    for rec in records:
        pod = rec.point_of_diversion
        wr = pod.water_right
        if pod.pk not in blocks:
            blocks[pod.pk] = {
                "pod_name": pod.name,
                "stream_name": pod.stream_name,
                "has_water_right": wr is not None,
                "right_id": wr.right_id if wr else "",
                "holder_name": wr.holder_name if wr else "",
                "right_type": wr.right_type.name if wr else "",
                "calwatrs_pin": wr.calwatrs_pin if wr else "",
                "rows": [],
            }
        blocks[pod.pk]["rows"].append({
            "month": rec.month,
            "volume_af": rec.volume_acre_feet,
            "max_rate_cfs": rec.max_flow_rate_cfs,
        })

    context = {
        "submission": submission,
        "blocks": list(blocks.values()),
        "diversion_type_display": (
            "Direct Use" if diversion_type == "direct_use" else "To Storage"
        ),
    }
    return render(request, "reporting/calwatrs_worksheet.html", context)


_CENTS = Decimal("0.01")


def _two_dp(value):
    """Quantize to 2 dp the same way on display and on save, so an unedited value
    submitted back never looks 'modified' due to a rounding mismatch."""
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _field_key(entity, mv):
    return f"{entity['entity_type']}:{entity['entity_id']}:{mv['month']}"


def _apply_prefill_overrides(prefill, overrides):
    """Overlay saved edits onto computed OpenET values and tag each one.

    Adds to every month-value object:
      - field_key:     the prefill_overrides key ("entity_type:entity_id:month")
      - openet_value:  the raw OpenET figure, rounded for display (always shown)
      - display_value: the saved edit if present, else the OpenET figure
      - modified:      True only when the user saved a value that differs from OpenET

    `overrides` only ever holds genuine edits (see report_prefill POST), so a
    "Modified" pill marks a value the user actually changed — not merely one that
    was re-submitted unchanged when the whole form saved.
    """
    for entity in prefill["entities"]:
        for mv in entity["months"]:
            field_key = _field_key(entity, mv)
            openet_display = _two_dp(mv["value_af"])
            mv["field_key"] = field_key
            mv["openet_value"] = openet_display
            if field_key in overrides:
                mv["display_value"] = _two_dp(overrides[field_key])
                mv["modified"] = True
            else:
                mv["display_value"] = openet_display
                mv["modified"] = False
    return prefill


@login_required
def report_prefill(request, pk):
    """Prepare a filing's monthly numbers from OpenET satellite ET.

    GET renders one editable input per entity-month, pre-populated with the raw
    OpenET consumptive-use estimate and tagged with its provenance. POST saves
    the (possibly edited) values onto ReportSubmission.prefill_overrides — never
    the ledger — so a user's reviewed figures survive without double-counting
    against the et_estimate entries the report generators read.
    """
    submission = get_object_or_404(
        ReportSubmission.objects.select_related("report_template", "reporting_period"),
        pk=pk,
    )
    report_type = submission.report_template.report_type
    method = PREFILL_METHOD_BY_REPORT_TYPE.get(report_type)
    if method is None:
        raise Http404("OpenET pre-fill is not available for this report type.")

    prefill = build_openet_prefill(submission.reporting_period, method)

    saved = False
    if request.method == "POST":
        # The form posts every input on each save, so we compare each submitted
        # value against the OpenET figure shown in that input (same 2dp rounding)
        # and persist ONLY the ones the user actually changed. That keeps
        # prefill_overrides — and the "Modified" pills — limited to real edits.
        baseline = {
            _field_key(entity, mv): _two_dp(mv["value_af"])
            for entity in prefill["entities"]
            for mv in entity["months"]
        }
        overrides = {}
        for key, value in request.POST.items():
            if not key.startswith("val:"):
                continue
            raw = value.strip()
            if not raw:
                continue
            field_key = key[len("val:"):]
            try:
                entered = Decimal(raw)
            except (InvalidOperation, ValueError):
                # Junk input is ignored rather than persisted as a fake edit.
                continue
            base = baseline.get(field_key)
            if base is None or _two_dp(entered) != base:
                overrides[field_key] = str(entered)
        submission.prefill_overrides = overrides
        submission.save(update_fields=["prefill_overrides", "updated_at"])
        saved = True

    prefill = _apply_prefill_overrides(prefill, submission.prefill_overrides or {})

    context = {
        "submission": submission,
        "prefill": prefill,
        "report_type": report_type,
        "is_gears": report_type.startswith("gears"),
        "is_calwatrs": report_type.startswith("calwatrs"),
        "saved": saved,
    }
    if request.headers.get("HX-Request"):
        return render(request, "reporting/partials/_openet_prefill.html", context)
    return render(request, "reporting/report_prefill.html", context)
