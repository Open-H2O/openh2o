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
from django.urls import reverse

from core.access import is_administrator
from core.modules import is_enabled

from .models import HealthCheckResult


# 143-09 (R-055, R-056): where a reader goes to act on a problem. Keyed by
# category; each entry is (url name, query string or None, the label the card
# prints, the module that owns the page). A skipped check's module is off by
# definition, so it is never looked up here: health_dashboard only consults
# this mapping for a yellow or red row, and only builds the href when the
# owning module is on (ISS-089: no `{% url %}` reaches the template outside a
# module gate).
WHERE_TO_LOOK = {
    "sync_freshness": (
        "datasync:monitoring_dashboard",
        None,
        "the monitoring dashboard",
        "datasync",
    ),
    "ledger_integrity": (
        "accounting:ledger_list",
        "source_type=calculated",
        "the calculated rows of the Use Ledger",
        "accounting",
    ),
    "period_alignment": (
        "accounting:ledger_list",
        None,
        "the Use Ledger",
        "accounting",
    ),
    "et_meter_agreement": (
        "accounting:dashboard",
        None,
        "the water balance",
        "accounting",
    ),
    "orphans": (
        "parcels:list",
        None,
        "the use areas",
        "parcels",
    ),
    "pod_fractions": (
        "surface:pod_list",
        None,
        "the surface diversions",
        "surface",
    ),
    "unallocated_delivery": (
        "surface:pod_list",
        None,
        "the surface diversions",
        "surface",
    ),
    "calculation": (
        "accounting:periods_list",
        None,
        "the reporting periods",
        "accounting",
    ),
}

# The six categories with no record page in the platform (database, disk,
# ssl, docker, migrations, cache_duplication all measure the host, not a
# module's data). A yellow or red row in one of these carries no `where` and
# instead tells the reader the fix is on the host, not in the platform.
HOST_LEVEL_CATEGORIES = {
    "database",
    "disk",
    "ssl",
    "docker",
    "migrations",
    "cache_duplication",
}

# Cards read red, yellow, green, skipped, then category (the panel says how
# many need attention, so the first cards under it are the ones that do).
_STATUS_ORDER = {"red": 0, "yellow": 1, "green": 2, "skipped": 3}


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


def dbz(request):
    """Database reachability probe: SELECT 1 against the default connection.

    The deliberate inverse of livez — this one MUST touch the database, because
    its whole purpose is to let an external monitor (the VanderOps Sites page)
    measure "the app can reach Postgres" instead of inferring it from page
    loads. Returns plain 200/"ok" or 503/"db unreachable"; no schema details,
    no row counts, safe for anonymous callers.
    """
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return HttpResponse(
            "db unreachable", content_type="text/plain", status=503
        )
    return HttpResponse("ok", content_type="text/plain")


def _canal_with_most_leftover_water():
    """The point of diversion with the most water beyond what the crops could use.

    "Most" is the largest total of ``UnallocatedDelivery`` over the newest
    reporting period that has any such row (149-02 Task 2b); ``None`` when
    there is none, and the card keeps its link to the diversions list. A
    period holds the months between its dates, so the sum is read by month
    range, not by the row's nullable period link.
    """
    from django.db.models import Sum

    from accounting.models import ReportingPeriod
    from surface.models import PointOfDiversion, UnallocatedDelivery

    for period in ReportingPeriod.objects.order_by("-start_date"):
        top = (
            UnallocatedDelivery.objects.filter(
                month__gte=period.start_date.replace(day=1),
                month__lte=period.end_date,
                amount_acre_feet__gt=0,
            )
            .values("point_of_diversion")
            .annotate(total=Sum("amount_acre_feet"))
            .order_by("-total", "point_of_diversion")
            .first()
        )
        if top is not None:
            return PointOfDiversion.objects.filter(pk=top["point_of_diversion"]).first()
    return None


