# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading and removing OpenH2O's demonstration data.

The demonstration is a real groundwater basin (the Merced Subbasin) with a made
up water accounting layer on top. An operator can load it into a new site to
try OpenH2O, and remove it again before adding the site's own records:

* ``manage.py load_demonstration`` and the button on Administration >
  Demonstration data run :func:`load`.
* ``manage.py remove_demonstration`` and the same page run :func:`remove`.

**One way to build it.** :data:`STEPS` is the whole sequence that builds the
demonstration, in order. ``scripts/rebuild-golden.sh`` runs it by calling
``load_demonstration``, so what the button loads is what the demonstration
site shows. Every step is a management command that needs no network: each
outside input is a file committed under ``data/merced/``.

**Only onto a site with no records of its own.** A load refuses, before it
writes anything, when a section the demonstration needs is switched off or when
any table in :data:`CONTENT_LABELS` holds a row. Mixing invented records with a
site's own would make every calculation run over both.

**Remove returns the site to a clean install.** It deletes every row of every
content table, keeps users, reference lists and the site settings, and turns
Demonstration mode off. The site name is deleted only when it is the
demonstration's own.

**Change history.** The load writes some 66,000 changes and the removal writes
as many deletions. Both run under their own change-history context and delete
the changes made under that context, and no others, before their transaction
ends, so a site's Change history does not carry invented changes in and out.

