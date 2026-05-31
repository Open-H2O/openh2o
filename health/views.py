# SPDX-License-Identifier: AGPL-3.0-or-later
from django.http import JsonResponse
from django.shortcuts import render
from django.db.models import Max

from .models import HealthCheckResult


def health_dashboard(request):
    latest_ids = (
        HealthCheckResult.objects.values("category")
        .annotate(latest_id=Max("id"))
        .values_list("latest_id", flat=True)
    )
    results = HealthCheckResult.objects.filter(id__in=latest_ids).order_by("category")

    green_count = results.filter(status="green").count()
    total = results.count()

    if total == 0:
        overall_status = "unknown"
    elif results.filter(status="red").exists():
        overall_status = "unhealthy"
    elif results.filter(status="yellow").exists():
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    context = {
        "results": results,
        "green_count": green_count,
        "total": total,
        "overall_status": overall_status,
    }
    return render(request, "health/dashboard.html", context)


def health_api(request):
    latest_ids = (
        HealthCheckResult.objects.values("category")
        .annotate(latest_id=Max("id"))
        .values_list("latest_id", flat=True)
    )
    results = HealthCheckResult.objects.filter(id__in=latest_ids).order_by("category")

    if not results.exists():
        return JsonResponse(
            {"status": "unknown", "checks": [], "checked_at": None}, status=200
        )

    checks = []
    for r in results:
        checks.append(
            {
                "category": r.category,
                "status": r.status,
                "message": r.message,
                "checked_at": r.checked_at.isoformat(),
            }
        )

    if results.filter(status="red").exists():
        overall = "unhealthy"
        http_status = 503
    elif results.filter(status="yellow").exists():
        overall = "degraded"
        http_status = 200
    else:
        overall = "healthy"
        http_status = 200

    latest_check = results.order_by("-checked_at").first()
    return JsonResponse(
        {
            "status": overall,
            "checks": checks,
            "checked_at": latest_check.checked_at.isoformat() if latest_check else None,
        },
        status=http_status,
    )