def health_dashboard(request):
    latest_ids = (
        HealthCheckResult.objects.values("category")
        .annotate(latest_id=Max("id"))
        .values_list("latest_id", flat=True)
    )
    # A list, not a queryset, from here on: the card order (red, yellow, green,
    # skipped, then category) is not a single `order_by` column, and each row
    # gains a `where`/`host_level` attribute below that only makes sense on a
    # concrete instance.
    results = list(HealthCheckResult.objects.filter(id__in=latest_ids))
    results.sort(key=lambda r: (_STATUS_ORDER.get(r.status, 4), r.category))

    green_count = sum(1 for r in results if r.status == "green")
    # The registry total: how many checks actually ran and persisted a row. This
    # is derived, never a literal — the template used to say "8 categories" long
    # after there were thirteen (ISS-090), so a fourteenth check moves the number
    # by itself.
    total = len(results)
    # Skipped checks belong to modules this deployment does not run. They are
    # shown, but they leave the healthy denominator and every rollup — counting
    # them as green is what let switching modules off raise the score (ISS-087).
    applicable_results = [r for r in results if r.status != "skipped"]
    applicable = len(applicable_results)
    skipped = total - applicable
    yellow_count = sum(1 for r in applicable_results if r.status == "yellow")
    red_count = sum(1 for r in applicable_results if r.status == "red")
    last_checked = max((r.checked_at for r in results), default=None)
    skipped_category_names = [
        r.get_category_display() for r in results if r.status == "skipped"
    ]

    # 143-09: a way to the record, on the card of every problem. Only a yellow
    # or red row gets one; a healthy or skipped card states its fact and
    # stops (rule 8). Host-level categories point nowhere in the platform;
    # they are fixed on the host, and the card says so instead.
    for r in results:
        r.where = None
        r.host_level = r.category in HOST_LEVEL_CATEGORIES
        # 149-01: a result may carry its own link (the calculation card points
        # at the one period's page, not a list).
        own_href = (r.details or {}).get("where_href")
        if r.status in ("yellow", "red") and own_href and is_enabled("accounting"):
            r.where = {"href": own_href, "label": "the water year's page"}
        elif r.status in ("yellow", "red") and r.category in WHERE_TO_LOOK:
            url_name, query, label, module = WHERE_TO_LOOK[r.category]
            if is_enabled(module):
                href = reverse(url_name)
                if query:
                    href = f"{href}?{query}"
                r.where = {"href": href, "label": label}
                if r.category == "unallocated_delivery":
                    canal = _canal_with_most_leftover_water()
                    if canal is not None:
                        r.where = {
                            "href": f"{reverse('surface:pod_detail', args=[canal.pk])}"
                            "#where-the-water-went",
                            "label": f"{canal.name}, month by month",
                        }

    if applicable == 0:
        # Nothing left to report on. Unreachable in practice — database, disk,
        # docker and migrations are not module-gated — but the empty case has to
        # be defined rather than falling through to "healthy".
        overall_status = "unknown"
    elif red_count:
        overall_status = "unhealthy"
    elif yellow_count:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    # 147-02 rule: operator detail is for signed-in staff, and the stored
    # error text of a failed calculation is for administrators only.
    show_admin_detail = is_administrator(request.user)
    for r in results:
        r.admin_detail = ""
        if isinstance(r.details, dict) and "error_detail" in r.details:
            if show_admin_detail and request.user.is_authenticated:
                r.admin_detail = r.details.get("error_detail") or ""
            r.details = {k: v for k, v in r.details.items() if k != "error_detail"}

    context = {
        "results": results,
        "green_count": green_count,
        "yellow_count": yellow_count,
        "red_count": red_count,
        "total": total,
        "applicable": applicable,
        "skipped": skipped,
        "last_checked": last_checked,
        "skipped_category_names": skipped_category_names,
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

    # Same exclusion as the dashboard: a check skipped because its module is off
    # must not vote in the rollup. It still appears in the `checks` array below —
    # an operator wants to see that it was skipped and why.
    applicable_results = results.exclude(status="skipped")

    if not applicable_results.exists():
        return JsonResponse({"status": "unknown"}, status=200)

    if applicable_results.filter(status="red").exists():
        overall = "unhealthy"
        http_status = 503
    elif applicable_results.filter(status="yellow").exists():
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
