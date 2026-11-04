# SPDX-License-Identifier: AGPL-3.0-or-later
"""The year's fingerprint: one code computed from the records of a water year.

:func:`compute` reads every row of the tables the year's figures rest on (the
locked tables, plus the use areas those rows belong to), and every Change
history entry of those rows, and returns one SHA-256 digest per part and one for
the whole year. Check recomputes it and names the parts that differ.

**How a row is written down.** A row is its columns in a fixed order, as JSON
with sorted keys and compact separators; a Decimal is its normalized text, a
float its ``repr``, a date or datetime ISO text, a UUID its string. Nothing is
turned into text by a catch-all: a type this module does not know raises, so a
new kind of column is noticed the first time it is read instead of being
written down under a guess. Rows are read in key order through the default
managers, so struck rows (voided or replaced) are in, and through
``values_list(...).iterator()``, so a large year is not held in memory.

**What each part reads.** The table's columns except any geometry column
(tested by field class, on the models and on their event tables). A row is in
the year by the same rule the finalized-year lock uses on it
(``accounting/locks.py``); ``tests/test_fingerprint_04.py`` compares the two on
every table. Three parts read less than the whole row, so ordinary work in a
closed year does not read as a changed record:

* Use areas: only the use areas with a ledger row or a calculation in the year,
  and only their id, number and the columns a correction or void writes;
* Fallow periods: the end month is read no later than the year's last month
  (the lock lets a running period be ended after the year);
* the Change history of those two tables is left out.

**What a fingerprint remembers.** The columns it read, table by table, event
tables included. Check recomputes over exactly those tables and columns, so a
table or column a later version adds is ignored by an older fingerprint. A
stored table or column that no longer exists cannot be read again: the part is
reported as unreadable, never as a difference.

Nothing here imports a model: every model is looked up by its label through the
app registry, because most belong to optional modules (``core`` is required).
A model that is not installed when the code is taken is not a part of that code.
"""

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from django.apps import apps
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import FieldError
from django.db.models import Q
from django.utils import timezone

#: Version of the stored shape (``ReportingPeriod.fingerprint_parts``).
VERSION = 1

#: The key of the Change history part.
HISTORY = "history"

#: Every part, in the fixed order the whole-year digest is written in: ``(key, words)``.
#: A table's key is its model label. The words are what the page and the file print.
PARTS = (
    ("parcels.ParcelLedger", "Use ledger"),
    ("accounting.WaterAccountParcel", "Account use areas"),
    ("accounting.AllocationPlan", "Allocations"),
    ("accounting.WaterCredit", "Water credits"),
    ("accounting.WaterCreditDraw", "Water credit draws"),
    ("accounting.AllocationCarryover", "Carry-over"),
    ("accounting.AccountCredit", "Account credits"),
    ("accounting.CalculationRun", "Calculation results"),
    ("surface.DiversionRecord", "Diversion records"),
    ("surface.UnallocatedDelivery", "Unallocated deliveries"),
    ("surface.CanalMonthLoss", "Canal losses"),
    ("measurements.MeterReading", "Meter readings"),
    ("measurements.WaterMeasurement", "Water levels"),
    ("recharge.RechargeEvent", "Recharge events"),
    ("recharge.RechargeMeasurement", "Recharge measurements"),
    ("parcels.FallowPeriod", "Fallow periods"),
    ("datasync.TypedReading", "Station readings"),
    ("drinking.SystemProduction", "Production records"),
    ("drinking.SampleResult", "Lab results"),
    ("accounting.PeriodStatement", "Filed figures records"),
    ("accounting.PeriodStatementRow", "Figures as filed"),
    ("parcels.Parcel", "Use areas"),
    (HISTORY, "Change history"),
)

PART_KEYS = tuple(key for key, _ in PARTS)
PART_NAMES = dict(PARTS)

#: The tables a fingerprint reads rows of: every part but the Change history.
COVERED_MODELS = tuple(key for key in PART_KEYS if key != HISTORY)

USE_AREAS = "parcels.Parcel"
FALLOW_PERIODS = "parcels.FallowPeriod"

#: Parts whose Change history is left out.
NO_HISTORY = frozenset({USE_AREAS, FALLOW_PERIODS})

