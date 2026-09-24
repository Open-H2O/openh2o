# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading change history back: the rows ``/changes/`` shows.

The recording side is ``core/history.py``. This module turns the recorded events
into rows a person can read: when, who, which record, what changed (field,
before, after) and the note.

``changes_for`` also fed the History panel on record pages until 147-02
(Brent's 2026-09-24 checkpoint ruling removed the panel; keep the recording,
strip the display). It stays here, tested directly, because it is the same
one-record reading path ``/changes/``'s own ``?type=&record=`` filter uses.

**One row per record per action.** A single request or command can write the
same row more than once (a step reorder lifts every moved step out of the way,
then sets its final place). Events are grouped by record and by the context
they were made under, and a row shows the state before the first event and
after the last. A group whose net effect changed nothing is not shown.

**Values come from the native event columns, never from pghistory's
``pgh_diff``.** That aggregate goes through JSON and returns a Decimal as a
float (measured 2026-09-23: ``12.5000`` and ``12.7500`` came back as ``12.5``
and ``12.75``). Every update records the row as it was (``before_update``) and
as it became (``update``), so the before value is always the recorded one,
never an inference from an earlier event that may not exist.

**Query count does not grow with the history.** One grouped query finds the
page's rows across every event table, then one query per event table on the
page, one per related table named, one for contexts and one for people.

Nothing here imports a model at module scope (``core`` is required; most
tracked models belong to optional modules).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal

from django.apps import apps
from django.core.paginator import Paginator
from django.db import connection, models
from django.urls import NoReverseMatch
from django.utils import timezone
from django.utils.text import capfirst

from core.history import LABEL_BEFORE_UPDATE
from core.identifiers import kind_for

PAGE_SIZE = 50
PANEL_SIZE = 10

LABEL_BEFORE = LABEL_BEFORE_UPDATE
LABEL_INSERT = "insert"
LABEL_UPDATE = "update"
LABEL_DELETE = "delete"

# Columns a reader never needs in a list of changes: the row's own key and the
# time it was first created (neither ever changes).
HIDDEN_FIELDS = frozenset({"id", "created_at"})

# The longest value shown in a cell before it is cut (a JSON breakdown can run
# to kilobytes).
VALUE_MAX = 160

COMMAND_FILTER = "commands"


# -- The event tables ---------------------------------------------------------


def event_models():
    """Every event model of a running module, keyed by its tracked model's label.

    A schema-resident module switched off keeps its tables (and so its event
    tables), but its records are not this deployment's business: leaving it
    out here keeps its record names off the record-type filter, the same way
    its pages and nav disappear (``tests/droppability``).
    """
    from pghistory.models import Event

    from core.modules import MODULE_REGISTRY, enabled_module_names

    running = set(enabled_module_names())
    owner = {app: name for name, spec in MODULE_REGISTRY.items() for app in spec.apps}
    found = {}
    for model in apps.get_models():
        if not issubclass(model, Event) or model._meta.abstract:
            continue
        tracked = getattr(model, "pgh_tracked_model", None)
        if tracked is None or model._meta.proxy or not model._meta.managed:
            continue
        if owner.get(tracked._meta.app_label) not in running:
            continue
        found[tracked._meta.label] = model
    return found


# What the pages call a record, where that differs from the model's own name.
# A use area is stored as a `Parcel` and every page says "use area" (copy rule
# 4: one name per thing), so its history says it too.
RECORD_TYPE_NAMES = {
    "parcels.Parcel": "Use area",
    "parcels.ParcelLedger": "Ledger entry",
    "geography.ParcelZone": "Zone membership",
    "accounting.WaterAccountParcel": "Account use area",
    "accounting.AllocationPlan": "Allocation",
    "wells.WellIrrigatedParcel": "Well use area share",
    "surface.PointOfDiversionParcel": "Point of diversion use area share",
    "surface.WaterRightParcel": "Water right place of use",
    "surface.ParcelIrrigationMethod": "Use area irrigation method",
    "core.SiteConfig": "Site settings",
    "drinking.SamplingSchedule": "Sampling schedule row",
}