**What is a content table.** :data:`CONTENT_LABELS`, :data:`REFERENCE_LABELS`
and :data:`KEPT_LABELS` together name every model OpenH2O has. A test holds the
three lists and the app registry to describing each other, so a new table fails
the suite until someone says which kind it is.
"""

from __future__ import annotations

import graphlib
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pghistory
from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: The site name the demonstration gives the site (``seed_merced_base`` sets it).
DEMONSTRATION_NAME = "Halvern Valley GSA"

#: The boundary the demonstration is built around.
DEMONSTRATION_BOUNDARY = "Merced Subbasin"

#: Seconds between the page's refreshes while a run is under way.
REFRESH_SECONDS = 10

#: A run that has been "running" this long without a lock held is read as one
#: that stopped without finishing.
STALE_MINUTES = 90

#: The Site health category the runs are recorded under.
HEALTH_CATEGORY = "demonstration"

#: The fixed key of the advisory lock that makes a load or a removal
#: one-at-a-time (the seven bytes "OH:DEMO"; greppable, like the calculation's).
ADVISORY_LOCK_KEY = int.from_bytes(b"OH:DEMO", "big")

_DATA = Path(settings.BASE_DIR) / "data"

#: The steps, in order: ``(management command, arguments)``. The paths are
#: absolute so a run does not depend on the directory it starts in.
STEPS = [
    ("seed_data", []),
    ("seed_observed_properties", []),
    # The boundary must exist before the flowlines fixture: it names the
    # boundary by natural key. seed_merced runs this step again; it is idempotent.
    ("seed_merced_base", []),
    ("loaddata", [str(_DATA / "merced" / "flowlines.json")]),
    ("seed_merced", ["--skip-auto-populate", "--allow-prod-clobber"]),
    ("load_station_fixture", ["--fixture", str(_DATA / "merced" / "stations.json")]),
    ("load_reading_fixture", ["--fixture", str(_DATA / "merced" / "readings.json")]),
    ("load_openet_fixture", ["--fixture", str(_DATA / "merced" / "openet_cache.json")]),
    ("seed_calculation_plan", []),
    # Both water years in one invocation: the command rebuilds the ledger on
    # each run, so a second invocation would wipe the first year's rows.
    (
        "refresh_merced_accounting",
        ["--period", "WY 2024-2025", "--period", "WY 2025-2026"],
    ),
    # Re-seeded after the refresh on purpose: the meter reads are the sum of the
    # ledger rows, and the refresh rewrites the ledger.
    ("seed_merced_measurements", []),
]


# -- What is a content table ---------------------------------------------------

#: Every model a site's own records live in. A load needs every one of them
#: empty, and a removal empties every one of them.
CONTENT_LABELS = [
    "geography.Boundary",
    "geography.Zone",
    "geography.ZoneGroup",
    "geography.ParcelZone",
    "geography.Flowline",
    "parcels.CropType",
    "parcels.Parcel",
    "parcels.ParcelStaging",
    "parcels.ParcelIrrigationMethod",
    "parcels.UsageLocation",
    "parcels.ParcelLedger",
    "wells.Well",
    "wells.MonitoringWell",
    "wells.WellIrrigatedParcel",
    "wells.WellMeter",
    "measurements.Meter",
    "measurements.MeterReading",
    "measurements.Sensor",
    "measurements.SensorMeasurement",
    "measurements.WaterMeasurement",
    "standards.Datastream",
    "surface.WaterRight",
    "surface.WaterRightParcel",
    "surface.PointOfDiversion",
    "surface.PointOfDiversionParcel",
    "surface.PointOfDiversionDevice",
    "surface.MeasuringDevice",
    "surface.DiversionRecord",
    "surface.CanalMonthLoss",
    "surface.UnallocatedDelivery",
    "surface.WaterAccountDeliveryPoint",
    "recharge.RechargeSite",
    "recharge.RechargeSitePOD",
    "recharge.RechargeEvent",
    "recharge.RechargeMeasurement",
    "accounting.ReportingPeriod",
    "accounting.WaterAccount",
    "accounting.WaterAccountParcel",
    "accounting.AllocationPlan",
    "accounting.AllocationCarryover",
    "accounting.AccountCredit",
    "accounting.WaterCredit",
    "accounting.WaterCreditDraw",
    "accounting.CalculationPlan",
    "accounting.CalculationStep",
    "accounting.CalculationRun",
    "accounting.CalculationRequest",
    "datasync.MonitoredStation",
    "datasync.DataRecordStaging",
    "datasync.DataSyncLog",
    "datasync.OpenETCache",
    "drinking.WaterSystem",
    "drinking.SystemFacility",
    "drinking.SystemProduction",
    "drinking.SamplingPoint",
    "drinking.SamplingSchedule",
    "drinking.SampleEvent",
    "drinking.SampleResult",
    "drinking.EnvirofactsCache",
    "reporting.ReportingProfile",
    "reporting.ReportingCrosswalk",
    "reporting.ReportSubmission",
]

#: Lists OpenH2O ships and every site needs. A load and a removal leave them as
#: they are.
REFERENCE_LABELS = [
    "accounting.WaterType",
    "core.Role",
    "datasync.DataSource",
    "drinking.Analyte",
    "drinking.RegulatoryLimit",
    "parcels.IrrigationMethod",
    "reporting.ReportTemplate",
    "standards.ObservedProperty",
    "standards.SourceParameter",
    "surface.WaterRightType",
    "wells.WellType",
]

#: People, settings and the site's health: never part of a load or a removal.
KEPT_LABELS = [
    "core.User",
    "core.UserRole",
    "core.SiteConfig",
    "health.HealthCheckResult",
    "feedback.Feedback",
    "feedback.FeedbackAttachment",
]

#: Apps that are not OpenH2O's own: sign-in, sessions, sites, permissions, the
#: spatial reference tables and the change history itself.
KEPT_APPS = frozenset(
    {
        "account",
        "admin",
        "auth",
        "contenttypes",
        "gis",
        "pghistory",
        "sessions",
        "sites",
        "socialaccount",
    }
)

#: How each content table is named on screen: (one, many).
SCREEN_NAMES = {
    "geography.Boundary": ("boundary", "boundaries"),
    "geography.Zone": ("zone", "zones"),
    "geography.ZoneGroup": ("zone group", "zone groups"),
    "geography.ParcelZone": ("use area zone link", "use area zone links"),
    "geography.Flowline": ("stream or canal line", "stream and canal lines"),
    "parcels.CropType": ("crop type", "crop types"),
    "parcels.Parcel": ("use area", "use areas"),
    "parcels.ParcelStaging": ("staged use area", "staged use areas"),
    "parcels.ParcelIrrigationMethod": (
        "irrigation method assignment",
        "irrigation method assignments",
    ),
    "parcels.UsageLocation": ("land use record", "land use records"),
    "parcels.ParcelLedger": ("use ledger entry", "use ledger entries"),
    "wells.Well": ("well", "wells"),
    "wells.MonitoringWell": ("monitoring well", "monitoring wells"),
    "wells.WellIrrigatedParcel": ("well use area link", "well use area links"),
    "wells.WellMeter": ("well meter link", "well meter links"),
    "measurements.Meter": ("meter", "meters"),
    "measurements.MeterReading": ("meter reading", "meter readings"),
    "measurements.Sensor": ("sensor", "sensors"),
    "measurements.SensorMeasurement": ("sensor measurement", "sensor measurements"),
    "measurements.WaterMeasurement": ("water measurement", "water measurements"),
    "standards.Datastream": ("datastream", "datastreams"),
    "surface.WaterRight": ("water right", "water rights"),
    "surface.WaterRightParcel": ("water right use area link", "water right use area links"),
    "surface.PointOfDiversion": ("surface diversion", "surface diversions"),
    "surface.PointOfDiversionParcel": (
        "diversion use area link",
        "diversion use area links",
    ),
    "surface.PointOfDiversionDevice": ("diversion device link", "diversion device links"),
    "surface.MeasuringDevice": ("measuring device", "measuring devices"),
    "surface.DiversionRecord": ("diversion record", "diversion records"),
    "surface.CanalMonthLoss": ("canal monthly loss", "canal monthly losses"),
    "surface.UnallocatedDelivery": ("unallocated delivery", "unallocated deliveries"),
    "surface.WaterAccountDeliveryPoint": (
        "account delivery point",
        "account delivery points",
    ),
    "recharge.RechargeSite": ("recharge site", "recharge sites"),
    "recharge.RechargeSitePOD": ("recharge site intake link", "recharge site intake links"),
    "recharge.RechargeEvent": ("recharge event", "recharge events"),
    "recharge.RechargeMeasurement": ("recharge measurement", "recharge measurements"),
    "accounting.ReportingPeriod": ("water year", "water years"),
    "accounting.WaterAccount": ("water account", "water accounts"),
    "accounting.WaterAccountParcel": (
        "account use area link",
        "account use area links",
    ),
    "accounting.AllocationPlan": ("allocation", "allocations"),
    "accounting.AllocationCarryover": ("allocation carryover", "allocation carryovers"),
    "accounting.AccountCredit": ("account credit", "account credits"),
    "accounting.WaterCredit": ("water credit", "water credits"),
    "accounting.WaterCreditDraw": ("water credit draw", "water credit draws"),
    "accounting.CalculationPlan": ("calculation method", "calculation methods"),
    "accounting.CalculationStep": ("calculation step", "calculation steps"),
    "accounting.CalculationRun": ("calculation result", "calculation results"),
    "accounting.CalculationRequest": ("calculation request", "calculation requests"),
    "datasync.MonitoredStation": ("monitoring station", "monitoring stations"),
    "datasync.DataRecordStaging": ("station reading", "station readings"),
    "datasync.DataSyncLog": ("sync log entry", "sync log entries"),
    "datasync.OpenETCache": ("OpenET record", "OpenET records"),
    "drinking.WaterSystem": ("water system", "water systems"),
    "drinking.SystemFacility": ("system facility", "system facilities"),
    "drinking.SystemProduction": ("system production record", "system production records"),
    "drinking.SamplingPoint": ("sampling point", "sampling points"),
    "drinking.SamplingSchedule": ("sampling schedule row", "sampling schedule rows"),
    "drinking.SampleEvent": ("sample event", "sample events"),
    "drinking.SampleResult": ("lab result", "lab results"),
    "drinking.EnvirofactsCache": ("Envirofacts cache entry", "Envirofacts cache entries"),
    "reporting.ReportingProfile": ("reporting profile", "reporting profiles"),
    "reporting.ReportingCrosswalk": ("reporting crosswalk entry", "reporting crosswalk entries"),
    "reporting.ReportSubmission": ("report submission", "report submissions"),
}


def screen_name(label, count):
    """The screen name of a content table, singular for one and plural otherwise."""
    one, many = SCREEN_NAMES[label]
    return one if count == 1 else many


def content_models():
    """``[(label, model)]`` for each content table this site has installed.

    A section that is switched off and removed outright has no model to list.
    """
    found = []
    for label in CONTENT_LABELS:
        try:
            found.append((label, apps.get_model(label)))
        except LookupError:
            continue
    return found


def content_counts():
    """``{label: rows}`` for each installed content table that holds a row."""
    counts = {}
    for label, model in content_models():
        rows = model.objects.count()
        if rows:
            counts[label] = rows
    return counts


def total(counts):
    return sum(counts.values())


def describe(counts, limit=None):
    """``"3 use areas, 2 zones and 1 well"``, in the content list's order.

    With ``limit``, the first ``limit`` kinds and then ``"and N other kinds of
    record"``.
    """
    items = [f"{n:,} {screen_name(label, n)}" for label, n in counts.items()]
    if limit is not None and len(items) > limit:
        rest = len(items) - limit
        items = items[:limit] + [f"{rest} other kinds of record"]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# -- Whether a load or a removal can go ahead --------------------------------

NOT_LOADED_SENTENCE = (
    "The demonstration data is not loaded on this site, so nothing was removed."
)
RUNNING_SENTENCE = (
    "A load or a removal of the demonstration data is already running, so "
    "nothing was started."
)


def modules_missing():
    """Labels of the sections the demonstration needs that this site has off."""
    from core.modules import MODULE_REGISTRY, enabled_module_names

    running = set(enabled_module_names())
    return [
        spec.label
        for name, spec in MODULE_REGISTRY.items()
        if spec.on_by_default and name not in running
    ]


def _join(names):
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def load_refusal():
    """The sentence that says why a load cannot go ahead, or ``None``."""
    missing = modules_missing()
    if missing:
        which = _join(missing)
        return (
            f"The demonstration data needs the {which} "
            f"section{'s' if len(missing) > 1 else ''} switched on, and this "
            f"site has {'them' if len(missing) > 1 else 'it'} off, so nothing "
            "was loaded."
        )
    counts = content_counts()
    if counts:
        return (
            f"This site already holds {describe(counts, limit=6)}, so the "
            "demonstration data was not loaded."
        )
    return None


def is_loaded():
    """Whether this site holds the demonstration data."""
    from core.models import SiteConfig

    site = SiteConfig.objects.first()
    if site is None or not site.demonstration_mode:
        return False
    try:
        boundary = apps.get_model("geography.Boundary")
    except LookupError:
        return False
    return boundary.objects.filter(name=DEMONSTRATION_BOUNDARY).exists()


def removal_deletes_settings():
    """Whether a removal deletes the site settings: the load made them."""
    from core.models import SiteConfig

    site = SiteConfig.objects.first()
    return site is not None and site.agency_name == DEMONSTRATION_NAME


# -- One at a time ------------------------------------------------------------


def _lock_cursor():
    return connections[DEFAULT_DB_ALIAS].cursor()


def try_lock():
    """Take the one-at-a-time lock for this connection; ``False`` when held."""
    with _lock_cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
        return bool(cursor.fetchone()[0])


def unlock():
    with _lock_cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])


def lock_held_elsewhere():
    """Whether another connection holds the lock right now (a run is going)."""
    with _lock_cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
        free = bool(cursor.fetchone()[0])
        if free:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
    return not free


# -- The record of each run (Site health) ------------------------------------


def _health_model():
    """The Site health model, or ``None`` when that section is not running."""
    from core.modules import is_enabled

    if not is_enabled("health"):
        return None
    try:
        from health.models import HealthCheckResult
    except ImportError:
        return None
    return HealthCheckResult


_RUNNING_WORDS = {
    "load": "Loading the demonstration data.",
    "remove": "Removing the demonstration data.",
}


def _person(user):
    if user is None:
        return None, ""
    name = ""
    try:
        name = user.get_full_name() or user.get_username()
    except AttributeError:
        name = str(user)
    return user.pk, name


def begin_run(action, user=None):
    """Record that a run has started; returns the record's key, or ``None``."""
    model = _health_model()
    if model is None:
        return None
    pk, name = _person(user)
    row = model.objects.create(
        category=HEALTH_CATEGORY,
        status="green",
        message=_RUNNING_WORDS[action],
        details={"action": action, "state": "running", "user": pk, "user_name": name},
    )
    return row.pk


