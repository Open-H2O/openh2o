# SPDX-License-Identifier: AGPL-3.0-or-later
"""Library of system self-check functions backing the health dashboard.

Each ``check_*`` function returns a category/status/message/details dict (green,
yellow, or red) covering database connectivity, disk usage, data-sync freshness,
ledger integrity, unassigned parcels, duplicated OpenET cache coverage,
point-of-diversion fraction splits, unallocated surface deliveries,
reporting-period month alignment, SSL certificate expiry, the expected database,
and pending migrations; ``run_all_checks`` runs them all in order.
"""
import shutil
import ssl
import socket
from decimal import Decimal
from io import StringIO
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, Sum
from django.core.management import call_command
from django.utils import timezone


def check_database():
    try:
        connection.ensure_connection()
        from parcels.models import Parcel, ParcelLedger
        from wells.models import Well
        from accounting.models import WaterAccount

        counts = {
            "parcels": Parcel.objects.count(),
            "wells": Well.objects.count(),
            "ledger_entries": ParcelLedger.objects.count(),
            "water_accounts": WaterAccount.objects.count(),
        }
        return {
            "category": "database",
            "status": "green",
            "message": f"Connected. {counts['parcels']} parcels, {counts['wells']} wells, {counts['ledger_entries']} ledger entries.",
            "details": counts,
        }
    except Exception as e:
        return {
            "category": "database",
            "status": "red",
            "message": f"Connection failed: {e}",
            "details": {"error": str(e)},
        }


def check_disk():
    import os
    paths_to_check = {"base_dir": str(settings.BASE_DIR)}
    if hasattr(settings, "MEDIA_ROOT") and settings.MEDIA_ROOT:
        media_path = str(settings.MEDIA_ROOT)
        if os.path.exists(media_path):
            paths_to_check["media_root"] = media_path

    details = {}
    worst_status = "green"

    for label, path in paths_to_check.items():
        try:
            usage = shutil.disk_usage(path)
            pct_used = (usage.used / usage.total) * 100
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            details[label] = {
                "path": path,
                "percent_used": round(pct_used, 1),
                "free_gb": round(free_gb, 1),
                "total_gb": round(total_gb, 1),
            }
            if pct_used > 90:
                worst_status = "red"
            elif pct_used > 80 and worst_status != "red":
                worst_status = "yellow"
        except Exception as e:
            details[label] = {"error": str(e)}
            worst_status = "red"

    base = details.get("base_dir", {})
    msg = f"{base.get('percent_used', '?')}% used, {base.get('free_gb', '?')} GB free"
    return {
        "category": "disk",
        "status": worst_status,
        "message": msg,
        "details": details,
    }


def check_sync_freshness():
    from datasync.models import DataSource, DataSyncLog

    # On the public demo the database is restored from a frozen golden snapshot
    # every night, so external-feed timestamps are intentionally static. Staleness
    # is the designed state here, not a fault — report green instead of alarming
    # forever (and escalating to red once the snapshot ages past a week).
    if getattr(settings, "HEALTH_DEMO_MODE", False):
        return {
            "category": "sync_freshness",
            "status": "green",
            "message": "Demo instance — sync freshness not enforced (data is snapshot-restored nightly).",
            "details": {"demo_mode": True},
        }

    active_sources = DataSource.objects.filter(is_active=True)
    if not active_sources.exists():
        return {
            "category": "sync_freshness",
            "status": "green",
            "message": "No active data sources configured.",
            "details": {},
        }

    now = timezone.now()
    details = {}
    worst_status = "green"

    for source in active_sources:
        last_log = (
            DataSyncLog.objects.filter(data_source=source, status="success")
            .order_by("-started_at")
            .first()
        )
        if last_log is None:
            details[source.code] = {"last_sync": None, "status": "red"}
            worst_status = "red"
        else:
            age = now - last_log.started_at
            age_hours = age.total_seconds() / 3600
            if age > timedelta(days=7):
                source_status = "red"
                worst_status = "red"
            elif age > timedelta(hours=48):
                source_status = "yellow"
                if worst_status != "red":
                    worst_status = "yellow"
            else:
                source_status = "green"
            details[source.code] = {
                "last_sync": last_log.started_at.isoformat(),
                "age_hours": round(age_hours, 1),
                "status": source_status,
            }

    stale_count = sum(1 for v in details.values() if v["status"] != "green")
    msg = f"{len(details)} sources checked, {stale_count} stale" if stale_count else f"{len(details)} sources all fresh"
    return {
        "category": "sync_freshness",
        "status": worst_status,
        "message": msg,
        "details": details,
    }