# The records a record's page edits besides itself: a well's page sets the
# share each linked use area takes, a point of diversion's page records its
# monthly diversions. A reader who changes one there looks for it in that
# page's History panel, so a record's history includes these, found by the
# foreign key the history row copied (as a plain id column, core/history.py).
# A use area's ledger entries are left out on purpose: the engine rewrites
# them every run, and ten of them would push every edit a person made off the
# panel. They are one filter away on the Change history page.
RELATED_RECORDS = {
    "parcels.Parcel": (
        ("wells.WellIrrigatedParcel", "parcel"),
        ("surface.PointOfDiversionParcel", "parcel"),
        ("surface.WaterRightParcel", "parcel"),
        ("surface.ParcelIrrigationMethod", "parcel"),
        ("geography.ParcelZone", "parcel"),
        ("accounting.WaterAccountParcel", "parcel"),
    ),
    "wells.Well": (
        ("wells.WellIrrigatedParcel", "well"),
        ("wells.WellMeter", "well"),
    ),
    "surface.PointOfDiversion": (
        ("surface.DiversionRecord", "point_of_diversion"),
        ("surface.PointOfDiversionParcel", "point_of_diversion"),
        ("surface.PointOfDiversionDevice", "point_of_diversion"),
        ("surface.UnallocatedDelivery", "point_of_diversion"),
    ),
    "surface.WaterRight": (
        ("surface.WaterRightParcel", "water_right"),
        ("surface.PointOfDiversion", "water_right"),
    ),
    "accounting.WaterAccount": (
        ("accounting.WaterAccountParcel", "water_account"),
        ("surface.WaterAccountDeliveryPoint", "account"),
    ),
    "accounting.ReportingPeriod": (
        ("accounting.AllocationPlan", "reporting_period"),
    ),
}


def related_records(label):
    """(child label, id column) pairs whose changes join ``label``'s history."""
    pairs = []
    for child, field_name in RELATED_RECORDS.get(label, ()):
        try:
            column = apps.get_model(child)._meta.get_field(field_name).column
        except LookupError:
            continue  # the child's module is not installed on this deployment
        pairs.append((child, column))
    return pairs


def record_type_name(model):
    """The sentence-case name a page uses for one kind of record."""
    label = model._meta.label
    if label in RECORD_TYPE_NAMES:
        return RECORD_TYPE_NAMES[label]
    return capfirst(str(model._meta.verbose_name).lower())


def field_name(model_field):
    """A field's label in a change row: its verbose name, sentence case.

    A link to a use area is labelled "Use area", the pages' word for a parcel.
    """
    if (
        isinstance(model_field, models.ForeignKey)
        and model_field.related_model._meta.label == "parcels.Parcel"
    ):
        return "Use area"
    return capfirst(str(model_field.verbose_name))


def record_types():
    """(label, name) for the record-type filter, sorted by name."""
    pairs = [
        (label, record_type_name(model.pgh_tracked_model))
        for label, model in event_models().items()
    ]
    return sorted(pairs, key=lambda pair: pair[1].lower())


# Fields that belong to a module other than their model's own. `core.SiteConfig`
# is required, but these settings exist for `surface` alone (DeliverySettingsForm
# hides them without it), so a deployment without `surface` never shows their
# history either.
FIELD_MODULES = {
    "core.SiteConfig.default_irrigation_efficiency": "surface",
    "core.SiteConfig.groundwater_efficiency": "wells",
    "core.SiteConfig.diversion_use_type_rule": "surface",
    "core.SiteConfig.diversion_report_year_rule": "surface",
    "core.SiteConfig.season_start_month": "surface",
}


def tracked_fields(event_model, only=None):
    """The tracked model's fields that the event model copies, in model order.

    ``only`` limits them to the named fields (a page's History panel naming
    the settings that page edits).
    """
    from core.modules import enabled_module_names

    running = set(enabled_module_names())
    tracked = event_model.pgh_tracked_model
    label = tracked._meta.label
    copied = {f.name for f in event_model._meta.concrete_fields}
    return [
        f
        for f in tracked._meta.concrete_fields
        if f.name in copied
        and f.name not in HIDDEN_FIELDS
        and FIELD_MODULES.get(f"{label}.{f.name}", None) in (None, *running)
        and (only is None or f.name in only)
    ]


# -- Formatting ---------------------------------------------------------------


