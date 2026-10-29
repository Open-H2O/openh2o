# SPDX-License-Identifier: AGPL-3.0-or-later
"""Library of system self-check functions backing the health dashboard.

Each ``check_*`` function returns a category/status/message/details dict (green,
yellow, or red) covering database connectivity, disk usage, data-sync freshness,
ledger integrity, unassigned parcels, duplicated OpenET cache coverage,
point-of-diversion fraction splits, unallocated surface deliveries,
reporting-period month alignment, satellite-ET-versus-meter agreement, SSL
certificate expiry, the expected database, and pending migrations;
``run_all_checks`` runs them all in order.
"""
import ipaddress
import json
import shutil
import ssl
import socket
from pathlib import Path
from decimal import Decimal
from io import StringIO
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, QuerySet, Sum
from django.core.management import call_command
from django.urls import reverse
from django.utils import dateformat, timezone

from core.modules import is_enabled


def not_applicable(category: str, module: str, subject: str) -> dict:
    """A check whose whole subject belongs to a module this deployment does not run.

    Three answers were available and two of them are wrong. Reporting **red**
    would tell an operator their instance is broken for running the
    configuration they chose. Dropping the row **silently** would shrink the
    dashboard with no explanation, and a missing check looks exactly like a
    check that has never run — the failure shape this codebase guards against
    everywhere else.

    So the check still produces a row, still names itself, and says why it has
    nothing to measure. ``status`` is ``skipped`` — its own alarm level, added
    as the fourth STATUS_CHOICES entry. Everything that rolls health
    up branches on the status field: the dashboard, the JSON API and the CLI
    summary all exclude skipped rows from the healthy denominator and from the
    overall verdict, so a switched-off module can no longer raise the score.

    ``details.module_disabled`` is retained as PROVENANCE — it names which
    module is absent — and is no longer the thing the UI branches on. That was
    the workaround while the field had only three values.
    """
    # The module in words, never its key.
    return {
        "category": category,
        "status": "skipped",
        "message": (
            f"This site has turned off OpenH2O's {_MODULE_WORDS.get(module, module)}, "
            "so this check does not apply."
        ),
        "details": {"module_disabled": module},
    }


#: The modules a check can need, as a sentence names them.
_MODULE_WORDS = {
    "accounting": "accounting",
    "datasync": "data sync",
    "parcels": "use areas",
    "surface": "surface water records",
}


def _count(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def _and(parts: list, word: str = "and") -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(parts) < 2:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} {word} {parts[-1]}"


def _or(parts: list) -> str:
    return _and(parts, "or")


# Irrigation-efficiency bands for check_et_meter_agreement (math eval item 9).
# These come from published irrigation efficiency ranges — roughly 0.70-0.95 for
# drip/micro and 0.55-0.75 for flood/furrow — NOT from our own data, which cannot
# validate them (see that function's docstring on demo circularity).
ET_METER_GREEN_LOW = Decimal("0.60")
ET_METER_GREEN_HIGH = Decimal("1.00")
ET_METER_RED_LOW = Decimal("0.45")
ET_METER_RED_HIGH = Decimal("1.15")
# Below this many comparable parcel-periods the aggregate is anecdote, not signal.
ET_METER_MIN_SAMPLE = 3