#: The only columns the Use areas part reads.
USE_AREA_COLUMNS = (
    "id",
    "parcel_number",
    "voided_at",
    "voided_by_id",
    "void_reason",
    "replaced_at",
    "replaces_id",
    "change_reason",
)

#: Who made each change: the one table that is not an event table.
CONTEXT = "pghistory.Context"
CONTEXT_COLUMNS = ("id", "metadata")

#: How many primary keys one event query names.
_CHUNK = 5000


# -- The printed code ---------------------------------------------------------------------


def short_code(digest):
    """``0AB1-0181-4EB9-3DFD-02D4``: the first 20 characters, uppercase, five groups of four."""
    head = (digest or "")[:20].upper()
    return "-".join(head[i : i + 4] for i in range(0, 20, 4))


# -- Writing a row down -------------------------------------------------------------------


def plain(value):
    """``value`` as something ``json`` writes the same way every time, or raise ``TypeError``."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    raise TypeError(f"The fingerprint does not know how to write a {type(value).__name__}.")


def canonical(row):
    """One row as the text its digest is fed."""
    return json.dumps(plain(row), sort_keys=True, separators=(",", ":"))


def _feed(digest, row):
    digest.update(canonical(row).encode())
    digest.update(b"\n")


def whole_digest(parts):
    """The year's digest from its parts: ``name:digest`` lines in the fixed part order.

    ``parts`` maps a part key to a dict holding its ``digest``. Only the keys
    present are written, so a fingerprint taken before a part existed still
    agrees with itself.
    """
    lines = "".join(f"{PART_NAMES[key]}:{parts[key]['digest']}\n" for key in PART_KEYS if key in parts)
    return hashlib.sha256(lines.encode()).hexdigest()


# -- Which rows are in the year ----------------------------------------------------------------


def _month_firsts(period):
    """The first day of each month that falls inside the year: the months the lock reads."""
    day = period.start_date.replace(day=1)
    if day < period.start_date:
        day = _next_month(day)
    found = []
    while day <= period.end_date:
        found.append(day)
        day = _next_month(day)
    return found


def _next_month(day):
    return (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _day_range(period):
    """The year as a half-open range of datetimes, in the site's own time zone."""
    zone = timezone.get_default_timezone()
    return (
        timezone.make_aware(dt.datetime.combine(period.start_date, dt.time.min), zone),
        timezone.make_aware(dt.datetime.combine(period.end_date + dt.timedelta(days=1), dt.time.min), zone),
    )


def water_year_label(period):
    """The water year the year's end month falls in, by the site's start month (October if none)."""
    site = apps.get_model("core", "SiteConfig").objects.order_by("id").first()
    start = site.water_year_start_month if site else 10
    return period.end_date.year + (1 if start > 1 and period.end_date.month >= start else 0)


def _production_rule(period):
    """The production records dated to a month of the year.

    A record is dated the first day of its month; one with no month (or none
    from 1 to 12) is read as January, as the lock reads it.
    """
    rule = Q(pk__in=[])
    for day in _month_firsts(period):
        rule |= Q(year=day.year, month=day.month)
        if day.month == 1:
            rule |= Q(year=day.year) & (Q(month__isnull=True) | ~Q(month__range=(1, 12)))
    return rule