def finish_run(record_pk, action, ok, message, counts=None):
    """Write a run's outcome into its record."""
    model = _health_model()
    if model is None or record_pk is None:
        return
    row = model.objects.filter(pk=record_pk).first()
    if row is None:
        return
    details = dict(row.details or {})
    details.update(
        {
            "action": action,
            "state": "succeeded" if ok else "failed",
            "finished_at": timezone.now().isoformat(),
        }
    )
    if counts is not None:
        details["records"] = total(counts)
    row.status = "green" if ok else "yellow"
    row.message = message
    row.details = details
    row.save(update_fields=["status", "message", "details"])


def last_record():
    """The newest run record, or ``None``."""
    model = _health_model()
    if model is None:
        return None
    return model.objects.filter(category=HEALTH_CATEGORY).order_by("-id").first()


def last_load_time():
    """When the last successful load started, or ``None``."""
    model = _health_model()
    if model is None:
        return None
    row = (
        model.objects.filter(
            category=HEALTH_CATEGORY,
            details__action="load",
            details__state="succeeded",
        )
        .order_by("-id")
        .first()
    )
    return row.checked_at if row else None


# -- The page's view of it -----------------------------------------------------


@dataclass
class Status:
    #: ``not_loaded``, ``refused``, ``running`` or ``loaded``.
    state: str
    #: For ``running``: ``load`` or ``remove``.
    action: str = ""
    #: For ``refused``: the sentence.
    refusal: str = ""
    #: The newest run record, if any.
    record: object = None
    #: Words for the newest run: ``(sentence, ok, who, when)``.
    last: dict = field(default_factory=dict)