def format_decimal(value):
    """A stored Decimal exactly, with at least two decimal places.

    ``Decimal("12.5000")`` -> ``"12.50"``; ``Decimal("12.5010")`` -> ``"12.501"``.
    Trailing zeros past the second place are storage padding, not precision
    anyone entered; every other digit is kept, so a change in the third place
    is never hidden by rounding.
    """
    normalized = value.normalize()
    if normalized.as_tuple().exponent > -2:
        normalized = value.quantize(Decimal("0.01"))
    text = format(normalized, "f")
    return "0.00" if text in ("-0.00", "-0") else text


def _format_value(model_field, value, names):
    if value is None or value == "":
        return ""
    if isinstance(model_field, models.ForeignKey):
        related = model_field.related_model._meta.label
        return names.get((related, value)) or f"#{value} (removed)"
    if model_field.choices:
        label = dict(model_field.flatchoices).get(value)
        if label is not None:
            return str(label)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, default=str)
    else:
        text = str(value)
    return text if len(text) <= VALUE_MAX else text[: VALUE_MAX - 1] + "…"


def _dict_changes(model_field, old, new, names):
    """One row per key that changed in a JSON settings column.

    A methodology step keeps its settings as one JSON value; showing the whole
    value before and after would bury the one setting that moved.
    """
    rows = []
    for key in sorted(set(old) | set(new)):
        if key in old and key in new and old[key] == new[key]:
            continue
        label = f"{field_name(model_field)}, {str(key).replace('_', ' ')}"
        rows.append(
            FieldChange(
                label,
                _format_value(model_field, old.get(key), names) if key in old else "",
                _format_value(model_field, new.get(key), names) if key in new else "",
            )
        )
    return rows


# -- Rows ---------------------------------------------------------------------


@dataclass
class FieldChange:
    name: str
    before: str
    after: str


@dataclass
class ChangeRow:
    when: datetime
    action: str  # "added", "changed" or "removed"
    record_type: str
    record_name: str
    record_url: str
    who: str
    note: str
    changes: list = field(default_factory=list)
    model_label: str = ""
    object_id: int = 0


def _index_sql(filters):
    """The grouped query over every event table the filters admit.

    Returns (sql, params) selecting model, object id, first and last event id,
    the time of the last event and the context id, one row per record per
    context, newest first.
    """
    by_label = event_models()
    # (label, column that must equal the record's id or None) per event table.
    if filters.get("record_type") and filters.get("object_id") is not None:
        targets = [(filters["record_type"], "pgh_obj_id")] + [
            (child, column)
            for child, column in related_records(filters["record_type"])
            if child in by_label
        ]
    elif filters.get("record_type"):
        targets = [(filters["record_type"], None)]
    else:
        targets = [(label, None) for label in sorted(by_label)]
    where, params_each = [], []
    if filters.get("since") is not None:
        where.append("pgh_created_at >= %s")
        params_each.append(filters["since"])
    if filters.get("until") is not None:
        where.append("pgh_created_at < %s")
        params_each.append(filters["until"])
    person = filters.get("person")
    if person == COMMAND_FILTER:
        where.append(
            "pgh_context_id IN (SELECT id FROM pghistory_context"
            " WHERE metadata ? 'command')"
        )
    elif person:
        where.append(
            "pgh_context_id IN (SELECT id FROM pghistory_context"
            " WHERE metadata->>'user' = %s)"
        )
        params_each.append(str(person))
    branches, params = [], []
    for label, column in targets:
        table = connection.ops.quote_name(by_label[label]._meta.db_table)
        conditions, values = list(where), list(params_each)
        if column is not None:
            conditions.insert(0, f"{connection.ops.quote_name(column)} = %s")
            values.insert(0, filters["object_id"])
        clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        branches.append(
            f"SELECT %s AS model, pgh_obj_id AS obj, pgh_id, pgh_created_at,"
            f" pgh_context_id,"
            f" COALESCE(pgh_context_id::text, pgh_created_at::text) AS grp"
            f" FROM {table}{clause}"
        )
        params.extend([label, *values])
    union = " UNION ALL ".join(branches)
    sql = (
        "SELECT model, obj, MIN(pgh_id), MAX(pgh_id), MAX(pgh_created_at) AS at,"
        " MIN(pgh_context_id::text)"
        f" FROM ({union}) AS u GROUP BY model, obj, grp"
    )
    return sql, params