def rules(period):
    """Which rows of each table are in the year: ``{label: Q}``, the lock's own rule for the table."""
    span = (period.start_date, period.end_date)
    low, high = _day_range(period)
    firsts = _month_firsts(period)
    months = [f"{day.year}-{day.month:02d}" for day in firsts]
    label = water_year_label(period)
    first_month = period.start_date.replace(day=1)
    return {
        "parcels.ParcelLedger": Q(effective_date__range=span) | Q(reporting_period=period),
        "accounting.WaterAccountParcel": Q(reporting_period=period),
        "accounting.AllocationPlan": Q(reporting_period=period),
        "accounting.WaterCredit": Q(origin_period__in=months),
        "accounting.WaterCreditDraw": Q(draw_period__in=months),
        "accounting.AllocationCarryover": Q(water_year=label),
        "accounting.AccountCredit": Q(water_year=label),
        "accounting.CalculationRun": Q(period_start__range=span)
        | Q(period_start__isnull=True, period__in=months),
        "surface.DiversionRecord": Q(month__range=span) | Q(reporting_period=period),
        "surface.UnallocatedDelivery": Q(month__range=span) | Q(reporting_period=period),
        "surface.CanalMonthLoss": Q(month__range=span),
        "measurements.MeterReading": Q(reading_date__gte=low, reading_date__lt=high),
        "measurements.WaterMeasurement": Q(measurement_date__gte=low, measurement_date__lt=high),
        "recharge.RechargeEvent": Q(start_date__range=span),
        "recharge.RechargeMeasurement": Q(measurement_date__gte=low, measurement_date__lt=high),
        "parcels.FallowPeriod": (Q(start_month__isnull=True) | Q(start_month__lte=period.end_date))
        & (Q(end_month__isnull=True) | Q(end_month__gte=first_month)),
        "datasync.TypedReading": Q(observation_date__range=span),
        "drinking.SystemProduction": _production_rule(period),
        "drinking.SampleResult": Q(event__sample_date__range=span),
        "accounting.PeriodStatement": Q(period=period),
        "accounting.PeriodStatementRow": Q(period=period),
    }


def _model(label):
    """The model, or None when its app is not installed."""
    try:
        return apps.get_model(label)
    except (LookupError, ValueError):
        return None


def selection(period, label):
    """The rows of table ``label`` that are in the year, unordered; None when the table is not installed.

    The default manager, so voided and replaced rows are in.
    """
    model = _model(label)
    if model is None:
        return None
    if label == USE_AREAS:
        return model._default_manager.filter(pk__in=_use_area_ids(period))
    return model._default_manager.filter(rules(period)[label])


def _use_area_ids(period):
    """The use areas with a ledger row or a calculation in the year."""
    found = set()
    rule = rules(period)
    for label in ("parcels.ParcelLedger", "accounting.CalculationRun"):
        model = _model(label)
        if model is not None:
            found |= set(model._default_manager.filter(rule[label]).values_list("parcel_id", flat=True))
    return found


# -- Columns -------------------------------------------------------------------------------------


def _readable_columns(model):
    """Every concrete column of ``model`` that is not a geometry, by database attribute name."""
    return [
        field.attname
        for field in model._meta.concrete_fields
        if not isinstance(field, gis_models.GeometryField)
    ]


class Unreadable(Exception):
    """A part that cannot be recomputed from what the fingerprint stored."""


def _columns_for(model, key, stored):
    """The columns to read for ``key``: the stored list when checking, else the current ones."""
    if stored is None:
        return list(USE_AREA_COLUMNS) if key == USE_AREAS else _readable_columns(model)
    try:
        wanted = list(stored[key])
    except (KeyError, TypeError):
        raise Unreadable(key) from None
    have = set(_readable_columns(model))
    if any(column not in have for column in wanted):
        raise Unreadable(key)
    return wanted


# -- Computing ----------------------------------------------------------------------------------


@dataclass
class Computed:
    """What :func:`compute` read."""

    digest: str = ""
    #: ``{key: {"name", "digest", "rows"}}`` for each part computed.
    parts: dict = field(default_factory=dict)
    #: ``{label: [column, ...]}`` for each table read, event tables and the context table included.
    columns: dict = field(default_factory=dict)
    #: Keys of the parts a stored fingerprint names that cannot be recomputed now.
    unreadable: list = field(default_factory=list)


def _fallow_reader(columns, period):
    """The row as the Fallow periods part reads it: the end month no later than the year's last month."""
    if "end_month" not in columns:
        return lambda row: row
    index = columns.index("end_month")
    last = period.end_date.replace(day=1)

    def read(row):
        end = row[index]
        if end is None or end > last:
            end = last
        return row[:index] + (end,) + row[index + 1 :]

    return read


def _read_table(period, key, model, columns):
    """``(digest, rows, primary keys)`` of the year's rows of one table."""
    queryset = selection(period, key).order_by("pk")
    pk_name = model._meta.pk.attname
    pk_index = columns.index(pk_name) if pk_name in columns else None
    reader = _fallow_reader(columns, period) if key == FALLOW_PERIODS else (lambda row: row)
    digest = hashlib.sha256()
    count = 0
    pks = []
    for row in queryset.values_list(*columns).iterator(chunk_size=2000):
        _feed(digest, reader(row))
        count += 1
        if pk_index is not None:
            pks.append(row[pk_index])
    if pk_index is None:
        pks = list(queryset.values_list("pk", flat=True))
    return digest.hexdigest(), count, pks


