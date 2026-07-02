# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Health dashboard surface.

Serves the operator health dashboard and the JSON liveness endpoint, each
rolling the latest HealthCheckResult per category into one overall status
(healthy / degraded / unhealthy / unknown). Anonymous callers see the aggregate
status only; per-subsystem messages are withheld unless the caller is
authenticated.
"""
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.db.models import Max

from .models import HealthCheckResult


def livez(request):
    """Container liveness probe: 200 the instant gunicorn can serve a request.

    Deliberately touches NO database and rolls up NO subsystem health — it answers
    only "is the web process up and handling HTTP." The Docker HEALTHCHECK and the
    Caddy readiness gate (depends_on: service_healthy) key off this, so it must not
    depend on anything that could be transiently red: a stale "unhealthy" row in
    the nightly golden.dump must never keep Caddy from starting. Subsystem health
    lives on the /health/ dashboard and /health/api/ endpoint instead.
    """
    return HttpResponse("ok", content_type="text/plain")


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
        # Per-subsystem messages name internals + failure reasons — operator-only
        # reconnaissance. Anonymous visitors see the aggregate status only.
        "show_detail": request.user.is_authenticated,
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
        return JsonResponse({"status": "unknown"}, status=200)

    if results.filter(status="red").exists():
        overall = "unhealthy"
        http_status = 503
    elif results.filter(status="yellow").exists():
        overall = "degraded"
        http_status = 200
    else:
        overall = "healthy"
        http_status = 200

    # Creds-free liveness ping: anonymous callers get the overall up/down only.
    # The per-subsystem category/message detail (reconnaissance for a prober) is
    # withheld unless the caller is authenticated.
    if not request.user.is_authenticated:
        return JsonResponse({"status": overall}, status=http_status)

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

    latest_check = results.order_by("-checked_at").first()
    return JsonResponse(
        {
            "status": overall,
            "checks": checks,
            "checked_at": latest_check.checked_at.isoformat() if latest_check else None,
        },
        status=http_status,
    )