class _ChangeIndex:
    """A lazy, sliceable list of change rows, for Django's Paginator."""

    def __init__(self, filters):
        self.filters = filters
        self._count = None

    def count(self):
        if self._count is None:
            if not event_models():
                self._count = 0
            else:
                sql, params = _index_sql(self.filters)
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM ({sql}) AS g", params)
                    self._count = cursor.fetchone()[0]
        return self._count

    def __len__(self):
        return self.count()

    def __getitem__(self, key):
        if not isinstance(key, slice):
            raise TypeError("change rows are read a page at a time")
        start, stop = key.start or 0, key.stop
        if not event_models() or stop is not None and stop <= start:
            return []
        sql, params = _index_sql(self.filters)
        limit = "" if stop is None else f" LIMIT {int(stop - start)}"
        with connection.cursor() as cursor:
            cursor.execute(
                f"{sql} ORDER BY at DESC, MAX(pgh_id) DESC{limit} OFFSET {int(start)}",
                params,
            )
            groups = cursor.fetchall()
        only = self.filters.get("fields")
        return build_rows(
            groups, only={self.filters["record_type"]: only} if only else None
        )


def build_rows(groups, only=None):
    """Turn index rows (model, obj, first id, last id, at, context) into ChangeRows."""
    from pghistory.models import Context

    by_label = event_models()
    wanted = {}
    for label, _obj, first_id, last_id, _at, _ctx in groups:
        wanted.setdefault(label, set()).update({first_id, last_id})

    events = {}
    for label, ids in wanted.items():
        for event in by_label[label].objects.filter(pgh_id__in=ids):
            events[(label, event.pgh_id)] = event

    # Names for every record a row names or a foreign key points at, one query
    # per table.
    to_name = {}
    for label, obj, first_id, last_id, _at, _ctx in groups:
        to_name.setdefault(label, set()).add(obj)
        event_model = by_label[label]
        for event_id in (first_id, last_id):
            event = events.get((label, event_id))
            if event is None:
                continue
            for model_field in tracked_fields(event_model):
                if isinstance(model_field, models.ForeignKey):
                    value = getattr(event, model_field.name)
                    if value is not None:
                        related = model_field.related_model._meta.label
                        to_name.setdefault(related, set()).add(value)
    names, live = _names_for(to_name)

    context_ids = {ctx for *_rest, ctx in groups if ctx}
    contexts = {
        str(c.pk): c.metadata or {}
        for c in Context.objects.filter(pk__in=context_ids)
    }
    people = _people_for(contexts.values())

    rows = []
    for label, obj, first_id, last_id, at, ctx in groups:
        row = _row_for(
            label,
            obj,
            events.get((label, first_id)),
            events.get((label, last_id)),
            at,
            contexts.get(ctx or "", {}),
            people,
            names,
            live,
            (only or {}).get(label),
        )
        if row is not None:
            rows.append(row)
    return rows


def _names_for(to_name):
    """(names, live): display names and live instances, keyed (label, pk)."""
    names, live = {}, {}
    for label, ids in to_name.items():
        try:
            model = apps.get_model(label)
        except LookupError:
            continue
        forward = [
            f.name
            for f in model._meta.concrete_fields
            if isinstance(f, models.ForeignKey)
        ]
        for obj in model._default_manager.select_related(*forward).filter(pk__in=ids):
            names[(label, obj.pk)] = str(obj)
            live[(label, obj.pk)] = obj
    return names, live


def _people_for(contexts):
    User = apps.get_model("core", "User")
    ids = set()
    for metadata in contexts:
        user = metadata.get("user")
        if user is not None:
            try:
                ids.add(int(user))
            except (TypeError, ValueError):
                continue
    return {user.pk: user for user in User.objects.filter(pk__in=ids)}


def person_name(user):
    return user.get_full_name().strip() or user.email or user.username


def who_for(metadata, people):
    user = metadata.get("user")
    if user is not None:
        try:
            person = people.get(int(user))
        except (TypeError, ValueError):
            person = None
        if person is not None:
            return person_name(person)
        return f"former user #{user}"
    command = metadata.get("command")
    if command:
        return f"a command: {command}"
    return "not recorded"


def _record_url(obj):
    if obj is None:
        return ""
    if kind_for(obj):
        from core.identifiers import identifier_for

        return identifier_for(obj, base="")
    get_url = getattr(obj, "get_absolute_url", None)
    if get_url is None:
        return ""
    try:
        return get_url()
    except NoReverseMatch:
        return ""