def check_database():
    try:
        connection.ensure_connection()

        # This check is about CONNECTIVITY, so it survives every demotion — it
        # just stops counting tables nobody is filling. Each count is omitted from
        # both the details and the sentence rather than reported as a zero that
        # reads like a missing import.
        counts = {}
        phrases = []
        if is_enabled("parcels"):
            from parcels.models import Parcel, ParcelLedger

            counts["parcels"] = Parcel.objects.count()
            counts["ledger_entries"] = ParcelLedger.objects.count()
            phrases.append(_count(counts["parcels"], "use area", "use areas"))
        if is_enabled("wells"):
            from wells.models import Well

            counts["wells"] = Well.objects.count()
            phrases.append(_count(counts["wells"], "well", "wells"))
        if is_enabled("parcels"):
            phrases.append(_count(counts["ledger_entries"], "ledger entry", "ledger entries"))
        if is_enabled("accounting"):
            from accounting.models import WaterAccount

            counts["water_accounts"] = WaterAccount.objects.count()
        # With every counted module off, the honest sentence is the bare fact
        # this check exists to establish.
        held = f", which holds {_and(phrases)}" if phrases else ""
        return {
            "category": "database",
            "status": "green",
            "message": f"OpenH2O reached the database{held}.",
            "details": counts,
        }
    except Exception as e:
        return {
            "category": "database",
            "status": "red",
            "message": f"OpenH2O cannot reach the database. Details: {e}",
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

    # The first sentence was reworded 2026-10-16 (on Docker Desktop the disk
    # is Docker's own).
    base = details.get("base_dir", {})
    if "error" in base:
        msg = f"OpenH2O cannot read the disk's size. Details: {base['error']}"
    else:
        msg = (
            f"The disk OpenH2O runs on is {base['percent_used']}% full, with "
            f"{base['free_gb']} GB free."
        )
        if worst_status != "green":
            msg += (
                " OpenH2O asks for attention when the disk is over 80% full and "
                "for action when it is over 90% full."
            )
    return {
        "category": "disk",
        "status": worst_status,
        "message": msg,
        "details": details,
    }


def check_sync_freshness():
    if not is_enabled("datasync"):
        return not_applicable(
            "sync_freshness", "datasync", "external-feed freshness"
        )

    from datasync.models import DataSource

    # On the public demo the database is restored from a frozen golden snapshot
    # every night, so external-feed timestamps are intentionally static. Staleness
    # is the designed state here, not a fault — report green instead of alarming
    # forever (and escalating to red once the snapshot ages past a week).
    if getattr(settings, "HEALTH_DEMO_MODE", False):
        return {
            "category": "sync_freshness",
            "status": "green",
            "message": (
                "This demonstration site restores its data every night, so "
                "OpenH2O does not check how recently each data source synced."
            ),
            "details": {"demo_mode": True},
        }

    active_sources = DataSource.objects.filter(is_active=True)
    if not active_sources.exists():
        return {
            "category": "sync_freshness",
            "status": "green",
            "message": "No data source is turned on.",
            "details": {},
        }

    details, worst_status, names, waiting_for_key, no_station_on = _survey_source_freshness(
        active_sources
    )
    msg = _freshness_message(details, names, waiting_for_key, no_station_on)
    return {
        "category": "sync_freshness",
        "status": worst_status,
        "message": msg,
        "details": details,
    }


def _survey_source_freshness(
    active_sources: QuerySet,
) -> tuple[dict[str, dict], str, dict[str, str], list[str], list[str]]:
    """Each active source's last sync and status, the worst status, and the sources left uncounted."""
    from datasync import freshness
    from datasync.models import DataSyncLog

    now = timezone.now()
    details = {}
    worst_status = "green"
    names = {}
    # Row 4: a source waiting for its API key is not counted, as the
    # monitoring dashboard shows it (it was action required here).
    waiting_for_key = []
    # A source with no
    # station turned on is not counted (the dashboard says "None activated").
    no_station_on = []

    for source in active_sources:
        if freshness.credential_missing(source.code):
            waiting_for_key.append(source.name)
            details[source.code] = {"last_sync": None, "status": "needs_key"}
            continue
        if not source.monitoredstation_set.filter(is_active=True).exists():
            no_station_on.append(source.name)
            details[source.code] = {"last_sync": None, "status": "no_station_on"}
            continue
        names[source.code] = source.name
        # Row 1: a partial sync (some stations returned data) counts as a
        # sync, as sync_source's own failure streak counts it.
        last_log = (
            DataSyncLog.objects.filter(
                data_source=source, status__in=("success", "partial")
            )
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
    return details, worst_status, names, waiting_for_key, no_station_on


def _freshness_message(
    details: dict[str, dict],
    names: dict[str, str],
    waiting_for_key: list[str],
    no_station_on: list[str],
) -> str:
    """The sentences that say which sources are stale, never synced, or not counted."""
    from datasync import freshness

    counted = {
        c: v for c, v in details.items()
        if v["status"] not in ("needs_key", "no_station_on")
    }
    never = [freshness.source_phrase(names[c]) for c, v in counted.items() if v["last_sync"] is None]
    behind = [(c, v) for c, v in counted.items() if v["last_sync"] and v["status"] != "green"]
    sentences = []
    if never:
        sentences.append(f"OpenH2O has not synced {_or(never)} on this site yet.")
    for c, v in behind:
        sentences.append(
            f"OpenH2O last synced {freshness.source_phrase(names[c])} "
            f"{freshness.format_hours(round(v['age_hours']))} ago."
        )
    if sentences:
        sentences.append(
            "OpenH2O asks for attention when a data source last synced more "
            "than 48 hours ago, and for action after 7 days or when it has "
            "never synced."
        )
    elif len(counted) == 1:
        sentences.append(
            f"OpenH2O synced {freshness.source_phrase(names[next(iter(counted))])} "
            "in the last 48 hours."
        )
    elif counted:
        sentences.append(
            f"OpenH2O synced all {len(counted)} data sources in the last 48 hours."
        )
    if waiting_for_key:
        need = "needs" if len(waiting_for_key) == 1 else "need"
        sentences.append(
            f"OpenH2O does not count {_and(waiting_for_key)}, which {need} an API key."
        )
    if no_station_on:
        verb = "is" if len(no_station_on) == 1 else "are"
        sentences.append(
            f"{_and(no_station_on)}, with no station turned on, {verb} not counted."
        )
    return " ".join(sentences)


def check_ledger_integrity():
    if not is_enabled("parcels"):
        return not_applicable(
            "ledger_integrity", "parcels", "the use-area ledger"
        )

    from parcels.models import Parcel, ParcelLedger

    orphan_count = ParcelLedger.objects.exclude(
        parcel_id__in=Parcel.objects.values_list("id", flat=True)
    ).count()

    # Row 6: only calculated rows (a zero meter reading is not one).
    zero_count = ParcelLedger.objects.filter(
        amount_acre_feet=0, source_type="calculated"
    ).count()

    details = {"orphan_entries": orphan_count, "zero_amount_entries": zero_count}

    # Orphaned entries are real corruption and stay red everywhere. Zero-amount
    # entries are legitimate demo-seed artifacts (a parcel that booked no water in
    # a period); on the frozen demo they're static and shouldn't alarm.
    #
    # The count is a plain amount_acre_feet=0 filter (every zero-amount row
    # in the live demo is a calculated row), and the message tells the same story the
    # Use Ledger tells about those rows in its Description column, so a reader
    # who meets the count here and the rows there reads one story instead of
    # two different words for the same fact.
    # A month
    # with no ETAW met by groundwater is a normal month, so it is healthy on
    # every site (it asked for attention outside the demo).
    if orphan_count > 0:
        status = "red"
        if orphan_count == 1:
            msg = "1 ledger entry belongs to a use area that is no longer on file."
        else:
            msg = (
                f"{orphan_count:,} ledger entries belong to a use area that is "
                "no longer on file."
            )
    else:
        status = "green"
        msg = "Every ledger entry belongs to a use area on file."
        if zero_count:
            have = "has" if zero_count == 1 else "have"
            months = "that month" if zero_count == 1 else "those months"
            msg += (
                f" {_count(zero_count, 'calculated ledger row', 'calculated ledger rows')} "
                f"{have} no ETAW met by groundwater, so the estimated groundwater "
                f"extraction for {months} is zero."
            )

    return {
        "category": "ledger_integrity",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_orphans():
    # The acting half is "active parcels not assigned to an account", which needs
    # BOTH modules. They are mutually required, so one predicate
    # would do — the pair is spelled out anyway, because an exemption that
    # depends on a requires-edge should say which edge it is leaning on.
    if not is_enabled("parcels") or not is_enabled("accounting"):
        return not_applicable(
            "orphans", "parcels", "parcel-to-account assignment"
        )

    from parcels.models import Parcel
    from accounting.models import WaterAccountParcel

    assigned_parcel_ids = WaterAccountParcel.objects.filter(
        removed_date__isnull=True
    ).values_list("parcel_id", flat=True)
    unassigned_parcels = Parcel.objects.filter(status="active").exclude(
        id__in=assigned_parcel_ids
    ).count()

    # The parcel half is the only half this check ever acts on — the well and
    # station counts are context. Each is reported only when its module is on,
    # so a demoted module contributes no key rather than a zero.
    details = {"unassigned_parcels": unassigned_parcels}
    if is_enabled("wells"):
        from wells.models import Well

        details["active_wells"] = Well.objects.filter(status="active").count()
    if is_enabled("datasync"):
        from datasync.models import MonitoredStation

        details["monitored_stations"] = MonitoredStation.objects.count()

    if unassigned_parcels > 0:
        status = "yellow"
        have = "has" if unassigned_parcels == 1 else "have"
        msg = (
            f"{_count(unassigned_parcels, 'active use area', 'active use areas')} "
            f"{have} no water account."
        )
    else:
        status = "green"
        msg = "Every active use area belongs to a water account."

    return {
        "category": "orphans",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_ssl():
    hosts = getattr(settings, "ALLOWED_HOSTS", [])
    domain = getattr(settings, "SITE_DOMAIN", None)
    target = (domain or (hosts[0] if hosts else "")).lstrip(".")

    # A site
    # reached at a name that is not a public domain (one computer, an office
    # network) has no certificate to check. It was action required forever.
    if not _is_public_domain(target):
        if target and target != "*":
            msg = (
                "OpenH2O has no HTTPS certificate to check, because this "
                f"site's address is {target}, not a public domain name."
            )
        else:
            msg = (
                "This site has no public domain name, so OpenH2O has no HTTPS "
                "certificate to check."
            )
        return {
            "category": "ssl",
            "status": "skipped",
            "message": msg,
            "details": {"address": target},
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

                # Row 1.
                days = f"{days_remaining} day{'' if days_remaining == 1 else 's'}"
                msg = f"The HTTPS certificate for {target} expires in {days}."
                if status != "green":
                    msg += (
                        " OpenH2O asks for attention 30 days before the "
                        "certificate expires and for action 7 days before."
                    )
                return {
                    "category": "ssl",
                    "status": status,
                    "message": msg,
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
            "message": f"OpenH2O cannot read the HTTPS certificate for {target}. Details: {e}",
            "details": {"domain": target, "error": str(e)},
        }


def _is_public_domain(name: str) -> bool:
    """A dotted name that is not an IP address or a local-network name."""
    if not name or name == "*" or "." not in name:
        return False
    try:
        ipaddress.ip_address(name)
        return False
    except ValueError:
        pass
    return not name.endswith((".local", ".localhost", ".internal", ".lan"))


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
                "message": (
                    f"OpenH2O is connected to {actual_name}, the database named "
                    "in OpenH2O's settings."
                ),
                "details": {"expected": expected_name, "actual": actual_name},
            }
        else:
            return {
                "category": "docker",
                "status": "red",
                "message": (
                    f"OpenH2O is connected to {actual_name}, but the database "
                    f"named in OpenH2O's settings is {expected_name}."
                ),
                "details": {"expected": expected_name, "actual": actual_name},
            }
    except Exception as e:
        return {
            "category": "docker",
            "status": "red",
            "message": f"OpenH2O cannot read the database's name. Details: {e}",
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
                "message": "The database has every update this version of OpenH2O needs.",
                "details": {"unapplied_count": 0},
            }
        else:
            return {
                "category": "migrations",
                "status": "red",
                "message": (
                    f"The database is missing {_count(len(unapplied), 'update', 'updates')} "
                    "this version of OpenH2O needs. Run the migrate command."
                ),
                "details": {
                    "unapplied_count": len(unapplied),
                    "unapplied": unapplied[:10],
                },
            }
    except Exception as e:
        return {
            "category": "migrations",
            "status": "red",
            "message": f"OpenH2O cannot read which updates the database has. Details: {e}",
            "details": {"error": str(e)},
        }


def check_cache_duplication():
    """Catch OpenETCache rows that cover the same parcel-month more than once.

    Two cache rows spanning one parcel-month
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
    if not is_enabled("datasync"):
        return not_applicable(
            "cache_duplication", "datasync", "the OpenET cache"
        )

    from datasync.models import OpenETCache

    exact_groups = list(
        OpenETCache.objects.exclude(model_name=OpenETCache.PENDING_MARKER)
        .filter(parcel__isnull=False)
        .values("parcel_id", "start_date", "end_date", "variable", "model_name")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .values_list("parcel_id", flat=True)
    )
    exact_duplicates = len(exact_groups)

    # Overlapping-but-not-identical spans, per parcel/variable/model. Small
    # table (one row per parcel-window), so the self-join is cheap.
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT a.parcel_id FROM datasync_openetcache a
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
        overlap_parcels = [row[0] for row in cur.fetchall()]
    overlapping = len(overlap_parcels)
    use_areas = len(set(exact_groups) | set(overlap_parcels))

    details = {
        "exact_duplicate_groups": exact_duplicates,
        "overlapping_span_pairs": overlapping,
        "use_areas": use_areas,
    }

    # The engine reads the newer estimate (accounting/steps.py), so no figure is
    # overstated; attention needed, not action required.
    if use_areas:
        status = "yellow"
        msg = (
            "OpenH2O holds two OpenET estimates for the same months at "
            f"{_count(use_areas, 'use area', 'use areas')}, and uses the newer one."
        )
    else:
        status = "green"
        msg = "OpenH2O holds one OpenET estimate for each use area and month."

    return {
        "category": "cache_duplication",
        "status": status,
        "message": msg,
        "details": details,
    }


def check_pod_fractions():
    """Verify each point of diversion splits to ~100% across its served parcels.

    A POD's diverted volume is apportioned to
    parcels by PointOfDiversionParcel.fraction. If the fractions sum to less than
    one, diverted water silently vanishes from the ledger; more than one and it
    is invented. Neither shows up as an error anywhere else.

    TOLERANCE IS REQUIRED, not laziness: fraction is a 4-decimal field, so an
    even split across 18 parcels cannot sum to exactly 1 (the live demo sits at
    1.0008, 0.9999 and 1.0003). We allow one unit in the last place per link,
    with a small floor, and flag anything beyond that as real misconfiguration.
    """
    if not is_enabled("surface"):
        return not_applicable(
            "pod_fractions", "surface", "point-of-diversion fraction splits"
        )

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

    # The shares divide a canal's water only in a month with no ETAW on any of
    # its use areas, so attention needed, not action required.
    n_points = len(sums)
    if offenders:
        status = "yellow"
        msg = (
            f"At {_count(len(offenders), 'point', 'points')} of diversion, the use "
            "areas' shares do not add up to 100%. OpenH2O divides a canal's water "
            "in these shares only in a month when none of the canal's use areas "
            "has any ETAW. In such a month, the use areas together receive more "
            "or less water than the canal delivered."
        )
    elif n_points == 0:
        status = "green"
        msg = "No point of diversion serves a use area yet."
    elif n_points == 1:
        status = "green"
        msg = "At the one point of diversion that serves use areas, their shares add up to 100%."
    else:
        status = "green"
        msg = (
            f"At each of the {n_points} points of diversion that serve use "
            "areas, their shares add up to 100%."
        )

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
    if not is_enabled("surface"):
        return not_applicable(
            "unallocated_delivery", "surface", "surface delivery attribution"
        )

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

    # The run note's words (2026-10-12), the points of diversion named first.
    if count:
        status = "yellow"
        points = rows.values("point_of_diversion").distinct().count()
        msg = (
            f"At {_count(points, 'point', 'points')} of diversion, {total:,.2f} AF "
            "of headgate water was left after each field received its ETAW "
            "divided by its irrigation efficiency."
        )
    else:
        status = "green"
        msg = (
            "No headgate water was left after each field received its ETAW "
            "divided by its irrigation efficiency."
        )

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
    if not is_enabled("accounting"):
        return not_applicable(
            "period_alignment", "accounting", "reporting-period boundaries"
        )

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

    # Name the day.
    if offenders:
        status = "yellow"
        parts = []
        for period in ReportingPeriod.objects.filter(
            name__in=[o["period"] for o in offenders]
        ).order_by("start_date"):
            parts.append(_mid_month_sentences(period))
        msg = " ".join(parts)
    else:
        status = "green"
        msg = (
            "Every water year starts on the first day of a month and ends on "
            "the last day of a month."
        )

    return {
        "category": "period_alignment",
        "status": status,
        "message": msg,
        "details": details,
    }


def _day(d) -> str:
    return f"{d:%B} {d.day}"


def _mid_month_sentences(period) -> str:
    """'WY 2025-2026 starts on October 15. OpenH2O calculates whole months,
    so WY 2025-2026's figures include October 1 to 14.'"""
    import calendar
    from datetime import date

    s, e = period.start_date, period.end_date
    last = calendar.monthrange(e.year, e.month)[1]
    when, extra = [], []
    if s.day != 1:
        when.append(f"starts on {_day(s)}")
        before = date(s.year, s.month, s.day - 1)
        extra.append(
            f"{_day(date(s.year, s.month, 1))}" + ("" if s.day == 2 else f" to {before.day}")
        )
    if e.day != last:
        when.append(f"ends on {_day(e)}")
        after = date(e.year, e.month, e.day + 1)
        extra.append(_day(after) + ("" if after.day == last else f" to {last}"))
    return (
        f"{period.name} {' and '.join(when)}. OpenH2O calculates whole months, "
        f"so {period.name}'s figures include {' and '.join(extra)}."
    )


def _metered_use_areas(n: int) -> str:
    """"1 metered use area" / "22 metered use areas": a real plural, never "(s)".

    The check counts one use area once per water year it has a meter or a
    delivery and an estimated use, so the caller says "counted once per water
    year" beside the number.
    """
    return f"{n} metered use area{'' if n == 1 else 's'}"


def check_et_meter_agreement():
    """Cross-check satellite ET against physical meters — the one test closure cannot do.

    Item 9 (math eval 2026-07-18). Every ET number in this system comes from one
    place: OpenET actual ET (``variable="ET"``, ``model="Ensemble"``), read by
    accounting.steps.et_gross. The mass-balance closure metric CANNOT validate
    that magnitude, because the residual method defines groundwater extraction as
    whatever makes the identity balance — inflate ET and both sides inflate
    together. Measured 2026-06-05: doubling gross ET moved closure by 0.07%.

    A meter is the only instrument in the database that is independent of OpenET.
    It measures water that physically moved through a pipe and has no opinion
    about satellites. So on parcels the district actually meters we can ask a
    question closure cannot: does the crop demand we derived from space agree
    with the water somebody pumped?

    THE RATIO IS IRRIGATION EFFICIENCY. Net consumptive use (gross ET minus
    effective precipitation) divided by applied water (metered groundwater plus
    delivered surface water) is the fraction of applied water the crop actually
    consumed; the rest goes to deep percolation, runoff and evaporation. Published
    ranges run roughly 0.70-0.95 for drip and micro-sprinkler and 0.55-0.75 for
    flood and furrow, so the bands below come from agronomy, NOT from our data.
    Above 1.0 the crop consumed more than was supplied, which needs soil-moisture
    carryover or a measurement error to explain.

    Sensitivity is the whole point: a parcel sitting at 0.93 today lands at 1.86
    if ET doubles. That is deep in the red band and impossible to miss.

    WARNING — THE DEMO CANNOT VALIDATE THIS CHECK. seed_merced_ledgers writes each
    meter reading and each surface delivery as the parcel's own ET-derived need
    DIVIDED by an efficiency the seeder itself chose, so a demo ratio is that
    chosen efficiency read straight back out, no matter how wrong ET is. That is
    circular by construction: on demo data this measures the seeder. It only
    becomes a real test against a district's own meters. Do not "tune" the bands
    to make demo numbers prettier.

    What the seeder chooses decides the shape of the circularity. A flat band
    keyed on a WELL or POD INDEX ([1.05, 1.18] and [1.02, 1.16]) would make every
    parcel read near-drip and the aggregate sit at 0.9288 whether the field was
    flood-irrigated alfalfa or a micro-irrigated almond block. The multiple is
    instead 1 / (that crop's
    irrigation-method efficiency), so a demo parcel reads back the efficiency of
    the method its crop is actually grown under and the aggregate is the
    consumptive-use-weighted harmonic mean of the seeded crop mix. Still the
    seeder measuring itself — but a parcel-level number a district engineer can
    recognise rather than dismiss.

    Status comes from the AGGREGATE ratio, because a systematic ET error is what
    this exists to catch and that is what moves the aggregate. Individual parcels
    outside the band are listed as a data-quality signal and can raise a green
    aggregate to yellow, but one odd parcel does not turn the system red.

    This is a plausibility rail, never a correction factor: nothing here feeds
    back into CalculationRun or any filed number.
    """
    if not is_enabled("accounting"):
        return not_applicable(
            "et_meter_agreement", "accounting", "the ET-versus-meter cross-check"
        )

    periods, total_cu, total_applied, out_of_band, comparable_parcels = _compare_periods()

    out_of_band.sort(key=lambda row: abs(Decimal(row["ratio"]) - Decimal("1")), reverse=True)
    details = {
        "comparable_parcel_periods": comparable_parcels,
        "by_period": periods,
        "out_of_band": out_of_band[:20],
        "expected_range": f"{ET_METER_GREEN_LOW}-{ET_METER_GREEN_HIGH}",
        "sufficient_sample": comparable_parcels >= ET_METER_MIN_SAMPLE,
    }

    if total_applied <= 0:
        # No meters is not a fault. A district with no metered parcels simply
        # cannot run this test, and saying so plainly beats a false all-clear.
        return {
            "category": "et_meter_agreement",
            "status": "green",
            "message": (
                "No metered use area has water metered or delivered, so OpenH2O "
                "cannot compare ETAW with it."
            ),
            "details": details,
        }

    aggregate = total_cu / total_applied
    details["aggregate_ratio"] = str(aggregate.quantize(Decimal("0.0001")))
    details["total_consumptive_use_af"] = str(total_cu)
    details["total_applied_water_af"] = str(total_applied)

    status, msg = _et_meter_verdict(aggregate, comparable_parcels, out_of_band)
    return {
        "category": "et_meter_agreement",
        "status": status,
        "message": msg,
        "details": details,
    }


def _compare_periods() -> tuple[list[dict], Decimal, Decimal, list[dict], int]:
    """Each water year's ETAW-to-applied-water row, the grand totals, the out-of-band parcels and the comparable parcel count."""
    from accounting.models import ReportingPeriod

    periods = []
    total_cu = Decimal("0")
    total_applied = Decimal("0")
    out_of_band = []
    comparable_parcels = 0

    for period in ReportingPeriod.objects.all().order_by("start_date"):
        comparison = _period_meter_comparison(period)
        if comparison is None:
            continue
        period_cu, period_applied, period_comparable, period_out_of_band = comparison
        comparable_parcels += period_comparable
        out_of_band.extend(period_out_of_band)

        if period_applied > 0:
            periods.append(
                {
                    "period": period.name,
                    "ratio": str((period_cu / period_applied).quantize(Decimal("0.001"))),
                    "consumptive_use_af": str(period_cu),
                    "applied_water_af": str(period_applied),
                }
            )
            total_cu += period_cu
            total_applied += period_applied
    return periods, total_cu, total_applied, out_of_band, comparable_parcels


def _period_meter_comparison(period) -> tuple[Decimal, Decimal, int, list[dict]] | None:
    """One water year's net consumptive use and applied water over its comparable parcels, with the out-of-band parcels; None when no run was metered."""
    from accounting.models import CalculationRun
    from accounting.services import runs_in_period
    from parcels.models import ParcelLedger

    runs = runs_in_period(
        CalculationRun.objects.filter(residual_disposition="metered"), period
    )
    months = set(runs.values_list("period", flat=True))
    parcel_ids = set(runs.values_list("parcel_id", flat=True))
    if not parcel_ids:
        return None

    # Meter rows are matched by the MONTH their effective_date falls in, the
    # same normalization accounting.services.billable_ledger uses; the runs
    # themselves are selected by runs_in_period so period membership has
    # exactly one definition (item 6).
    metered = {}
    for pid, eff, amt in ParcelLedger.objects.filter(
        source_type="meter_reading", parcel_id__in=parcel_ids
    ).values_list("parcel_id", "effective_date", "amount_acre_feet"):
        if eff.strftime("%Y-%m") in months:
            metered[pid] = metered.get(pid, Decimal("0")) + abs(amt)

    cu_by_parcel = {}
    surface_by_parcel = {}
    for run in runs:
        cu_by_parcel[run.parcel_id] = cu_by_parcel.get(
            run.parcel_id, Decimal("0")
        ) + (run.net_consumptive_use_af or Decimal("0"))
        surface_by_parcel[run.parcel_id] = surface_by_parcel.get(
            run.parcel_id, Decimal("0")
        ) + (run.surface_water_af or Decimal("0"))

    comparable_parcels = 0
    out_of_band = []
    period_cu = Decimal("0")
    period_applied = Decimal("0")
    for pid in parcel_ids:
        cu = cu_by_parcel.get(pid, Decimal("0"))
        applied = metered.get(pid, Decimal("0")) + surface_by_parcel.get(
            pid, Decimal("0")
        )
        if applied <= 0 or cu <= 0:
            continue
        comparable_parcels += 1
        period_cu += cu
        period_applied += applied
        ratio = cu / applied
        if not (ET_METER_GREEN_LOW <= ratio <= ET_METER_GREEN_HIGH):
            out_of_band.append(
                {
                    "parcel_id": pid,
                    "period": period.name,
                    "ratio": str(ratio.quantize(Decimal("0.001"))),
                    "consumptive_use_af": str(cu),
                    "applied_water_af": str(applied),
                }
            )
    return period_cu, period_applied, comparable_parcels, out_of_band


def _et_meter_verdict(aggregate: Decimal, n: int, out_of_band: list[dict]) -> tuple[str, str]:
    """The status and sentence for the aggregate ETAW-to-applied-water ratio."""
    # The ratio
    # is ETAW (net consumptive use: gross ET less effective precipitation)
    # over the water metered or delivered.
    pct = (aggregate * 100).quantize(Decimal("0.1"))
    low, high = int(ET_METER_GREEN_LOW * 100), int(ET_METER_GREEN_HIGH * 100)
    each = "each counted" if n != 1 else "counted"
    base = (
        f"ETAW was {pct}% of the water metered or delivered across "
        f"{_metered_use_areas(n)}, {each} once per water year."
    )

    if n < ET_METER_MIN_SAMPLE:
        status = "green"
        have = "have" if n != 1 else "has"
        msg = (
            f"Only {_metered_use_areas(n)}, {each} once per water year, {have} both "
            "ETAW and water metered or delivered, too few for OpenH2O to compare."
        )
    elif aggregate < ET_METER_RED_LOW or aggregate > ET_METER_RED_HIGH:
        status = "red"
        msg = f"{base} Check the OpenET figures and the meter readings."
    elif aggregate < ET_METER_GREEN_LOW or aggregate > ET_METER_GREEN_HIGH:
        status = "yellow"
        msg = f"{base} OpenH2O asks for attention outside {low}% to {high}%."
    elif out_of_band:
        status = "yellow"
        k = len(out_of_band)
        msg = (
            f"{base} OpenH2O expects {low}% to {high}%, and {k} of the {n} "
            f"{'falls' if k == 1 else 'fall'} outside that range."
        )
    else:
        status = "green"
        msg = f"{base} OpenH2O expects {low}% to {high}%."
    return status, msg


def _when(dt):
    """A moment in the site's local time, e.g. "October 6, 2026 at 4:51 AM"."""
    return dateformat.format(timezone.localtime(dt), r"F j, Y \a\t g:i A")


STUCK_RUNNING_AFTER = timedelta(hours=2)
STUCK_QUEUED_AFTER = timedelta(minutes=15)


def check_calculation():
    """When the calculation last ran, and whether it worked.

    Precedence: a run that has been "running" for over two hours is marked
    failed and reported red; a request waiting over fifteen minutes means the
    program that runs it is not running (yellow); otherwise the latest
    finished request decides; a site that has never run it is yellow.
    ``details["error_detail"]`` is for administrators only; the dashboard view
    removes it for everyone else.
    """
    if not is_enabled("accounting"):
        return not_applicable("calculation", "accounting", "the calculation")

    from accounting.models import CalculationRequest

    now = timezone.now()

    stuck_card = _stuck_calculation_card(now)
    if stuck_card is not None:
        return stuck_card

    waiting_card = _waiting_calculation_card(now)
    if waiting_card is not None:
        return waiting_card

    last = (
        CalculationRequest.objects.filter(finished_at__isnull=False)
        .select_related("reporting_period")
        .order_by("-finished_at", "-pk")
        .first()
    )
    if last is None:
        return {
            "category": "calculation",
            "status": "yellow",
            # Row 10.
            "message": (
                "OpenH2O has not calculated any water year on this site yet. "
                "Run the calculation from a water year's page."
            ),
            "details": {},
        }

    stale_card = _stale_calculation_card(last, now)
    if stale_card is not None:
        return stale_card

    return _latest_calculation_card(last)


def _request_details(req, **extra) -> dict:
    """The details every calculation card carries about one request."""
    return {
        "request_id": req.pk,
        "reporting_period_id": req.reporting_period_id,
        "error_detail": req.error_detail or "",
        **extra,
    }


def _with_where(d: dict, req) -> dict:
    """Add the link to the request's water year page, when it has one."""
    if req.reporting_period_id:
        d["where_href"] = reverse(
            "accounting:period_detail", args=[req.reporting_period_id]
        )
    return d


def _stuck_calculation_card(now: datetime) -> dict | None:
    """Mark a run stuck past two hours as failed and return the red card, or None."""
    from accounting.models import CalculationRequest

    stuck = (
        CalculationRequest.objects.filter(
            status="running", started_at__lt=now - STUCK_RUNNING_AFTER
        )
        .order_by("started_at")
        .first()
    )
    if not stuck:
        return None
    sentence = (
        "The calculation stopped without finishing, probably because the "
        "server restarted. Run it again from the water year's page."
    )
    CalculationRequest.objects.filter(
        status="running", started_at__lt=now - STUCK_RUNNING_AFTER
    ).update(status="failed", finished_at=now, outcome=sentence)
    stuck.refresh_from_db()
    return {
        "category": "calculation",
        "status": "red",
        "message": sentence,
        "details": _with_where(_request_details(stuck), stuck),
    }


def _waiting_calculation_card(now: datetime) -> dict | None:
    """The yellow card for a request queued past fifteen minutes, or None."""
    from accounting.models import CalculationRequest

    waiting = (
        CalculationRequest.objects.filter(
            status="queued", requested_at__lt=now - STUCK_QUEUED_AFTER
        )
        .order_by("requested_at")
        .first()
    )
    if not waiting:
        return None
    return {
        "category": "calculation",
        "status": "yellow",
        # Row 9: the cause is in the guide's Calculation row.
        "message": (
            f"The calculation requested on {_when(waiting.requested_at)} "
            "has not started. Pass this card to the AI that "
            "maintains the site; the fix is in OpenH2O's operator guide."
        ),
        "details": _with_where(_request_details(waiting), waiting),
    }


def _stale_calculation_card(last, now: datetime) -> dict | None:
    """The yellow card when open water years have gone two days without a finished calculation, or None."""
    from accounting.models import CalculationRequest, ReportingPeriod

    # A failed latest run stays red (below, it is worse). Otherwise an
    # open water year with no finished calculation for two days means the
    # nightly calculation may have stopped.
    # A run in progress (one stuck past two hours was caught above) is not a
    # stopped schedule.
    in_progress = CalculationRequest.objects.filter(
        status__in=("queued", "running")
    ).exists()
    if (
        last.status != "failed"
        and not in_progress
        and (now - last.finished_at) >= CALCULATION_STALE_AFTER
    ):
        open_years = list(
            ReportingPeriod.objects.filter(is_finalized=False)
            .order_by("start_date")
            .values_list("name", flat=True)
        )
        if open_years:
            still = "is" if len(open_years) == 1 else "are"
            d = _request_details(
                last, age_hours=round((now - last.finished_at).total_seconds() / 3600, 1)
            )
            _with_where(d, last)
            return {
                "category": "calculation",
                "status": "yellow",
                "message": (
                    f"OpenH2O has not calculated since {_when(last.finished_at)}, "
                    f"and {_and(open_years)} {still} still open. {_HAND_OFF}"
                ),
                "details": d,
            }
    return None


def _latest_calculation_card(last) -> dict:
    """The card for the latest finished request: red if it failed, yellow if it has notes, else green."""
    # Row 7: "OpenH2O last calculated 12 months of WY 2025-2026 on ...".
    months = len(last.months or [])
    what = f"{months} month{'' if months == 1 else 's'}"
    if last.reporting_period_id:
        what += f" of {last.reporting_period.name}"
    summary = f"OpenH2O last calculated {what} on {_when(last.finished_at)}."
    d = _request_details(last)
    if last.status == "failed":
        status, msg = "red", last.outcome
        _with_where(d, last)
    elif last.status == "finished_with_notes":
        notes = last.notes or []
        status = "yellow"
        msg = f"{summary} {notes[0]}" if notes else summary
        _with_where(d, last)
    else:
        status, msg = "green", summary
    return {"category": "calculation", "status": status, "message": msg, "details": d}


BACKUP_STALE_AFTER = timedelta(hours=36)

# The line every card the organization cannot fix itself ends with.
_HAND_OFF = (
    "Pass this card to the AI that maintains the site; the fix is in "
    "OpenH2O's operator guide."
)

# scripts/backup.sh's step names, as the red card says them.
_BACKUP_STEPS = {
    "dump": "while copying the database",
    "read-back": "while checking that the database backup can be read",
    "media": "while copying the uploaded files",
    "record": "while recording the result",
}
CALCULATION_STALE_AFTER = timedelta(hours=48)


def _read_backup_record(path: Path):
    """The parsed JSON object in ``path``, or None when the file is absent.

    Raises ValueError for anything unreadable: a directory, bad JSON, or JSON
    that is not an object.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _record_time(value):
    """An aware datetime from an ISO string; ValueError when it is not one."""
    if not isinstance(value, str):
        raise ValueError("not a date")
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def check_backup():
    """Whether the site has a recent backup that read back.

    Reads the two files scripts/backup.sh leaves in OPENH2O_BACKUP_STATUS_DIR:
    last-backup.json (a good run) and last-backup-failure.json (a failed run,
    removed by the next good one). Files, not database rows, because a restore
    would roll a row back to the moment of the backup. Never raises: a record
    that cannot be read is a yellow card.
    """
    folder = Path(getattr(settings, "OPENH2O_BACKUP_STATUS_DIR", "/backups"))
    if not folder.is_dir():
        return {
            "category": "backup",
            "status": "yellow",
            "message": (
                "OpenH2O cannot find the backups folder, so it cannot tell "
                f"whether this site has a backup. {_HAND_OFF}"
            ),
            "details": {"folder": str(folder)},
        }

    unreadable = {
        "category": "backup",
        "status": "yellow",
        "message": f"OpenH2O cannot read the record of the last backup. {_HAND_OFF}",
        "details": {"folder": str(folder)},
    }
    try:
        success = _read_backup_record(folder / "last-backup.json")
        failure = _read_backup_record(folder / "last-backup-failure.json")
        finished = None
        if success is not None:
            finished = _record_time(success["finished_at"])
            dump_bytes = int(success["dump_bytes"])
            entries = int(success["table_data_entries"])
            base_tables = int(success["base_tables"])
        failed = None
        if failure is not None:
            failed = _record_time(failure["failed_at"])
            step = str(failure["step"])
            reason = str(failure["reason"])
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        return unreadable

    if failure is not None and (finished is None or failed > finished):
        return _failed_backup_card(failed, finished, step, reason)

    if success is None:
        return {
            "category": "backup",
            "status": "yellow",
            "message": (
                f"OpenH2O has no record of a backup on this site yet. {_HAND_OFF}"
            ),
            "details": {"folder": str(folder)},
        }

    return _successful_backup_card(finished, dump_bytes, entries, base_tables)


def _failed_backup_card(failed: datetime, finished: datetime | None, step: str, reason: str) -> dict:
    """The red card for a failed backup run that is newer than the last good one."""
    return {
        "category": "backup",
        "status": "red",
        "message": (
            f"The backup on {_when(failed)} failed "
            f"{_BACKUP_STEPS.get(step, f'at its {step} step')}. {_HAND_OFF}"
        ),
        "details": {
            "failed_at": failed.isoformat(),
            "step": step,
            "reason": reason,
            **(
                {"finished_at": finished.isoformat()}
                if finished is not None
                else {}
            ),
        },
    }


def _successful_backup_card(finished: datetime, dump_bytes: int, entries: int, base_tables: int) -> dict:
    """The card for the last good backup: yellow if it is missing tables or stale, else green."""
    age = timezone.now() - finished
    details = {
        "finished_at": finished.isoformat(),
        "dump_bytes": dump_bytes,
        "table_data_entries": entries,
        "base_tables": base_tables,
        "age_hours": round(age.total_seconds() / 3600, 1),
    }
    size = f"{dump_bytes / 1_000_000:.1f} MB"
    if entries < base_tables:
        return {
            "category": "backup",
            "status": "yellow",
            "message": (
                f"The backup on {_when(finished)} is missing "
                f"{base_tables - entries} of the database's {base_tables} "
                f"tables. {_HAND_OFF}"
            ),
            "details": details,
        }
    if age >= BACKUP_STALE_AFTER:
        return {
            "category": "backup",
            "status": "yellow",
            "message": (
                f"OpenH2O has not backed up this site since {_when(finished)}. "
                f"{_HAND_OFF}"
            ),
            "details": details,
        }
    return {
        "category": "backup",
        "status": "green",
        "message": (
            f"OpenH2O backed up this site on {_when(finished)}. The database "
            f"backup is {size} and contains all {base_tables} of the database's "
            "tables."
        ),
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
        check_et_meter_agreement(),
        check_ssl(),
        check_docker(),
        check_migrations(),
        check_calculation(),
        check_backup(),
    ]