def check_ledger_integrity():
    from parcels.models import Parcel, ParcelLedger

    orphan_count = ParcelLedger.objects.exclude(
        parcel_id__in=Parcel.objects.values_list("id", flat=True)
    ).count()

    zero_count = ParcelLedger.objects.filter(amount_acre_feet=0).count()

    details = {"orphan_entries": orphan_count, "zero_amount_entries": zero_count}

    # Orphaned entries are real corruption and stay red everywhere. Zero-amount
    # entries are legitimate demo-seed artifacts (a parcel that booked no water in
    # a period); on the frozen demo they're static and shouldn't alarm.
    demo = getattr(settings, "HEALTH_DEMO_MODE", False)
    if orphan_count > 0:
        status = "red"
        msg = f"{orphan_count} orphaned ledger entries (parcel deleted)"
    elif zero_count > 0 and not demo:
        status = "yellow"
        msg = f"{zero_count} zero-amount ledger entries"
    elif zero_count > 0:
        status = "green"
        msg = f"{zero_count} zero-amount ledger entries (demo data; informational)"
    else:
        status = "green"
        msg = "All ledger entries valid"

    return {
        "category": "ledger_integrity",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_orphans():
    from parcels.models import Parcel
    from accounting.models import WaterAccountParcel
    from datasync.models import MonitoredStation
    from wells.models import Well

    assigned_parcel_ids = WaterAccountParcel.objects.filter(
        removed_date__isnull=True
    ).values_list("parcel_id", flat=True)
    unassigned_parcels = Parcel.objects.filter(status="active").exclude(
        id__in=assigned_parcel_ids
    ).count()

    orphan_wells = Well.objects.filter(status="active").count()
    monitored_count = MonitoredStation.objects.count()

    details = {
        "unassigned_parcels": unassigned_parcels,
        "active_wells": orphan_wells,
        "monitored_stations": monitored_count,
    }

    if unassigned_parcels > 0:
        status = "yellow"
        msg = f"{unassigned_parcels} active parcels not assigned to any account"
    else:
        status = "green"
        msg = "All active parcels assigned to accounts"

    return {
        "category": "orphans",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_ssl():
    hosts = getattr(settings, "ALLOWED_HOSTS", [])
    domain = getattr(settings, "SITE_DOMAIN", None)

    if domain:
        target = domain
    elif hosts and hosts[0] not in ("*", "localhost", "127.0.0.1", ""):
        target = hosts[0]
    else:
        return {
            "category": "ssl",
            "status": "yellow",
            "message": "SSL check unavailable (development mode)",
            "details": {"reason": "No public domain configured in ALLOWED_HOSTS"},
        }

    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((target, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=target) as ssock:
                cert = ssock.getpeercert()
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                days_remaining = (not_after - datetime.utcnow()).days

                if days_remaining < 7:
                    status = "red"
                elif days_remaining < 30:
                    status = "yellow"
                else:
                    status = "green"

                return {
                    "category": "ssl",
                    "status": status,
                    "message": f"Certificate valid for {days_remaining} days ({target})",
                    "details": {
                        "domain": target,
                        "expires": not_after.isoformat(),
                        "days_remaining": days_remaining,
                    },
                }
    except Exception as e:
        return {
            "category": "ssl",
            "status": "red",
            "message": f"SSL check failed: {e}",
            "details": {"domain": target, "error": str(e)},
        }


def check_docker():
    db_settings = settings.DATABASES["default"]
    expected_name = db_settings.get("NAME", "")

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_name = cursor.fetchone()[0]

        if actual_name == expected_name:
            return {
                "category": "docker",
                "status": "green",
                "message": f"Database '{actual_name}' matches configuration",
                "details": {"expected": expected_name, "actual": actual_name},
            }
        else:
            return {
                "category": "docker",
                "status": "red",
                "message": f"Database mismatch: expected '{expected_name}', got '{actual_name}'",
                "details": {"expected": expected_name, "actual": actual_name},
            }
    except Exception as e:
        return {
            "category": "docker",
            "status": "red",
            "message": f"Docker check failed: {e}",
            "details": {"error": str(e)},
        }


def check_migrations():
    try:
        out = StringIO()
        call_command("showmigrations", "--plan", stdout=out)
        output = out.getvalue()
        unapplied = [
            line.strip() for line in output.splitlines() if line.strip() and not line.strip().startswith("[X]")
        ]
        if not unapplied:
            return {
                "category": "migrations",
                "status": "green",
                "message": "All migrations applied",
                "details": {"unapplied_count": 0},
            }
        else:
            return {
                "category": "migrations",
                "status": "red",
                "message": f"{len(unapplied)} unapplied migrations",
                "details": {
                    "unapplied_count": len(unapplied),
                    "unapplied": unapplied[:10],
                },
            }
    except Exception as e:
        return {
            "category": "migrations",
            "status": "red",
            "message": f"Migration check failed: {e}",
            "details": {"error": str(e)},
        }


def check_cache_duplication():
    """Catch OpenETCache rows that cover the same parcel-month more than once.

    F-math-08 (math eval 2026-07-18). Two cache rows spanning one parcel-month
    hold the SAME measurement fetched twice, so the engine reads the newer and
    ignores the older — but duplicates still mean a writer bypassed the upsert,
    and before that fix they were summed into a doubled gross ET. This is the
    check that would have caught the doubling, because the closure metric never
    will: the residual method absorbs multiplicative ET error almost invisibly
    (doubling ET moved closure by 0.07%).

    The uniqueness constraint blocks identical windows; this also catches the
    case the constraint cannot see — DIFFERENT spans that overlap (a January-June
    window plus a March-only window both covering March).
    """
    from datasync.models import OpenETCache

    exact_duplicates = (
        OpenETCache.objects.exclude(model_name=OpenETCache.PENDING_MARKER)
        .values("parcel_id", "start_date", "end_date", "variable", "model_name")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .count()
    )

    # Overlapping-but-not-identical spans, per parcel/variable/model. Small
    # table (one row per parcel-window), so the self-join is cheap.
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM datasync_openetcache a
            JOIN datasync_openetcache b
              ON a.parcel_id = b.parcel_id
             AND a.variable = b.variable
             AND a.model_name = b.model_name
             AND a.id < b.id
             AND a.start_date <= b.end_date
             AND b.start_date <= a.end_date
            WHERE a.model_name <> %s AND a.parcel_id IS NOT NULL
            """,
            [OpenETCache.PENDING_MARKER],
        )
        overlapping = cur.fetchone()[0]

    details = {
        "exact_duplicate_groups": exact_duplicates,
        "overlapping_span_pairs": overlapping,
    }

    if exact_duplicates or overlapping:
        status = "red"
        msg = (
            f"OpenET cache covers some parcel-months twice "
            f"({exact_duplicates} duplicate windows, {overlapping} overlapping "
            f"spans) — ET and precip may be overstated"
        )
    else:
        status = "green"
        msg = "No duplicated OpenET cache coverage"

    return {
        "category": "cache_duplication",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_pod_fractions():
    """Verify each point of diversion splits to ~100% across its served parcels.

    F-data-06 (math eval 2026-07-18). A POD's diverted volume is apportioned to
    parcels by PointOfDiversionParcel.fraction. If the fractions sum to less than
    one, diverted water silently vanishes from the ledger; more than one and it
    is invented. Neither shows up as an error anywhere else.

    TOLERANCE IS REQUIRED, not laziness: fraction is a 4-decimal field, so an
    even split across 18 parcels cannot sum to exactly 1 (the live demo sits at
    1.0008, 0.9999 and 1.0003). We allow one unit in the last place per link,
    with a small floor, and flag anything beyond that as real misconfiguration.
    """
    from surface.models import PointOfDiversionParcel

    sums = (
        PointOfDiversionParcel.objects.values("point_of_diversion_id")
        .annotate(total=Sum("fraction"), n=Count("id"))
        .order_by("point_of_diversion_id")
    )

    offenders = []
    for row in sums:
        # 0.0001 per link is the most 4-decimal rounding can drift, floored at
        # 0.001 so a 2-parcel split still gets a sane band.
        tolerance = max(Decimal("0.001"), Decimal("0.0001") * row["n"])
        drift = abs((row["total"] or Decimal("0")) - Decimal("1"))
        if drift > tolerance:
            offenders.append(
                {
                    "point_of_diversion_id": row["point_of_diversion_id"],
                    "fraction_sum": str(row["total"]),
                    "links": row["n"],
                }
            )

    details = {"pods_checked": len(sums), "offenders": offenders[:20]}

    if offenders:
        status = "red"
        msg = (
            f"{len(offenders)} point(s) of diversion do not split to 100% — "
            f"diverted water is being lost or invented"
        )
    else:
        status = "green"
        msg = f"All {len(sums)} points of diversion split to 100%"

    return {
        "category": "pod_fractions",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_unallocated_delivery():
    """Surface delivered water that crop demand cannot account for.

    T4 (math eval 2026-07-18). The allocator now records a surplus rather than
    dropping it, but a recorded surplus still needs a face: it means the internal
    ledger does not fully explain what the DiversionRecord says was delivered.
    Usually that is a data-quality signal — an overstated diversion volume, an
    understated ET estimate, or genuine non-crop use that should be entered as
    such — so it is a yellow, not a red: the number is recorded and reconcilable,
    it just is not attributed yet.
    """
    from surface.models import UnallocatedDelivery

    rows = UnallocatedDelivery.objects.all()
    total = rows.aggregate(total=Sum("amount_acre_feet"))["total"] or Decimal("0")
    count = rows.count()

    worst = [
        {
            "point_of_diversion": str(r.point_of_diversion),
            "month": str(r.month),
            "unallocated_af": str(r.amount_acre_feet),
            "delivery_af": str(r.delivery_acre_feet),
        }
        for r in rows.order_by("-amount_acre_feet")[:10]
    ]

    details = {
        "records": count,
        "total_unallocated_af": str(total),
        "largest": worst,
    }

    if count:
        status = "yellow"
        msg = (
            f"{total} AF delivered across {count} POD-month(s) is not explained "
            f"by crop demand — check diversion volumes, ET estimates, non-crop use"
        )
    else:
        status = "green"
        msg = "All delivered surface water is accounted for by demand"

    return {
        "category": "unallocated_delivery",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_period_month_alignment():
    """Flag reporting periods whose boundaries fall mid-month.

    P1-5 (math eval 2026-07-18, item 6). The calculation engine produces one run
    per WHOLE month, so a period that starts or ends mid-month cannot be honoured
    exactly: the partial months at each end are counted in full. That is the
    honest behaviour — pro-rating would invent daily resolution the data does not
    have — but it must not be invisible, because the filed total then covers more
    days than the period claims.

    Yellow, not red: the numbers are correct for the months included, and most
    districts run month-aligned periods where this never arises.
    """
    import calendar

    from accounting.models import ReportingPeriod

    offenders = []
    for period in ReportingPeriod.objects.all():
        start_ok = period.start_date.day == 1
        last_day = calendar.monthrange(period.end_date.year, period.end_date.month)[1]
        end_ok = period.end_date.day == last_day
        if not (start_ok and end_ok):
            offenders.append(
                {
                    "period": period.name,
                    "start_date": str(period.start_date),
                    "end_date": str(period.end_date),
                    "is_finalized": period.is_finalized,
                }
            )

    details = {"periods_checked": ReportingPeriod.objects.count(), "offenders": offenders}

    if offenders:
        status = "yellow"
        msg = (
            f"{len(offenders)} reporting period(s) start or end mid-month; monthly "
            f"calculation runs are counted whole, so those periods include more "
            f"days than they state"
        )
    else:
        status = "green"
        msg = "All reporting periods are month-aligned"

    return {
        "category": "period_alignment",
        "status": status,
        "message": msg,
        "details": details,
    }


def run_all_checks():
    return [
        check_database(),
        check_disk(),
        check_sync_freshness(),
        check_ledger_integrity(),
        check_orphans(),
        check_cache_duplication(),
        check_pod_fractions(),
        check_unallocated_delivery(),
        check_period_month_alignment(),
        check_ssl(),
        check_docker(),
        check_migrations(),
    ]