def _row_for(label, obj_id, first, last, at, metadata, people, names, live, only=None):
    if first is None or last is None:
        return None
    event_model = type(last)
    tracked = event_model.pgh_tracked_model
    fields_ = tracked_fields(event_model, only)

    def values(event):
        return {f.name: getattr(event, f.name) for f in fields_}

    if first.pgh_label == LABEL_INSERT:
        before = None
    elif first.pgh_label == LABEL_BEFORE:
        before = values(first)
    else:
        # A group opening on the row as it became, with no record of what it
        # was: the before is not known, and is shown as not recorded.
        before = {}
    after = None if last.pgh_label == LABEL_DELETE else values(last)

    changes = []
    if before is None or after is None:
        # Added, removed, or both inside one action: list the values the row
        # held. A JSON column (a calculation's step-by-step breakdown) is left
        # out here; it is its own page's business, and shown key by key when it
        # changes.
        if before is None and after is None:
            action, shown, side = "added and removed", values(last), "after"
        elif before is None:
            action, shown, side = "added", after, "after"
        else:
            action, shown, side = "removed", values(last), "before"
        for f in fields_:
            if isinstance(f, models.JSONField):
                continue
            text = _format_value(f, shown[f.name], names)
            if text:
                pair = ("", text) if side == "after" else (text, "")
                changes.append(FieldChange(field_name(f), *pair))
        if not changes:
            return None
    else:
        action = "changed"
        for f in fields_:
            if f.name not in before:
                changes.append(
                    FieldChange(
                        field_name(f), "not recorded", _format_value(f, after[f.name], names)
                    )
                )
                continue
            old, new = before[f.name], after[f.name]
            if old == new:
                continue
            if isinstance(old, dict) and isinstance(new, dict):
                changes.extend(_dict_changes(f, old, new, names))
                continue
            changes.append(
                FieldChange(
                    field_name(f),
                    _format_value(f, old, names),
                    _format_value(f, new, names),
                )
            )
        if not changes:
            return None

    obj = live.get((label, obj_id))
    return ChangeRow(
        when=timezone.localtime(at),
        action=action,
        record_type=record_type_name(tracked),
        record_name=names.get((label, obj_id)) or f"#{obj_id} (removed)",
        record_url=_record_url(obj),
        who=who_for(metadata, people),
        note=str(metadata.get("note") or metadata.get("reason") or ""),
        changes=changes,
        model_label=label,
        object_id=obj_id,
    )


# -- The two readers ----------------------------------------------------------


def _day_start(value):
    return timezone.make_aware(datetime.combine(value, time.min))


def build_filters(*, record_type="", person="", since=None, until=None, object_id=None):
    """Validated filters: an unknown record type is dropped, dates become bounds."""
    from datetime import timedelta

    filters = {}
    if record_type and record_type in event_models():
        filters["record_type"] = record_type
    if person:
        filters["person"] = person
    if since is not None:
        filters["since"] = _day_start(since)
    if until is not None:
        filters["until"] = _day_start(until + timedelta(days=1))
    if object_id is not None and "record_type" in filters:
        filters["object_id"] = int(object_id)
    return filters


def recent_changes(filters, page=1, per_page=PAGE_SIZE):
    """One page of change rows (a Django ``Page``), newest first."""
    paginator = Paginator(_ChangeIndex(filters), per_page)
    return paginator.get_page(page)


def changes_for(obj, limit=PANEL_SIZE, fields=None):
    """The latest changes to one record, newest first.

    ``fields`` limits the rows to changes of those fields; a change that moved
    none of them is left out.
    """
    label = obj._meta.label
    if label not in event_models():
        return []
    filters = {"record_type": label, "object_id": obj.pk}
    if fields:
        filters["fields"] = set(fields)
    return _ChangeIndex(filters)[0:limit]


def people_choices():
    """(value, name) for the person filter: everyone who has made a change."""
    from pghistory.models import Context

    User = apps.get_model("core", "User")
    ids = set()
    for value in (
        Context.objects.filter(metadata__has_key="user")
        .values_list("metadata__user", flat=True)
        .distinct()
    ):
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    users = sorted(User.objects.filter(pk__in=ids), key=lambda u: person_name(u).lower())
    return [(str(u.pk), person_name(u)) for u in users]