def status():
    """Where the demonstration stands, for the page."""
    record = last_record()
    last = {}
    if record is not None:
        details = record.details or {}
        last = {
            "message": record.message,
            "ok": details.get("state") == "succeeded",
            "running": details.get("state") == "running",
            "who": details.get("user_name") or "",
            "when": record.checked_at,
        }
    held = lock_held_elsewhere()
    fresh = (
        record is not None
        and (record.details or {}).get("state") == "running"
        and (timezone.now() - record.checked_at).total_seconds() < STALE_MINUTES * 60
    )
    if held or fresh:
        action = ((record.details or {}).get("action") if record else "") or "load"
        return Status("running", action=action, record=record, last=last)
    if record is not None and (record.details or {}).get("state") == "running":
        # Stopped without finishing: say so rather than leaving it "running".
        last = dict(
            last,
            ok=False,
            running=False,
            message="The last run stopped before it finished.",
        )
    if is_loaded():
        return Status("loaded", record=record, last=last)
    refusal = load_refusal()
    if refusal:
        return Status("refused", refusal=refusal, record=record, last=last)
    return Status("not_loaded", record=record, last=last)


def added_by_people():
    """How many records people added since the load, still on the site.

    Read from Change history: an insert made under a signed-in person's request
    (a context with a user and no command), newer than the last load's record.
    """
    from django.db import connection

    from core.changes import event_models

    since = last_load_time()
    wanted = {label for label, _ in content_models()}
    count = 0
    for label, event_model in event_models().items():
        if label not in wanted:
            continue
        tracked = event_model.pgh_tracked_model
        table = connection.ops.quote_name(event_model._meta.db_table)
        live = connection.ops.quote_name(tracked._meta.db_table)
        key = connection.ops.quote_name(tracked._meta.pk.column)
        sql = (
            f"SELECT COUNT(*) FROM {table} e WHERE e.pgh_label = 'insert'"
            " AND e.pgh_context_id IN (SELECT id FROM pghistory_context"
            " WHERE metadata ? 'user' AND NOT metadata ? 'command')"
            f" AND EXISTS (SELECT 1 FROM {live} t WHERE t.{key} = e.pgh_obj_id)"
        )
        params = []
        if since is not None:
            sql += " AND e.pgh_created_at > %s"
            params.append(since)
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            count += cursor.fetchone()[0]
    return count


