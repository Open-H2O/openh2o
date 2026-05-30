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
from reporting.models import ReportSubmission, ReportTemplate
from reporting.validators import validate_report


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
    context = {"submission": submission}
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

    if action == "approve" and submission.status == "draft":
        # Internal GSA/agency sign-off. This is NOT a Water Board review —
        # the state never sees this status.
        submission.status = "internally_approved"
        submission.internal_notes = request.POST.get("internal_notes", "")
        submission.save(update_fields=["status", "internal_notes", "updated_at"])

    elif action == "mark_filed" and submission.status in ("internally_approved", "exported"):
        # The user records that THEY filed and certified this in the state
        # portal. OpenH2O did not submit anything — this is self-reported.
        submission.status = "filed"
        submission.filed_at = timezone.now()
        submission.certified_by = request.user
        submission.state_confirmation_number = request.POST.get(
            "state_confirmation_number", ""
        )
        submission.save(update_fields=[
            "status", "filed_at", "certified_by", "state_confirmation_number", "updated_at",
        ])

    if request.headers.get("HX-Request"):
        return render(request, "reporting/partials/_status_section.html", {"submission": submission})

    return redirect("reporting:report_detail", pk=submission.pk)
