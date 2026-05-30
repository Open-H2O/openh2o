import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from reporting.forms import ReportGenerateForm
from reporting.generators import generate_calwatrs_csv, generate_gears_csv
from reporting.models import ReportingProfile, ReportSubmission, ReportTemplate
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