def _event_label(key):
    return f"{key}Event"


def _read_history(selected, stored):
    """``(digest, rows, columns)`` of the Change history of the selected rows.

    ``selected`` maps a part key to its primary keys, in part order. Raises
    :class:`Unreadable` when a stored event table or column is gone.
    """
    digest = hashlib.sha256()
    count = 0
    columns = {}
    contexts = set()
    if stored is None:
        labels = [key for key in selected if key not in NO_HISTORY and _model(_event_label(key))]
    else:
        labels = [key for key in selected if _event_label(key) in stored]
        # A stored event table whose tracked table is no longer read cannot be selected.
        for name in stored:
            if name not in PART_NAMES and name != CONTEXT and name[: -len("Event")] not in selected:
                raise Unreadable(name)
    for key in labels:
        event = _model(_event_label(key))
        if event is None:
            raise Unreadable(_event_label(key))
        cols = _columns_for(event, _event_label(key), stored)
        columns[_event_label(key)] = cols
        context_index = cols.index("pgh_context_id") if "pgh_context_id" in cols else None
        order = event._meta.pk.attname
        pks = selected[key]
        for start in range(0, len(pks), _CHUNK):
            chunk = pks[start : start + _CHUNK]
            rows = (
                event._default_manager.filter(pgh_obj_id__in=chunk)
                .order_by(order)
                .values_list(*cols)
                .iterator(chunk_size=2000)
            )
            for row in rows:
                _feed(digest, row)
                count += 1
                if context_index is not None and row[context_index]:
                    contexts.add(row[context_index])
    context = _model(CONTEXT)
    if context is None:
        raise Unreadable(CONTEXT)
    cols = list(CONTEXT_COLUMNS) if stored is None else _columns_for(context, CONTEXT, stored)
    columns[CONTEXT] = cols
    rows = context._default_manager.filter(pk__in=contexts).order_by("pk").values_list(*cols).iterator()
    for row in rows:
        _feed(digest, row)
    return digest.hexdigest(), count, columns


def compute(period, stored=None):
    """Read the year and return a :class:`Computed`.

    With no ``stored`` this is a fresh fingerprint: every part whose table is
    installed, over every readable column. With ``stored`` (the shape kept in
    ``ReportingPeriod.fingerprint_parts``) it reads exactly the parts and
    columns that fingerprint kept, and lists the parts it cannot read again in
    ``unreadable``; those have no digest.
    """
    stored_columns = None if stored is None else stored.get("columns", {})
    wanted = None if stored is None else set(stored.get("parts", {}))
    result = Computed()
    selected = {}
    broken = set()
    for key in COVERED_MODELS:
        if wanted is not None and key not in wanted:
            continue
        model = _model(key)
        if model is None:
            if stored is not None:
                result.unreadable.append(key)
                broken.add(key)
            continue
        try:
            columns = _columns_for(model, key, stored_columns)
            digest, rows, pks = _read_table(period, key, model, columns)
        except (Unreadable, FieldError):
            result.unreadable.append(key)
            broken.add(key)
            continue
        result.parts[key] = {"name": PART_NAMES[key], "digest": digest, "rows": rows}
        result.columns[key] = columns
        selected[key] = pks
    if wanted is None or HISTORY in wanted:
        history_needs = {key for key in selected if key not in NO_HISTORY}
        try:
            # A history that names a table whose rows could not be read cannot be selected either.
            if broken & set(COVERED_MODELS) - NO_HISTORY and wanted is not None:
                raise Unreadable(HISTORY)
            digest, rows, columns = _read_history(
                {key: selected[key] for key in selected if key in history_needs}, stored_columns
            )
        except (Unreadable, FieldError):
            result.unreadable.append(HISTORY)
        else:
            result.parts[HISTORY] = {"name": PART_NAMES[HISTORY], "digest": digest, "rows": rows}
            result.columns.update(columns)
    result.unreadable.sort(key=PART_KEYS.index)
    result.digest = whole_digest(result.parts)
    return result
