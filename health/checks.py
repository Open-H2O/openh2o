# SPDX-License-Identifier: AGPL-3.0-or-later
"""Library of system self-check functions backing the health dashboard.

Each ``check_*`` function returns a category/status/message/details dict (green,
yellow, or red) covering database connectivity, disk usage, data-sync freshness,
ledger integrity, unassigned parcels, SSL certificate expiry, the expected
database, and pending migrations; ``run_all_checks`` runs them all in order.
"""
import shutil
import ssl
import socket
from io import StringIO
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
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

    if orphan_count > 0:
        status = "red"
        msg = f"{orphan_count} orphaned ledger entries (parcel deleted)"
    elif zero_count > 0:
        status = "yellow"
        msg = f"{zero_count} zero-amount ledger entries"
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


def run_all_checks():
    return [
        check_database(),
        check_disk(),
        check_sync_freshness(),
        check_ledger_integrity(),
        check_orphans(),
        check_ssl(),
        check_docker(),
        check_migrations(),
    ]