# -- Running the steps ---------------------------------------------------------


def run_step(name, args, stdout=None):
    """Run one step. A seam: tests replace it to record the calls."""
    call_command(name, *args, stdout=stdout)


def run_steps(stdout=None):
    for name, args in STEPS:
        run_step(name, args, stdout=stdout)


def _event_tables():
    from core.management.commands.clear_change_history import _event_tables as tables

    return tables()


def forget_events(context_id):
    """Delete the changes written under ``context_id``, and no others."""
    from django.db import connection

    with connection.cursor() as cursor:
        for table in _event_tables():
            cursor.execute(
                f'DELETE FROM "{table}" WHERE pgh_context_id = %s', [str(context_id)]
            )
        cursor.execute(
            "DELETE FROM pghistory_context WHERE id = %s", [str(context_id)]
        )


def _clear_cache():
    try:
        from django.core.cache import cache

        cache.clear()
    except Exception:  # noqa: BLE001 - a missing cache table must not undo a run
        logger.warning("could not clear the cache after the demonstration run")


class Refused(Exception):
    """A load or a removal that was turned down; the message is the sentence."""


def load(stdout=None):
    """Load the demonstration into this site. Returns the counts it wrote.

    Everything runs in one transaction: a load that fails saves nothing.
    """
    refusal = load_refusal()
    if refusal:
        raise Refused(refusal)
    from core.models import SiteConfig

    with pghistory.context(action="load_demonstration") as context:
        with transaction.atomic():
            run_steps(stdout=stdout)
            site = SiteConfig.objects.first()
            if site is not None and not site.demonstration_mode:
                site.demonstration_mode = True
                site.save(update_fields=["demonstration_mode"])
            counts = content_counts()
            forget_events(context.id)
    _clear_cache()
    return counts


def _kept_counts():
    kept = {}
    for label in KEPT_LABELS:
        try:
            kept[label] = apps.get_model(label).objects.count()
        except LookupError:
            continue
    for model in apps.get_models():
        if model._meta.app_label in KEPT_APPS and not model._meta.proxy and model._meta.managed:
            if model._meta.app_label in {"gis", "pghistory"}:
                continue
            kept[model._meta.label] = model.objects.count()
    return kept


def _deletion_order(models):
    """Models in the order to empty them: a table before the tables it points at."""
    by_label = {m._meta.label: m for m in models}
    graph = {label: set() for label in by_label}
    for label, model in by_label.items():
        for field_ in model._meta.get_fields():
            if field_.is_relation and field_.many_to_one and field_.concrete:
                parent = field_.related_model._meta.label
                if parent in by_label and parent != label:
                    # The parent must wait for this table, so this table comes first.
                    graph[parent].add(label)
    sorter = graphlib.TopologicalSorter(graph)
    try:
        return [by_label[label] for label in sorter.static_order()]
    except graphlib.CycleError:
        return list(models)


def _restore_reference_lists():
    """Put back the two reference lists a load adds to.

    The demonstration's lab file teaches the analyte list names and DDW codes
    it did not have (the lab import learns both), and its wells add a well type.
    After the content tables are empty nothing points at those rows, so the
    lists go back to what ``seed_data`` writes: its analytes with no DDW code
    (it seeds none) and its well types. A row something still points at stays.
    """
    from django.db.models import ProtectedError

    from core.modules import is_enabled

    if is_enabled("drinking"):
        from drinking.management.commands.seed_drinking import SEED
        from drinking.models import Analyte

        seeded = {row[0] for row in SEED}
        Analyte.objects.filter(name__in=seeded).exclude(ddw_code__isnull=True).update(
            ddw_code=None
        )
        for analyte in Analyte.objects.exclude(name__in=seeded).filter(limits__isnull=True):
            try:
                analyte.delete()
            except ProtectedError:
                continue
    if is_enabled("wells"):
        from wells.management.commands.seed_well_types import WELL_TYPES
        from wells.models import WellType

        for well_type in WellType.objects.exclude(name__in=[t["name"] for t in WELL_TYPES]):
            try:
                well_type.delete()
            except ProtectedError:
                continue


def remove(stdout=None):
    """Remove the demonstration from this site. Returns the counts it removed."""
    from accounting.locks import override
    from core.models import SiteConfig

    if not is_loaded():
        raise Refused(NOT_LOADED_SENTENCE)

    with pghistory.context(action="remove_demonstration") as context:
        with transaction.atomic():
            kept_before = _kept_counts()
            removed = content_counts()
            models = [m for _, m in content_models()]
            ordered = _deletion_order(models)
            # The finalized-year lock is switched off for the removal: the
            # demonstration's first water year is finalized.
            with override("The demonstration data was removed."):
                for model in ordered:
                    model.objects.all().delete()
            _restore_reference_lists()
            site = SiteConfig.objects.first()
            if site is not None:
                if site.agency_name == DEMONSTRATION_NAME:
                    site.delete()
                elif site.demonstration_mode:
                    site.demonstration_mode = False
                    site.save(update_fields=["demonstration_mode"])
            left = content_counts()
            if left:
                raise Refused(
                    "The demonstration data was not removed, because "
                    f"{describe(left, limit=6)} could not be deleted. Nothing was removed."
                )
            kept_after = _kept_counts()
            # SiteConfig is the one kept table a removal may change.
            kept_before.pop("core.SiteConfig", None)
            kept_after.pop("core.SiteConfig", None)
            if kept_before != kept_after:
                raise Refused(
                    "The demonstration data was not removed, because the removal "
                    "reached records that are not part of it. Nothing was removed."
                )
            forget_events(context.id)
    _clear_cache()
    return removed


# -- Starting a run from the page ---------------------------------------------

COMMANDS = {"load": "load_demonstration", "remove": "remove_demonstration"}


def start_worker(action, record_pk=None, user_pk=None):
    """Start ``manage.py load_demonstration`` or ``remove_demonstration`` without
    making the page wait.

    The worker runs in its own process and session, so it outlives the web
    worker that started it. Only fixed words and integers reach the command
    line. It starts after the surrounding transaction commits, so the new
    process sees the run's record. With ``settings.OPENH2O_CALCULATION_INLINE``
    true (the test suite) the command runs in this process instead.
    """
    command = COMMANDS[action]
    args = []
    if record_pk is not None:
        args += ["--record", str(int(record_pk))]
    if user_pk is not None:
        args += ["--user", str(int(user_pk))]

    if getattr(settings, "OPENH2O_CALCULATION_INLINE", False):
        call_command(command, *args)
        return

    def _launch():
        subprocess.Popen(
            [sys.executable, "manage.py", command, *args],
            cwd=settings.BASE_DIR,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ,
        )

    transaction.on_commit(_launch)


# -- What a run says -----------------------------------------------------------


def _records(counts):
    n = total(counts)
    return f"{n:,} record{'' if n == 1 else 's'}"


def load_outcome(counts):
    return f"Loaded the demonstration data ({_records(counts)})."


def remove_outcome(counts):
    return f"Removed the demonstration data ({_records(counts)})."


def failure_sentence(action, exc):
    verb = "loaded" if action == "load" else "removed"
    nothing = "Nothing was saved." if action == "load" else "Nothing was removed."
    detail = str(exc).strip() or exc.__class__.__name__
    return f"The demonstration data was not {verb}: {detail} {nothing}"
